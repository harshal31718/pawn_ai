import time
import pytest
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.schemas import EndpointEntry

def test_rate_limiter_null_limits():
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-null",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=None,
        rpd_limit=None,
        active=True,
        last_verified=""
    )
    
    assert limiter.can_use(endpoint) is True
    for _ in range(100):
        limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is True

def test_rate_limiter_rpm_threshold():
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-rpm",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=10,
        rpd_limit=None,
        active=True,
        last_verified=""
    )
    
    for _ in range(8):
        limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is True
    
    limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is False

def test_rate_limiter_rpd_threshold():
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-rpd",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=None,
        rpd_limit=100,
        active=True,
        last_verified=""
    )
    
    for _ in range(89):
        limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is True
    
    limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is False

def test_rate_limiter_cooldown_expiry(monkeypatch):
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-cooldown",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=None,
        rpd_limit=None,
        active=True,
        last_verified=""
    )
    
    assert limiter.can_use(endpoint) is True
    
    now = time.time()
    limiter.record_429(endpoint.id, retry_after=60)
    assert limiter.can_use(endpoint) is False
    
    monkeypatch.setattr(time, "time", lambda: now + 61)
    assert limiter.can_use(endpoint) is True

def test_rate_limiter_rolling_window_reset(monkeypatch):
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-rolling",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=10,
        rpd_limit=None,
        active=True,
        last_verified=""
    )
    
    now = time.time()
    for _ in range(9):
        limiter.record_call(endpoint.id)
    assert limiter.can_use(endpoint) is False
    
    monkeypatch.setattr(time, "time", lambda: now + 61)
    assert limiter.can_use(endpoint) is True

def test_rate_limiter_dead_host_cooldown(monkeypatch):
    limiter = EndpointRateLimiter()
    endpoint = EndpointEntry(
        id="ep-test-dead",
        model_id="test-model",
        provider="google",
        provider_model_id="test-model-prov",
        base_url="https://api.google.com",
        priority=1,
        rpm_limit=None,
        rpd_limit=None,
        active=True,
        last_verified=""
    )
    
    limiter.record_connect_failure(endpoint.id)
    assert limiter.can_use(endpoint) is True
    
    now = time.time()
    limiter.record_connect_failure(endpoint.id)
    assert limiter.can_use(endpoint) is False
    
    monkeypatch.setattr(time, "time", lambda: now + 21)
    assert limiter.can_use(endpoint) is True
    
    limiter.record_success(endpoint.id)
    limiter.record_connect_failure(endpoint.id)
    assert limiter.can_use(endpoint) is True
