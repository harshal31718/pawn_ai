"""Thin client over the Kaggle public REST API (the same base the official
`kaggle` CLI wraps). Used to run a PAWN-managed template kernel inside the
*user's own* Kaggle account and pull its output.

Auth is HTTP Basic (username : api_token). All calls are BLOCKING (synchronous
httpx) and MUST be invoked off the event loop via run_in_threadpool — a kernel
run takes minutes (queue + container start + execution).

NOTE: the exact push/status/output wire contract is the spike flagged in
plan_v4 ("verify the Kaggle REST contract"). It is centralised here so it can be
corrected in one place once exercised against real credentials.
"""

import base64
import json
import time
from typing import Optional

import httpx

from app.constants import (
    KAGGLE_API_BASE,
    KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS,
    KAGGLE_HTTP_TIMEOUT_SECONDS,
    KAGGLE_POLL_INTERVAL_SECONDS,
    KAGGLE_RUN_TIMEOUT_SECONDS,
)
from app.exceptions import KaggleError

# Kernel statuses (lower-cased) that mean "stop polling".
_DONE = {"complete", "completed"}
_FAILED = {"error", "cancelacknowledged", "cancelrequested", "cancelled", "canceled"}

# Public union of the two: any status meaning "this kernel run is over" — used by
# image_session's warm-session dead-kernel probe to tell a genuinely-finished run
# apart from one that's still queued/running on Kaggle's side.
TERMINAL_KERNEL_STATUSES = frozenset(_DONE | _FAILED)

_PLACEHOLDER = "__PAWN_PAYLOAD_B64__"


class _KaggleConflict(Exception):
    """Internal: a push returned HTTP 409 (a kernel version is still being created
    or a run is in flight). Retriable — wait for the slug to settle and push again.

    Carries Kaggle's response body (`detail`) so a persistent conflict surfaces the
    real reason instead of a bare "HTTP 409"."""

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail)


def inject_payload(template_text: str, payload: dict) -> str:
    """Base64-encode `payload` (JSON) and substitute it into the template.

    The payload is never string-interpolated as code — the kernel base64-decodes
    it at runtime, so arbitrary user input cannot break or inject kernel source.
    """
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    if _PLACEHOLDER not in template_text:
        raise KaggleError("Template kernel is missing the payload placeholder.")
    return template_text.replace(_PLACEHOLDER, encoded)


def _client(username: str, api_token: str) -> httpx.Client:
    """Build an authed Kaggle REST client.

    General Access Tokens (KGAT_...) authenticate via Bearer; classic
    username:key pairs use HTTP Basic. Centralised so push/run/deploy agree.
    """
    headers: dict[str, str] = {}
    auth = None
    if api_token.startswith("KGAT_"):
        headers["Authorization"] = f"Bearer {api_token}"
    else:
        auth = (username, api_token)
    return httpx.Client(
        base_url=KAGGLE_API_BASE,
        auth=auth,
        headers=headers,
        timeout=KAGGLE_HTTP_TIMEOUT_SECONDS,
    )


def _raise_for_status(resp: httpx.Response, op: str) -> None:
    if resp.status_code == 401:
        # A bare 401 ("Unauthenticated") means Kaggle didn't accept the
        # credentials at all — the token is missing, malformed, expired, or
        # revoked. Distinct from 403, which means the token authenticated
        # fine but the account isn't allowed to do this specific thing.
        raise KaggleError(
            "Kaggle rejected your API token as invalid or expired. Generate a "
            "new token at kaggle.com → Settings → API, then re-save it in "
            "Image Lab → Kaggle Credentials."
        )
    if resp.status_code == 403:
        # Push requires phone verification; read endpoints accept any
        # verified account, so a 403 here (token was valid) usually means
        # the account hasn't completed phone verification.
        raise KaggleError(
            "Kaggle rejected the request. For kernels/push this usually means "
            "the account hasn't completed phone verification — check "
            "kaggle.com → Settings → Phone Verification."
        )
    if resp.status_code >= 400:
        body = (resp.text or "").strip()
        if "Maximum batch GPU session count" in body:
            raise KaggleError(
                "Kaggle GPU limit reached (max 2 concurrent GPU sessions). "
                "Stop an active warm session or wait for a running job to finish, then retry."
            )
        raise KaggleError(f"Kaggle {op} failed: HTTP {resp.status_code}")


def _push(
    client: httpx.Client,
    username: str,
    kernel_name: str,
    title: str,
    source: str,
    *,
    enable_gpu: bool,
    enable_internet: bool,
    dataset_sources: list[str] = None,
    accelerator: str = None,
) -> None:
    body = {
        "slug": f"{username}/{kernel_name}",
        "newTitle": title,
        "text": source,
        "language": "python",
        "kernelType": "notebook",
        "isPrivate": True,
        "enableGpu": enable_gpu,
        "enableTpu": False,
        "enableInternet": enable_internet,
        "datasetDataSources": dataset_sources or [],
        "competitionDataSources": [],
        "kernelDataSources": [],
        "modelDataSources": [],
        "categoryIds": [],
    }
    if accelerator:
        # Kaggle's /kernels/push reads the GPU type from `machineShape` (wire form
        # of the SDK's machine_shape / CLI --accelerator). The `accelerator` key is
        # silently ignored, which falls the run back to the default Pascal P100.
        # Valid values: NvidiaTeslaT4, NvidiaTeslaP100, Tpu1VmV38.
        body["machineShape"] = accelerator
    resp = client.post("/kernels/push", json=body)
    if resp.status_code == 409:
        # A previous version is still ingesting / a run is in flight. Caller retries.
        # Keep Kaggle's body so a persistent 409 surfaces the actual cause.
        raise _KaggleConflict((resp.text or "").strip()[:400])
    _raise_for_status(resp, "push")
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise KaggleError(f"Kaggle push failed: {data['error']}")


def _push_when_ready(
    client: httpx.Client,
    username: str,
    kernel_name: str,
    title: str,
    source: str,
    *,
    enable_gpu: bool,
    enable_internet: bool,
    dataset_sources: list[str] = None,
    accelerator: str = None,
    busy_wait_timeout: int,
    poll_interval: int,
) -> None:
    """Wait for the slug to be idle, then push — retrying on HTTP 409.

    A push always starts a run, and right after one Kaggle briefly reports the slug
    as neither running nor queued before the new version registers, so a plain
    `_wait_until_idle` can return early and the next push 409s. We loop: wait → push,
    and on 409 wait again, until the slug settles or `busy_wait_timeout` elapses.
    """
    deadline = time.monotonic() + busy_wait_timeout
    last_detail = ""
    while True:
        remaining = max(1, int(deadline - time.monotonic()))
        _wait_until_idle(
            client, username, kernel_name, timeout=remaining, poll_interval=poll_interval
        )
        try:
            _push(
                client,
                username,
                kernel_name,
                title,
                source,
                enable_gpu=enable_gpu,
                enable_internet=enable_internet,
                dataset_sources=dataset_sources,
                accelerator=accelerator,
            )
            return
        except _KaggleConflict as exc:
            last_detail = exc.detail or last_detail
            if time.monotonic() >= deadline:
                suffix = f" Kaggle said: {last_detail}" if last_detail else ""
                raise KaggleError(
                    "Kaggle kept rejecting the push with HTTP 409 (a kernel version "
                    "is stuck being created, or a run is still in flight). Open "
                    f"'{username}/{kernel_name}' on kaggle.com and stop/delete the "
                    f"stuck run, then try again.{suffix}"
                )
            time.sleep(poll_interval)


def _wait_until_complete(
    client: httpx.Client,
    username: str,
    kernel_name: str,
    *,
    timeout: int,
    poll_interval: int,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        resp = client.get(
            "/kernels/status",
            params={"userName": username, "kernelSlug": kernel_name},
        )
        _raise_for_status(resp, "status")
        data = resp.json()
        status = (data.get("status") or "").lower()
        if status in _DONE:
            return
        if status in _FAILED:
            raise KaggleError(f"Kaggle run failed: {data.get('failureMessage') or status}")
        if time.monotonic() > deadline:
            raise KaggleError("Kaggle run timed out before completing.")
        time.sleep(poll_interval)


def _wait_until_idle(
    client: httpx.Client,
    username: str,
    kernel_name: str,
    *,
    timeout: int,
    poll_interval: int,
) -> None:
    """Block until no run is in-flight on the slug, so a new run can be pushed.

    A Kaggle push always starts a run, so right after a deploy the warmup kernel is
    `queued`/`running`. Rather than erroring "Kaggle is busy", we wait for the slug
    to reach any terminal state (complete *or* failed — a prior failed warmup must
    not block a fresh run) before returning. Raises only if it stays busy past
    `timeout`. A non-200 status is treated as "can't tell" → let the push proceed.
    """
    deadline = time.monotonic() + timeout
    while True:
        resp = client.get(
            "/kernels/status",
            params={"userName": username, "kernelSlug": kernel_name},
        )
        if resp.status_code != 200:
            return
        status = (resp.json().get("status") or "").lower()
        if status not in ("running", "queued"):
            return
        if time.monotonic() > deadline:
            raise KaggleError(
                "Kaggle is still busy after waiting for the previous run "
                "(notebook warmup). Try again shortly."
            )
        time.sleep(poll_interval)


def _fetch_output_file(
    client: httpx.Client,
    username: str,
    kernel_name: str,
    output_filename: str,
) -> bytes:
    resp = client.get(
        "/kernels/output",
        params={"userName": username, "kernelSlug": kernel_name},
    )
    _raise_for_status(resp, "output")
    data = resp.json()
    files = data.get("files") or []
    target = next(
        (f for f in files if (f.get("fileName") or "").endswith(output_filename)),
        None,
    )
    if not target or not target.get("url"):
        raise KaggleError(f"Output file '{output_filename}' not found in kernel output.")
    # Output URLs are signed/temporary; fetch without the API auth header.
    dl = httpx.get(target["url"], timeout=KAGGLE_HTTP_TIMEOUT_SECONDS, follow_redirects=True)
    if dl.status_code >= 400:
        raise KaggleError(f"Failed to download Kaggle output: HTTP {dl.status_code}")
    return dl.content


def deploy_kernel(
    *,
    username: str,
    api_token: str,
    kernel_name: str,
    title: str,
    source: str,
    enable_gpu: bool = False,
    enable_internet: bool = False,
    dataset_sources: list[str] = None,
    accelerator: str = None,
) -> None:
    """First-time setup / warmup: push `source` to <username>/<kernel_name>.

    Deploy's only job is to verify creds and ensure the notebook exists. It does a
    SINGLE, non-blocking push and never waits for a busy slug to idle: if a run is
    already in flight (HTTP 409), the notebook already exists, so a verify/warmup
    deploy is already done. This keeps every model's deploy independent — a slow or
    stuck run on one slug can't stall (or starve the threadpool for) another model's
    deploy. Blocking only for the single HTTP call — invoke via run_in_threadpool."""
    with _client(username, api_token) as client:
        try:
            _push(
                client,
                username,
                kernel_name,
                title,
                source,
                enable_gpu=enable_gpu,
                enable_internet=enable_internet,
                dataset_sources=dataset_sources,
                accelerator=accelerator,
            )
        except _KaggleConflict:
            # A run/version is in flight on this slug — it already exists, so for a
            # warmup/verify deploy we're done. Never block waiting for it to idle.
            return


def kernel_status(username: str, api_token: str, kernel_name: str) -> Optional[str]:
    """Best-effort probe of a warm-session kernel's real state on Kaggle.

    Used by image_session's dead-kernel detection to get an independent signal
    when the notebook itself has stopped heartbeating over PostgREST (the normal
    liveness channel) — without this, a kernel that died silently (network
    failure, OOM, uncaught exception before the first heartbeat) is only caught
    by a long wall-clock timeout. One GET /kernels/status call, same endpoint
    _wait_until_complete already polls on the cold-run path.

    Returns Kaggle's lowercased status ("queued"/"running"/"complete"/"error"/...)
    or None when it can't be determined (any HTTP/network failure, non-200,
    missing field) — None always means "no information," never "kernel is gone."
    Callers must fall back to their own timeout-based detection on None. Never
    raises. Blocking — invoke via run_in_threadpool."""
    try:
        with _client(username, api_token) as client:
            resp = client.get(
                "/kernels/status",
                params={"userName": username, "kernelSlug": kernel_name},
            )
            if resp.status_code != 200:
                return None
            return (resp.json().get("status") or "").lower() or None
    except Exception:
        return None


def run_kernel(
    *,
    username: str,
    api_token: str,
    kernel_name: str,
    title: str,
    source: str,
    output_filename: str,
    enable_gpu: bool = False,
    enable_internet: bool = False,
    dataset_sources: list[str] = None,
    accelerator: str = None,
    timeout: int = KAGGLE_RUN_TIMEOUT_SECONDS,
    poll_interval: int = KAGGLE_POLL_INTERVAL_SECONDS,
    busy_wait_timeout: int = KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS,
) -> bytes:
    """Push `source` to <username>/<kernel_name>, run it, and return the bytes of
    `output_filename` from its output. Blocking — call via run_in_threadpool."""
    with _client(username, api_token) as client:
        # A push always starts a run, so an in-flight run (e.g. the deploy warmup)
        # would otherwise be rejected (or 409). Wait for the slug to free up, then push.
        _push_when_ready(
            client,
            username,
            kernel_name,
            title,
            source,
            enable_gpu=enable_gpu,
            enable_internet=enable_internet,
            dataset_sources=dataset_sources,
            accelerator=accelerator,
            busy_wait_timeout=busy_wait_timeout,
            poll_interval=poll_interval,
        )
        _wait_until_complete(
            client, username, kernel_name, timeout=timeout, poll_interval=poll_interval
        )
        return _fetch_output_file(client, username, kernel_name, output_filename)
