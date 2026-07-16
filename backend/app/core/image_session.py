"""Warm/persistent Kaggle image sessions + the unified durable job layer (Phase W).

Phase W keeps one Kaggle container alive so repeat images are fast. A running
Kaggle kernel is unreachable through Kaggle's batch API (no output until it
exits), so PAWN and the kernel rendezvous through the database: PAWN writes the
session/job rows directly via Postgres (the backend's own DB connection), and
the live kernel reads/writes them over HTTPS through the self-hosted PostgREST
instance, using the restricted `pawn_anon` Postgres role (RLS-scoped to just
these two tables — see postgres/schema.sql).

Two generation paths produce the same durable `image_jobs` row:
- **Warm session** (W.1): the live kernel loads the model once then serves a
  work-loop against PostgREST (FLUX -> real GPU serve-loop, SDXL -> CPU echo POC).
- **Cold one-shot** (W.1): PAWN runs the existing blocking Kaggle round-trip as a
  fire-and-forget background worker (`create_cold_job` + `run_cold_job`), de-duped
  per (user, model) -- the server-tracked job that fixes the lost-result bug.

Security: only the PostgREST public URL is injected into the notebook -- the
backend's own Postgres DSN (which can reach every table) is NEVER injected;
the kernel only ever talks to the restricted, RLS-scoped `pawn_anon` role via
PostgREST. Per-session-scoped JWT auth (narrower than "any pawn_anon request
can touch any live session's rows") remains deferred -- documented as
mandatory before multi-user, unchanged from the original Phase W decision.

Every DB + Kaggle call here is BLOCKING -- routes invoke them via
run_in_threadpool so the event loop is never stalled.
"""

import asyncio
import secrets as _secrets
import sys
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel
from psycopg.types.json import Json
from starlette.concurrency import run_in_threadpool

from app import config
from app.constants import (
    COLD_JOB_MAX_WALLCLOCK_SECONDS,
    IMAGE_SESSION_HEARTBEAT_STALE_SECONDS,
    IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS,
    IMAGE_SESSION_MAX_DURATION_MINUTES,
    IMAGE_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS,
    IMAGE_SESSION_STARTUP_PROBE_AFTER_SECONDS,
    IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS,
    KAGGLE_SESSION_POLL_INTERVAL_SECONDS,
)
from app.core import generate, kaggle, key_store
from app.core.image_models import DEFAULT_IMAGE_MODEL, get_image_model
from app.db.postgres_client import execute, fetchall, fetchone, transaction
from app.exceptions import NotConfiguredError

class ImageJobParams(BaseModel):
    width: int | None = None
    height: int | None = None
    num_inference_steps: int | None = None
    guidance_scale: float | None = None
    negative_prompt: str | None = None
    style_preset: str | None = None
    strength: float | None = None          # img2img: 0.1–1.0 (lower = closer to source)
    init_image_b64: str | None = None      # img2img: base64 source image (stored transiently)


# Job statuses still owned by a (live) worker -- used for de-dup + liveness.
_ACTIVE_JOB_STATUSES = ("queued", "running")

# Statuses that mean a kernel is (or should be) alive and serving.
# Includes the W.4 startup phases so a kernel mid-install/load isn't reaped.
_LIVE_STATUSES = frozenset({"starting", "installing", "loading_model", "ready"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_ts(value) -> Optional[datetime]:
    """Parse a Postgres timestamptz (already a datetime) or ISO string into a
    tz-aware datetime (or None)."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
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


# --- Session lifecycle -------------------------------------------------------


def start_session(
    user_id: str,
    model: str = DEFAULT_IMAGE_MODEL,
    duration_minutes: int = 60,
    max_images: Optional[int] = None,
) -> dict:
    """Create a session row and push the notebook (non-blocking).

    The push itself starts the Kaggle run, which loads the model once then loops
    against PostgREST until the timer expires, the image cap is hit, or the
    session is stopped. Returns immediately.
    """
    spec = get_image_model(model)  # validate model id before anything else
    if not spec.session_template or not spec.session_slug:
        raise NotConfiguredError(f"Warm sessions aren't available for '{model}' yet.")
    cfg = _load_creds(user_id)
    if not config.POSTGREST_PUBLIC_URL:
        raise NotConfiguredError(
            "PostgREST isn't configured for warm sessions yet "
            "(set POSTGREST_PUBLIC_URL once PAWN is deployed with the postgrest service)."
        )

    duration = max(1, min(int(duration_minutes), IMAGE_SESSION_MAX_DURATION_MINUTES))
    expires_at = _now() + timedelta(minutes=duration)
    session_token = _secrets.token_urlsafe(24)

    # Evict any prior live session for this (user, model) and insert the new one
    # atomically -- avoids a crash between the two leaving neither state. Two
    # concurrent start_session calls for the same (user, model) could still both
    # pass eviction and each insert a "starting" row (no DB-level uniqueness
    # constraint on live sessions per (user, model) yet); the per-(user,model)
    # asyncio.Lock in routes/generate.py prevents that within one backend
    # process, which covers the single/few-user scale this app runs at today.
    with transaction() as tx:
        tx.execute(
            """
            update image_sessions set status = 'ended'
            where user_id = %s and model = %s and status = ANY(%s)
            """,
            (user_id, model, list(_LIVE_STATUSES)),
        )
        row = tx.fetchone(
            """
            insert into image_sessions (user_id, model, session_token, status, expires_at, max_images)
            values (%s, %s, %s, 'starting', %s, %s)
            returning id
            """,
            (user_id, model, session_token, _iso(expires_at), max_images),
        )
    session_id = str(row["id"])

    payload = {
        "session_id": session_id,
        "postgrest_url": config.POSTGREST_PUBLIC_URL,
        "session_token": session_token,
        "model": model,
        "expires_at": _iso(expires_at),
        "poll_interval": KAGGLE_SESSION_POLL_INTERVAL_SECONDS,
        "max_images": max_images,
    }
    source = kaggle.inject_payload(
        spec.session_template.read_text(encoding="utf-8"), payload
    )
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
    """Bump a session's `expires_at` (capped at the max backstop)."""
    # Liveness check + update in one transaction, so a session that dies
    # between the two can't still be extended.
    with transaction() as tx:
        sess = _session_row(user_id, session_id, _fetchone=tx.fetchone)
        if sess is None:
            raise NotConfiguredError("That session no longer exists. Start a new session.")
        if not _is_alive(sess):
            raise NotConfiguredError("That session isn't running anymore. Start a new session.")
        current = _parse_ts(sess.get("expires_at")) or _now()
        new_expiry = current + timedelta(minutes=max(1, int(add_minutes)))
        hard_cap = _now() + timedelta(minutes=IMAGE_SESSION_MAX_DURATION_MINUTES)
        if new_expiry > hard_cap:
            new_expiry = hard_cap
        tx.execute(
            "update image_sessions set expires_at = %s where id = %s and user_id = %s",
            (_iso(new_expiry), session_id, user_id),
        )
    return {"session_id": session_id, "expires_at": _iso(new_expiry)}


def _latest_session(user_id: str, model: str) -> Optional[dict]:
    return fetchone(
        """
        select * from image_sessions
        where user_id = %s and model = %s
        order by created_at desc limit 1
        """,
        (user_id, model),
    )


# Only 'ready' sessions are expected to send heartbeats; warmup phases are exempt.
_HEARTBEAT_CHECKED_STATUSES = frozenset({"ready"})


def _is_alive(s: dict) -> bool:
    """True if the session's kernel is (or should be) running.

    Warmup phases (starting / installing / loading_model) are exempt from the
    heartbeat check -- the kernel is busy booting and sends no heartbeat during
    that time. Heartbeat staleness is only checked for 'ready' sessions.
    Expiry is always checked.
    """
    if s.get("status") not in _LIVE_STATUSES:
        return False
    expires = _parse_ts(s.get("expires_at"))
    if expires is not None and _now() >= expires:
        return False
    if s.get("status") in _HEARTBEAT_CHECKED_STATUSES:
        hb = _parse_ts(s.get("heartbeat_at"))
        if hb is None:
            return False
        if (_now() - hb).total_seconds() > IMAGE_SESSION_HEARTBEAT_STALE_SECONDS:
            return False
    return True


# In-process, per-session cache of the last Kaggle kernel-status probe result
# (monotonic timestamp, status). Single-process uvicorn -- module-level state
# is fine, no cross-process sync needed. Keyed by session_id so unrelated
# sessions/users never share a throttle window.
_probe_cache: dict[str, tuple[float, Optional[str]]] = {}


def _kernel_probe(user_id: str, model: str, session_id: str) -> Optional[str]:
    """Best-effort, throttled GET /kernels/status for a warmup session's real
    Kaggle kernel state -- the independent signal get_session_status uses to
    detect a dead kernel fast instead of waiting on IMAGE_SESSION_STARTUP_
    TIMEOUT_SECONDS (900s) alone. Returns Kaggle's lowercased status or None
    (no information: no Kaggle creds, an API failure, or malformed data) --
    None is never itself evidence the kernel is dead, just that this probe
    can't help this time; callers fall back to their own timeout logic.
    Never raises. Throttled to IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS per
    session_id so the frontend's 3s status poll doesn't hammer Kaggle's API."""
    now = _time.monotonic()
    cached = _probe_cache.get(session_id)
    if cached is not None and now - cached[0] < IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS:
        return cached[1]

    status: Optional[str] = None
    try:
        cfg = key_store.get_kaggle(user_id)
        if cfg and cfg.get("username") and cfg.get("api_token"):
            slug = get_image_model(model).session_slug
            if slug:
                status = kaggle.kernel_status(cfg["username"], cfg["api_token"], slug)
    except Exception:
        status = None

    _probe_cache[session_id] = (now, status)
    if len(_probe_cache) > 64:
        # Simple, single-process safeguard against unbounded growth over a
        # long backend uptime -- not a real LRU, just a periodic reset. Live
        # sessions re-populate their entry on the very next poll either way.
        _probe_cache.clear()
    return status


def get_session_status(user_id: str, model: str = DEFAULT_IMAGE_MODEL) -> dict:
    s = _latest_session(user_id, model)
    if s is None:
        return {"status": "none", "alive": False}

    # Auto-cleanup dead/stuck sessions
    status = s.get("status")

    if status in ("starting", "installing", "loading_model"):
        # The notebook's supervisor thread heartbeats during warmup too, so a
        # stale heartbeat here means the kernel died mid-startup (crash / OOM /
        # externally killed). Before the first heartbeat lands, or for an
        # older notebook that doesn't heartbeat during warmup, an independent
        # Kaggle kernel-status probe (_kernel_probe) gives a much faster
        # signal than the wall-clock startup timeout alone -- that timeout is
        # now only the backstop for when the probe itself has no information
        # (no Kaggle creds configured, or the Kaggle API is unreachable).
        hb = _parse_ts(s.get("heartbeat_at"))
        created = _parse_ts(s.get("created_at"))
        dead_reason = None
        if hb is not None:
            staleness = (_now() - hb).total_seconds()
            if staleness > IMAGE_SESSION_HEARTBEAT_STALE_SECONDS:
                dead_reason = (
                    "Session died during startup -- the Kaggle kernel stopped "
                    "sending heartbeats (crash, resource limit, or killed)."
                )
            elif staleness > IMAGE_SESSION_HEARTBEAT_STALE_SECONDS / 2:
                # Heartbeat going stale but not stale enough yet to be sure --
                # worth an early independent check rather than waiting out the
                # full window when Kaggle can already tell us it's over.
                probe = _kernel_probe(user_id, model, s["id"])
                if probe in kaggle.TERMINAL_KERNEL_STATUSES:
                    dead_reason = (
                        f"The Kaggle kernel is no longer running (Kaggle reports "
                        f"'{probe}') -- it exited or failed before the session "
                        "came up. Check the kernel log on kaggle.com/code."
                    )
        elif created is not None:
            age = (_now() - created).total_seconds()
            if age > IMAGE_SESSION_STARTUP_PROBE_AFTER_SECONDS:
                probe = _kernel_probe(user_id, model, s["id"])
                if probe in kaggle.TERMINAL_KERNEL_STATUSES:
                    dead_reason = (
                        f"The Kaggle kernel is no longer running (Kaggle reports "
                        f"'{probe}') -- it exited or failed before the session "
                        "came up. Check the kernel log on kaggle.com/code."
                    )
                elif probe == "running" and age > IMAGE_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS:
                    dead_reason = (
                        "The Kaggle kernel is running, but it has never reached "
                        "PAWN's database -- the PostgREST connection may be down "
                        "or misconfigured (tunnel, RLS token). Check the kernel "
                        "log on kaggle.com/code for '[pawn]' error lines."
                    )
                elif probe != "queued" and age > IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS:
                    dead_reason = (
                        "Session never finished starting up in time -- the Kaggle kernel "
                        "may have failed to install dependencies or load the model."
                    )
        if dead_reason is not None:
            try:
                execute(
                    "update image_sessions set status = 'error', error = %s where id = %s",
                    (dead_reason, s["id"]),
                )
            except Exception:
                pass
            s["status"] = "error"
            s["error"] = dead_reason
            _probe_cache.pop(s["id"], None)

    elif status == "stopping":
        # Cooperative stop only: Kaggle has no "cancel a running kernel" API,
        # so this flips a DB flag and waits for the kernel to notice on its
        # own next poll and exit. The age check MUST be measured from when
        # THIS stop was requested (stop_requested_at) -- using created_at (the
        # session's original start time) meant any session older than the
        # grace period got force-declared 'ended' on the very next poll after
        # Stop was clicked, regardless of whether the kernel had actually
        # exited (e.g. still mid-generation, or genuinely hung) -- PAWN was
        # confidently lying about the outcome. If the kernel doesn't confirm
        # within the grace period, say so honestly instead of guessing.
        basis = _parse_ts(s.get("stop_requested_at")) or _parse_ts(s.get("created_at"))
        if basis is not None and (_now() - basis).total_seconds() > 30:
            reason = (
                "Stop requested, but the Kaggle kernel didn't confirm exit in "
                "time -- it may still be running on Kaggle. Check kaggle.com/code "
                "if you're concerned about GPU usage."
            )
            try:
                execute(
                    "update image_sessions set status = 'error', error = %s where id = %s",
                    (reason, s["id"]),
                )
            except Exception:
                pass
            s["status"] = "error"
            s["error"] = reason

    elif status == "ready" and not _is_alive(s):
        # The kernel died/crashed/was killed on its own -- no Stop was ever
        # clicked. Nothing else in this codebase persists this (_is_alive() is
        # otherwise only computed fresh per-call, never written back), so the
        # UI would keep showing "ready" forever. Guard the UPDATE on
        # status='ready' so this can't race a concurrent graceful stop.
        stale_heartbeat = False
        hb = _parse_ts(s.get("heartbeat_at"))
        if hb is not None and (_now() - hb).total_seconds() > IMAGE_SESSION_HEARTBEAT_STALE_SECONDS:
            stale_heartbeat = True
        reason = (
            "Session heartbeat lost -- the Kaggle kernel likely crashed, hit a "
            "resource limit, or was killed unexpectedly."
            if stale_heartbeat else
            "Session exceeded its time limit without shutting down cleanly -- "
            "it may have become unresponsive."
        )
        try:
            execute(
                "update image_sessions set status = 'error', error = %s "
                "where id = %s and status = 'ready'",
                (reason, s["id"]),
            )
        except Exception:
            pass
        s["status"] = "error"
        s["error"] = reason

    return {
        "session_id": str(s["id"]),
        "status": s["status"],
        "error": s.get("error"),
        "expires_at": s.get("expires_at"),
        "created_at": s.get("created_at"),
        "images_done": s.get("images_done", 0),
        "max_images": s.get("max_images"),
        "alive": _is_alive(s),
    }


def stop_session(user_id: str, session_id: str) -> None:
    """Cooperative stop -- flag the session; the kernel exits on its next poll.

    Kaggle's API has no "cancel a running kernel" call, so this can only ever
    be a request the kernel notices and honors on its own -- it cannot force
    the kernel to actually exit. `stop_requested_at` records when THIS
    request was made (not when the session originally started) so
    get_session_status's grace-period check measures the right interval.
    """
    execute(
        "update image_sessions set status = 'stopping', stop_requested_at = now() "
        "where id = %s and user_id = %s",
        (session_id, user_id),
    )


# --- Jobs (warm session) -----------------------------------------------------


def _session_row(user_id: str, session_id: str, _fetchone=fetchone) -> Optional[dict]:
    """`_fetchone` defaults to the module-level fetchone; pass `tx.fetchone` to
    run this inside an existing transaction() block instead of its own connection."""
    return _fetchone(
        "select * from image_sessions where id = %s and user_id = %s limit 1",
        (session_id, user_id),
    )


def submit_session_job(
    user_id: str,
    session_id: str,
    prompt: str,
    params: Optional[ImageJobParams] = None,
) -> str:
    """Insert a queued job for a live (or warming-up) session.

    Jobs submitted during installing/loading_model queue up and are picked up
    FIFO once the kernel enters its serve loop. Only truly dead sessions
    (stopped/ended/expired) are rejected. Returns the new job id.
    """
    # Liveness check + insert in one transaction, so a session that dies
    # between the two can't still have a job queued against it.
    with transaction() as tx:
        sess = _session_row(user_id, session_id, _fetchone=tx.fetchone)
        if sess is None:
            raise NotConfiguredError("That session no longer exists. Start a new session.")
        if not _is_alive(sess):
            raise NotConfiguredError("That session isn't running anymore. Start a new session.")
        row = tx.fetchone(
            """
            insert into image_jobs (user_id, session_id, model, prompt, status, params)
            values (%s, %s, %s, %s, 'queued', %s)
            returning id
            """,
            (
                user_id,
                session_id,
                sess["model"],
                prompt,
                Json(params.model_dump(exclude_none=True) if params else {}),
            ),
        )
    return str(row["id"])


def get_job(user_id: str, job_id: str) -> Optional[dict]:
    """Fetch one job (scoped to the owner), or None if it doesn't exist."""
    row = fetchone(
        "select * from image_jobs where id = %s and user_id = %s limit 1",
        (job_id, user_id),
    )
    if row is None:
        return None
    return {
        "job_id": str(row["id"]),
        "status": row["status"],
        "model": row.get("model"),
        "prompt": row.get("prompt"),
        "image_b64": row.get("image_b64"),
        "mime": row.get("mime"),
        "via": row.get("via"),
        "error": row.get("error"),
        "created_at": row.get("created_at"),
    }


# --- Cold one-shot jobs ------------------------------------------------------
# A cold job has session_id NULL: PAWN runs the existing blocking Kaggle
# round-trip as a fire-and-forget background task and writes the result back
# onto the row, so the frontend tracks it from the server (survives refresh)
# and the Generate button is disabled while one is in flight.

# Columns the monitor panel needs -- deliberately EXCLUDES image_b64 so the
# list stays light; bytes are fetched lazily via get_job when opened.
_JOB_LIST_COLUMNS = (
    "id, session_id, model, prompt, status, mime, via, error, params, "
    "created_at, started_at, done_at"
)


def _active_cold_job(user_id: str, model: str) -> Optional[dict]:
    """A queued/running cold job (no session) for this (user, model), if any."""
    return fetchone(
        """
        select id, status from image_jobs
        where user_id = %s and model = %s and session_id is null
          and status = ANY(%s)
        order by created_at desc limit 1
        """,
        (user_id, model, list(_ACTIVE_JOB_STATUSES)),
    )


def create_cold_job(
    user_id: str,
    model: str,
    prompt: str,
    params: Optional[ImageJobParams] = None,
) -> tuple[str, bool]:
    """Create (or de-dup to) a queued cold job. Returns (job_id, created).

    Raises RuntimeError if a warm session is currently alive for this model.
    """
    get_image_model(model)  # validate before touching the DB
    latest = _latest_session(user_id, model)
    if latest is not None and _is_alive(latest):
        raise RuntimeError(
            f"A warm session is already running for '{model}'. "
            "Submit via the session -- use Generate on the warm session bar."
        )
    existing = _active_cold_job(user_id, model)
    if existing is not None:
        return str(existing["id"]), False
    row = fetchone(
        """
        insert into image_jobs (user_id, session_id, model, prompt, status, params)
        values (%s, NULL, %s, %s, 'queued', %s)
        returning id
        """,
        (user_id, model, prompt, Json(params.model_dump(exclude_none=True) if params else {})),
    )
    return str(row["id"]), True


def run_cold_job(job_id: str) -> None:
    """Background worker for a cold job: run the blocking Kaggle round-trip and
    write the result back onto the row. Idempotent -- only proceeds while the
    job is still 'queued'. Never raises: failures are recorded on the row."""
    job = fetchone("select * from image_jobs where id = %s limit 1", (job_id,))
    if job is None or job.get("status") != "queued":
        return  # de-duped, already handled, or gone
    execute(
        "update image_jobs set status = 'running', started_at = %s where id = %s",
        (_iso(_now()), job_id),
    )
    try:
        out = generate.generate_image(job["user_id"], job["prompt"], job["model"])
        execute(
            """
            update image_jobs
            set status = 'done', image_b64 = %s, mime = %s, via = %s, done_at = %s
            where id = %s
            """,
            (out["image"], out.get("mime", "image/png"), out.get("via"), _iso(_now()), job_id),
        )
    except Exception as e:
        print(f"cold job {job_id} failed: {e}", file=sys.stderr)
        execute(
            "update image_jobs set status = 'error', error = %s, done_at = %s where id = %s",
            (str(e)[:300], _iso(_now()), job_id),
        )


# --- Shared cold-job bg-task/lock state (F-1 fix) ---------------------------
# A kernel slug is single-writer, so two concurrent cold runs of the same
# (user, model) -- however they were triggered -- must never overlap. This
# used to be a per-caller-module lock/task-set (routes/generate.py had its
# own copy, and the chat generate_image tool duplicated it again), which only
# serialized runs triggered through the SAME entry point: a cold job started
# from Image Lab and one started from chat for the same (user, model) at
# roughly the same time could still race each other. Centralized here so
# every caller shares the same lock/task registry regardless of entry point.
_cold_job_locks: dict[str, asyncio.Lock] = {}
_cold_job_bg_tasks: set[asyncio.Task] = set()


def _cold_job_lock_for(key: str) -> asyncio.Lock:
    lock = _cold_job_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _cold_job_locks[key] = lock
    return lock


def spawn_cold_job_bg(user_id: str, model: str, job_id: str) -> None:
    """Fire-and-forget worker for a cold job, serialized per (user, model)
    across every caller. Strong ref held in _cold_job_bg_tasks -- asyncio
    only keeps a WEAK ref to a task, so without this a GC pass could collect
    a running worker mid-Kaggle-call and silently drop the job."""
    async def _run() -> None:
        async with _cold_job_lock_for(f"{user_id}:{model}"):
            await run_in_threadpool(run_cold_job, job_id)

    task = asyncio.create_task(_run())
    _cold_job_bg_tasks.add(task)
    task.add_done_callback(_cold_job_bg_tasks.discard)


def reap_stale_jobs(user_id: str) -> None:
    """Mark active jobs whose owner is gone as 'error' so the monitor never
    hangs on a ghost and the Generate button doesn't stay disabled forever.

    Rules:
    - Cold jobs stuck past max wall-clock: worker died (backend restart).
    - Session jobs (queued): reap for any session where _is_alive() is False,
      which covers both structurally dead sessions and heartbeat-stale ones
      (e.g. kernel killed externally while the session status is still 'ready').
    - Session jobs (running): also reap for non-alive sessions -- once the
      heartbeat stale threshold (90 s) has elapsed the kernel is truly gone,
      not merely busy (warm-session inference is fast; the cold-path kernel
      owns its own row via run_cold_job and has no session_id).
    """
    now = _now()
    cutoff = _iso(now - timedelta(seconds=COLD_JOB_MAX_WALLCLOCK_SECONDS))
    try:
        # Cold jobs: orphaned worker past wall-clock.
        execute(
            """
            update image_jobs
            set status = 'error', error = 'worker lost (timed out)', done_at = %s
            where user_id = %s and session_id is null
              and status = ANY(%s) and created_at < %s
            """,
            (_iso(now), user_id, list(_ACTIVE_JOB_STATUSES), cutoff),
        )

        # Session jobs: reap queued + running jobs for any non-alive session.
        # Fetching full rows so _is_alive() can check heartbeat_at + expires_at.
        sessions = fetchall("select * from image_sessions where user_id = %s", (user_id,))
        non_alive_ids = [s["id"] for s in sessions if not _is_alive(s)]
        if non_alive_ids:
            execute(
                """
                update image_jobs
                set status = 'error', error = 'session ended before this job ran', done_at = %s
                where user_id = %s and session_id = ANY(%s) and status = 'queued'
                """,
                (_iso(now), user_id, non_alive_ids),
            )
            execute(
                """
                update image_jobs
                set status = 'error', error = 'Session terminated unexpectedly', done_at = %s
                where user_id = %s and session_id = ANY(%s) and status = 'running'
                """,
                (_iso(now), user_id, non_alive_ids),
            )
    except Exception as e:
        print(f"reap_stale_jobs failed for {user_id}: {e}", file=sys.stderr)


def list_jobs(user_id: str, model: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Recent jobs for the monitor panel (newest first), WITHOUT image bytes.
    Reaps stale cold jobs first so the panel self-heals."""
    reap_stale_jobs(user_id)
    if model:
        rows = fetchall(
            f"""
            select {_JOB_LIST_COLUMNS} from image_jobs
            where user_id = %s and model = %s
            order by created_at desc limit %s
            """,
            (user_id, model, limit),
        )
    else:
        rows = fetchall(
            f"""
            select {_JOB_LIST_COLUMNS} from image_jobs
            where user_id = %s
            order by created_at desc limit %s
            """,
            (user_id, limit),
        )
    return [
        {
            "job_id": str(r["id"]),
            "session_id": str(r["session_id"]) if r.get("session_id") else None,
            "model": r.get("model"),
            "prompt": r.get("prompt"),
            "status": r.get("status"),
            "mime": r.get("mime"),
            "via": r.get("via"),
            "error": r.get("error"),
            "params": r.get("params"),
            "created_at": r.get("created_at"),
            "started_at": r.get("started_at"),
            "done_at": r.get("done_at"),
            "has_image": r.get("status") == "done",
        }
        for r in rows
    ]
