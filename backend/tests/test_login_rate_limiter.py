"""Login-change plan: login_rate_limiter -- (ip, email) brute-force guard
for POST /auth/login-password."""
import time

from app.core import login_rate_limiter as lrl


def setup_function():
    lrl._failures.clear()


def test_not_blocked_before_max_failures():
    for _ in range(lrl.MAX_FAILURES - 1):
        lrl.record_failure("1.2.3.4", "u@example.com")
    assert lrl.is_blocked("1.2.3.4", "u@example.com") is False


def test_blocked_at_max_failures():
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "u@example.com")
    assert lrl.is_blocked("1.2.3.4", "u@example.com") is True


def test_different_ip_same_email_is_independent():
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "u@example.com")
    assert lrl.is_blocked("9.9.9.9", "u@example.com") is False


def test_different_email_same_ip_is_independent():
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "u@example.com")
    assert lrl.is_blocked("1.2.3.4", "other@example.com") is False


def test_email_matching_is_case_insensitive():
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "User@Example.com")
    assert lrl.is_blocked("1.2.3.4", "user@example.com") is True


def test_success_clears_failure_history():
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "u@example.com")
    lrl.record_success("1.2.3.4", "u@example.com")
    assert lrl.is_blocked("1.2.3.4", "u@example.com") is False


def test_failures_outside_the_window_expire(monkeypatch):
    now = time.time()
    for _ in range(lrl.MAX_FAILURES):
        lrl.record_failure("1.2.3.4", "u@example.com")
    monkeypatch.setattr(time, "time", lambda: now + lrl.WINDOW_SECONDS + 1)
    assert lrl.is_blocked("1.2.3.4", "u@example.com") is False
