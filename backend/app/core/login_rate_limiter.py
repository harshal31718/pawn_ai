"""Login-change plan (2026-07-23): brute-force protection for
POST /auth/login-password.

Distinct from core/rate_limiter.py's EndpointRateLimiter (keyed
(user_id, endpoint_id) for BYOK provider quotas -- wrong shape here, since
no user_id exists before a successful login). This is a small, in-memory
sibling keyed (ip, email): a sliding 15-minute window, blocking after 8
failures. Deliberately in-memory only (unlike endpoint quota, a restart
resetting login attempt counters is an acceptable, non-security-critical
tradeoff -- the alternative, a Postgres write on every failed login attempt,
isn't worth it for a local/dev-scale deployment).
"""
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 8

_failures: Dict[Tuple[str, str], deque] = defaultdict(deque)


def _key(ip: str, email: str) -> Tuple[str, str]:
    return (ip, email.lower())


def _prune(dq: deque, now: float) -> None:
    cutoff = now - WINDOW_SECONDS
    while dq and dq[0] < cutoff:
        dq.popleft()


def is_blocked(ip: str, email: str) -> bool:
    """True if this (ip, email) pair has hit MAX_FAILURES within the
    current sliding window."""
    now = time.time()
    dq = _failures[_key(ip, email)]
    _prune(dq, now)
    return len(dq) >= MAX_FAILURES


def record_failure(ip: str, email: str) -> None:
    now = time.time()
    dq = _failures[_key(ip, email)]
    _prune(dq, now)
    dq.append(now)


def record_success(ip: str, email: str) -> None:
    """Clear this pair's failure history on a successful login."""
    _failures.pop(_key(ip, email), None)
