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

import httpx

from app.constants import (
    KAGGLE_API_BASE,
    KAGGLE_HTTP_TIMEOUT_SECONDS,
    KAGGLE_POLL_INTERVAL_SECONDS,
    KAGGLE_RUN_TIMEOUT_SECONDS,
)
from app.exceptions import KaggleError

# Kernel statuses (lower-cased) that mean "stop polling".
_DONE = {"complete", "completed"}
_FAILED = {"error", "cancelacknowledged", "cancelrequested", "cancelled", "canceled"}

_PLACEHOLDER = "__PAWN_PAYLOAD_B64__"


def inject_payload(template_text: str, payload: dict) -> str:
    """Base64-encode `payload` (JSON) and substitute it into the template.

    The payload is never string-interpolated as code — the kernel base64-decodes
    it at runtime, so arbitrary user input cannot break or inject kernel source.
    """
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    if _PLACEHOLDER not in template_text:
        raise KaggleError("Template kernel is missing the payload placeholder.")
    return template_text.replace(_PLACEHOLDER, encoded)


def _raise_for_status(resp: httpx.Response, op: str) -> None:
    if resp.status_code in (401, 403):
        # Read endpoints accept any verified account; push requires phone verification.
        # 401 here usually means the account isn't in state to push kernels.
        raise KaggleError(
            "Kaggle rejected the request. For kernels/push this usually means "
            "the account hasn't completed phone verification — check "
            "kaggle.com → Settings → Phone Verification."
        )
    if resp.status_code >= 400:
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
        "datasetDataSources": [],
        "competitionDataSources": [],
        "kernelDataSources": [],
        "modelDataSources": [],
        "categoryIds": [],
    }
    resp = client.post("/kernels/push", json=body)
    _raise_for_status(resp, "push")
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise KaggleError(f"Kaggle push failed: {data['error']}")


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
    timeout: int = KAGGLE_RUN_TIMEOUT_SECONDS,
    poll_interval: int = KAGGLE_POLL_INTERVAL_SECONDS,
) -> bytes:
    """Push `source` to <username>/<kernel_name>, run it, and return the bytes of
    `output_filename` from its output. Blocking — call via run_in_threadpool."""
    headers = {}
    auth = None
    if api_token.startswith("KGAT_"):
        headers["Authorization"] = f"Bearer {api_token}"
    else:
        auth = (username, api_token)

    with httpx.Client(
        base_url=KAGGLE_API_BASE, auth=auth, headers=headers, timeout=KAGGLE_HTTP_TIMEOUT_SECONDS
    ) as client:
        _push(
            client,
            username,
            kernel_name,
            title,
            source,
            enable_gpu=enable_gpu,
            enable_internet=enable_internet,
        )
        _wait_until_complete(
            client, username, kernel_name, timeout=timeout, poll_interval=poll_interval
        )
        return _fetch_output_file(client, username, kernel_name, output_filename)
