"""Warm/persistent Kaggle image sessions + the unified durable job layer (Phase W).

Phase W keeps one Kaggle container alive so repeat images are fast. A running
Kaggle kernel is unreachable through Kaggle's batch API (no output until it
exits), so PAWN and the kernel rendezvous through Supabase: PAWN writes the
session/job rows with the service key (bypasses RLS), and the live kernel
reads/writes them with the PUBLIC anon key.

Two generation paths produce the same durable `image_jobs` row:
- **Warm session** (W.1): the live kernel loads the model once then serves a
  Supabase work-loop (FLUX → real GPU serve-loop, SDXL → CPU echo POC).
- **Cold one-shot** (W.1): PAWN runs the existing blocking Kaggle round-trip as a
  fire-and-forget background worker (`create_cold_job` + `run_cold_job`), de-duped
  per (user, model) — the server-tracked job that fixes the lost-result bug.

Security: only the public anon key + URL are injected into the notebook — the
Supabase master service key is NEVER injected; the backend keeps it server-side.

Every Supabase + Kaggle call here is BLOCKING — routes invoke them via
run_in_threadpool so the event loop is never stalled.
"""

import secrets as _secrets
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config
from app.constants import (
    COLD_JOB_MAX_WALLCLOCK_SECONDS,
    IMAGE_SESSION_HEARTBEAT_STALE_SECONDS,
    IMAGE_SESSION_MAX_DURATION_MINUTES,
    KAGGLE_SESSION_POLL_INTERVAL_SECONDS,
)
from app.core import generate, kaggle, key_store
from app.core.image_models import DEFAULT_IMAGE_MODEL, get_image_model
from app.db.supabase_client import get_db
from app.exceptions import NotConfiguredError

# Job statuses still owned by a (live) worker — used for de-dup + liveness.
_ACTIVE_JOB_STATUSES = ("queued", "running")

# Statuses that mean a kernel is (or should be) alive and serving.
_LIVE_STATUSES = ("starting", "ready")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse a Supabase timestamptz string into a tz-aware datetime (or None)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_creds(user_id: str) -> dict:
    cfg = key_store.get_kaggle(user_id)
    if not cfg or not cfg.get("username") or not cfg.get("api_token"):
        raise NotConfiguredError(
            "Add your Kaggle username + API token in the Image Lab to start a session."
        )
    return cfg


def _session_title(slug: str) -> str:
    """Kaggle derives a notebook's slug from its title, so they must stay in
    lockstep (same invariant as core/generate._kernel_title)."""
    return slug.replace("-", " ").title()


def _first(res) -> Optional[dict]:
    """First row of a Supabase response, or None — avoids .single() raising on 0 rows."""
    rows = res.data or []
    return rows[0] if rows else None


# --- Session lifecycle -------------------------------------------------------


def start_session(
    user_id: str,
    model: str = DEFAULT_IMAGE_MODEL,
    duration_minutes: int = 60,
    max_images: Optional[int] = None,
) -> dict:
    """Create a session row and push the CPU echo notebook (non-blocking).

    The push itself starts the Kaggle run, which loads the model once then loops
    on Supabase until the timer expires, the image cap is hit, or the session is
    stopped. Returns immediately. Which notebook/slug/accelerator is used comes
    from the model registry: FLUX → real GPU serve-loop, SDXL → CPU echo POC.
    """
    spec = get_image_model(model)  # validate model id (→ 400) before anything else
    if not spec.session_template or not spec.session_slug:
        raise NotConfiguredError(f"Warm sessions aren't available for '{model}' yet.")
    cfg = _load_creds(user_id)
    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        # Without these the kernel can't reach Supabase and would hang in 'starting'.
        raise NotConfiguredError(
            "Supabase isn't configured for warm sessions yet "
            "(set secrets/supabase_url and secrets/supabase_anon_key)."
        )
    db = get_db()

    # Evict any prior live session for this (user, model): mark it ended so its
    # kernel exits on the next poll and the panel shows a single current session.
    db.table("image_sessions").update({"status": "ended"}).eq("user_id", user_id).eq(
        "model", model
    ).in_("status", list(_LIVE_STATUSES)).execute()

    duration = max(1, min(int(duration_minutes), IMAGE_SESSION_MAX_DURATION_MINUTES))
    expires_at = _now() + timedelta(minutes=duration)
    session_token = _secrets.token_urlsafe(24)

    inserted = (
        db.table("image_sessions")
        .insert(
            {
                "user_id": user_id,
                "model": model,
                "session_token": session_token,
                "status": "starting",
                "expires_at": _iso(expires_at),
                "max_images": max_images,
            }
        )
        .execute()
    )
    session_id = inserted.data[0]["id"]

    payload = {
        "session_id": session_id,
        "supabase_url": config.SUPABASE_URL,
        "anon_key": config.SUPABASE_ANON_KEY,
        "session_token": session_token,
        "model": model,
        "expires_at": _iso(expires_at),
        "poll_interval": KAGGLE_SESSION_POLL_INTERVAL_SECONDS,
        "max_images": max_images,
    }
    source = kaggle.inject_payload(
        spec.session_template.read_text(encoding="utf-8"), payload
    )
    # Internet on so the kernel reaches Supabase. GPU + dataset for a real serve
    # loop (FLUX); CPU/no-dataset for the echo POC (SDXL). Single non-blocking
    # push — the run loads then loops on its own.
    kaggle.deploy_kernel(
        username=cfg["username"],
        api_token=cfg["api_token"],
        kernel_name=spec.session_slug,
        title=_session_title(spec.session_slug),
        source=source,
        enable_gpu=spec.session_gpu,
        enable_internet=True,
        dataset_sources=[spec.dataset] if spec.session_gpu else [],
        accelerator=spec.accelerator if spec.session_gpu else None,
    )
    return {"session_id": session_id, "expires_at": _iso(expires_at), "status": "starting"}


def extend_session(user_id: str, session_id: str, add_minutes: int = 30) -> dict:
    """Bump a session's `expires_at` (capped so the total never exceeds the Kaggle
    run-time backstop). The kernel reads the new deadline on its next poll."""
    db = get_db()
    sess = _session_row(db, user_id, session_id)
    if sess is None:
        raise NotConfiguredError("That session no longer exists. Start a new session.")
    if not _is_alive(sess):
        # The kernel has already exited; bumping expires_at would be a no-op it
        # never reads. Tell the caller to start a fresh session.
        raise NotConfiguredError("That session isn't running anymore. Start a new session.")
    current = _parse_ts(sess.get("expires_at")) or _now()
    new_expiry = current + timedelta(minutes=max(1, int(add_minutes)))
    # Cap total remaining runtime at the backstop measured from now.
    hard_cap = _now() + timedelta(minutes=IMAGE_SESSION_MAX_DURATION_MINUTES)
    if new_expiry > hard_cap:
        new_expiry = hard_cap
    db.table("image_sessions").update({"expires_at": _iso(new_expiry)}).eq(
        "id", session_id
    ).eq("user_id", user_id).execute()
    return {"session_id": session_id, "expires_at": _iso(new_expiry)}


def _latest_session(db, user_id: str, model: str) -> Optional[dict]:
    res = (
        db.table("image_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("model", model)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return _first(res)


def _is_alive(s: dict) -> bool:
    if s.get("status") not in _LIVE_STATUSES:
        return False
    expires = _parse_ts(s.get("expires_at"))
    if expires is not None and _now() >= expires:
        return False
    # 'starting' has no heartbeat yet (kernel still booting) — alive until expiry.
    if s.get("status") == "ready":
        hb = _parse_ts(s.get("heartbeat_at"))
        if hb is None:
            return False
        if (_now() - hb).total_seconds() > IMAGE_SESSION_HEARTBEAT_STALE_SECONDS:
            return False
    return True


def get_session_status(user_id: str, model: str = DEFAULT_IMAGE_MODEL) -> dict:
    db = get_db()
    s = _latest_session(db, user_id, model)
    if s is None:
        return {"status": "none", "alive": False}
    return {
        "session_id": s["id"],
        "status": s["status"],
        "expires_at": s.get("expires_at"),
        "images_done": s.get("images_done", 0),
        "max_images": s.get("max_images"),
        "alive": _is_alive(s),
    }


def stop_session(user_id: str, session_id: str) -> None:
    """Cooperative stop — flag the session; the kernel exits on its next poll."""
    db = get_db()
    db.table("image_sessions").update({"status": "stopping"}).eq("id", session_id).eq(
        "user_id", user_id
    ).execute()


# --- Jobs (W.0: warm session echo jobs only) ---------------------------------


def _session_row(db, user_id: str, session_id: str) -> Optional[dict]:
    res = (
        db.table("image_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return _first(res)


def submit_session_job(user_id: str, session_id: str, prompt: str) -> str:
    """Insert a queued job for a live session; the kernel picks it up and writes
    the result row. Returns the new job id."""
    db = get_db()
    sess = _session_row(db, user_id, session_id)
    if sess is None:
        raise NotConfiguredError("That session no longer exists. Start a new session.")
    if not _is_alive(sess):
        # A stopping/ended/expired session has no kernel to pick the job up — it
        # would queue forever. Surface it as a 412 so the caller restarts.
        raise NotConfiguredError("That session isn't running anymore. Start a new session.")
    inserted = (
        db.table("image_jobs")
        .insert(
            {
                "user_id": user_id,
                "session_id": session_id,
                "model": sess["model"],
                "prompt": prompt,
                "status": "queued",
            }
        )
        .execute()
    )
    return inserted.data[0]["id"]


def get_job(user_id: str, job_id: str) -> Optional[dict]:
    """Fetch one job (scoped to the owner), or None if it doesn't exist."""
    db = get_db()
    res = (
        db.table("image_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    row = _first(res)
    if row is None:
        return None
    return {
        "job_id": row["id"],
        "status": row["status"],
        "model": row.get("model"),
        "prompt": row.get("prompt"),
        "image_b64": row.get("image_b64"),
        "mime": row.get("mime"),
        "via": row.get("via"),
        "error": row.get("error"),
        "created_at": row.get("created_at"),
    }


# --- Cold one-shot jobs (durable background path — the lost-result bug fix) ---
# A cold job has session_id NULL: PAWN runs the existing blocking Kaggle round-trip
# as a fire-and-forget background task and writes the result back onto the row, so
# the frontend tracks it from the server (survives refresh) and the Generate button
# is disabled while one is in flight (no duplicate submit).

# Columns the monitor panel needs — deliberately EXCLUDES image_b64 so the list
# stays light; bytes are fetched lazily via get_job when a thumbnail is opened.
_JOB_LIST_COLUMNS = (
    "id, session_id, model, prompt, status, mime, via, error, "
    "created_at, started_at, done_at"
)


def _active_cold_job(db, user_id: str, model: str) -> Optional[dict]:
    """A queued/running cold job (no session) for this (user, model), if any."""
    res = (
        db.table("image_jobs")
        .select("id, status")
        .eq("user_id", user_id)
        .eq("model", model)
        .is_("session_id", "null")
        .in_("status", list(_ACTIVE_JOB_STATUSES))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return _first(res)


def create_cold_job(user_id: str, model: str, prompt: str) -> tuple[str, bool]:
    """Create (or de-dup to) a queued cold job. Returns (job_id, created).

    If this (user, model) already has a queued/running cold job, returns that id
    with created=False — the server-side half of "one run per model at a time"
    that survives a refresh / double-submit. Otherwise inserts a queued row.
    """
    get_image_model(model)  # validate (→ 400) before touching the DB
    db = get_db()
    existing = _active_cold_job(db, user_id, model)
    if existing is not None:
        return existing["id"], False
    inserted = (
        db.table("image_jobs")
        .insert(
            {
                "user_id": user_id,
                "session_id": None,
                "model": model,
                "prompt": prompt,
                "status": "queued",
            }
        )
        .execute()
    )
    return inserted.data[0]["id"], True


def run_cold_job(job_id: str) -> None:
    """Background worker for a cold job: run the blocking Kaggle round-trip and
    write the result back onto the row. Idempotent — only proceeds while the job
    is still 'queued'. Blocking — call via run_in_threadpool. Never raises: any
    failure is recorded on the row (the caller is fire-and-forget)."""
    db = get_db()
    res = db.table("image_jobs").select("*").eq("id", job_id).limit(1).execute()
    job = _first(res)
    if job is None or job.get("status") != "queued":
        return  # de-duped, already handled, or gone
    db.table("image_jobs").update(
        {"status": "running", "started_at": _iso(_now())}
    ).eq("id", job_id).execute()
    try:
        out = generate.generate_image(job["user_id"], job["prompt"], job["model"])
        db.table("image_jobs").update(
            {
                "status": "done",
                "image_b64": out["image"],
                "mime": out.get("mime", "image/png"),
                "via": out.get("via"),
                "done_at": _iso(_now()),
            }
        ).eq("id", job_id).execute()
    except Exception as e:
        # Fire-and-forget worker must never raise — record a bounded message on the
        # row (truncated so a Kaggle HTTP error body can't bloat/leak into the UI).
        print(f"cold job {job_id} failed: {e}", file=sys.stderr)
        db.table("image_jobs").update(
            {"status": "error", "error": str(e)[:300], "done_at": _iso(_now())}
        ).eq("id", job_id).execute()


def reap_stale_jobs(user_id: str) -> None:
    """Mark a cold job stuck 'running' past the max wall-clock as 'error' so the
    monitor never hangs on a worker that died (e.g. a backend restart dropped the
    in-flight task). Best-effort — never blocks the caller."""
    cutoff = _iso(_now() - timedelta(seconds=COLD_JOB_MAX_WALLCLOCK_SECONDS))
    try:
        db = get_db()
        db.table("image_jobs").update(
            {"status": "error", "error": "worker lost (timed out)", "done_at": _iso(_now())}
        ).eq("user_id", user_id).is_("session_id", "null").eq("status", "running").lt(
            "started_at", cutoff
        ).execute()
    except Exception as e:
        print(f"reap_stale_jobs failed for {user_id}: {e}", file=sys.stderr)


def list_jobs(user_id: str, model: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Recent jobs for the monitor panel (newest first), WITHOUT image bytes.
    Reaps stale cold jobs first so the panel self-heals."""
    reap_stale_jobs(user_id)
    db = get_db()
    q = db.table("image_jobs").select(_JOB_LIST_COLUMNS).eq("user_id", user_id)
    if model:
        q = q.eq("model", model)
    res = q.order("created_at", desc=True).limit(limit).execute()
    return [
        {
            "job_id": r["id"],
            "session_id": r.get("session_id"),
            "model": r.get("model"),
            "prompt": r.get("prompt"),
            "status": r.get("status"),
            "mime": r.get("mime"),
            "via": r.get("via"),
            "error": r.get("error"),
            "created_at": r.get("created_at"),
            "done_at": r.get("done_at"),
            "has_image": r.get("status") == "done",
        }
        for r in (res.data or [])
    ]
