"""D.1 — env-var-driven deployment config (CORS, OAuth redirect, CSP).

Values are read once at import time (env var or Docker secret, per read_secret's
convention), so overrides are verified by reloading app.config with a patched
environment rather than mutating already-bound module globals.
"""

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from app import config
from app import main as app_main
from app.main import app

client = TestClient(app)


def test_defaults_match_local_dev_values(monkeypatch):
    for var in ("CORS_ORIGINS", "FRONTEND_URL", "OAUTH_REDIRECT_URI", "CSP_CONNECT_SRC"):
        monkeypatch.delenv(var, raising=False)
    importlib.reload(config)
    try:
        assert config.CORS_ORIGINS == "http://localhost:5173,http://localhost:5174"
        assert config.FRONTEND_URL == "http://localhost:5174"
        assert config.OAUTH_REDIRECT_URI == "http://localhost:8001/auth/callback"
        assert config.CSP_CONNECT_SRC == "http://localhost:8000"
    finally:
        importlib.reload(config)


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://pawn-example.duckdns.org")
    monkeypatch.setenv("FRONTEND_URL", "https://pawn-example.duckdns.org")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://pawn-example.duckdns.org/auth/callback")
    monkeypatch.setenv("CSP_CONNECT_SRC", "https://pawn-example.duckdns.org")
    importlib.reload(config)
    try:
        assert config.CORS_ORIGINS == "https://pawn-example.duckdns.org"
        assert config.FRONTEND_URL == "https://pawn-example.duckdns.org"
        assert config.OAUTH_REDIRECT_URI == "https://pawn-example.duckdns.org/auth/callback"
        assert config.CSP_CONNECT_SRC == "https://pawn-example.duckdns.org"
    finally:
        # monkeypatch only unsets these env vars once this test function returns,
        # so reloading here (while they're still set) would just re-apply the
        # override and leave the shared config module polluted for later tests.
        # Clear them ourselves first to actually restore the defaults.
        for var in ("CORS_ORIGINS", "FRONTEND_URL", "OAUTH_REDIRECT_URI", "CSP_CONNECT_SRC"):
            monkeypatch.delenv(var, raising=False)
        importlib.reload(config)


def test_cors_allows_configured_localhost_origins():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5174"


def test_cors_rejects_unknown_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_default_csp_connect_src_is_local_dev_value():
    response = client.get("/health")
    assert "connect-src 'self' http://localhost:8000" in response.headers["content-security-policy"]


def test_cors_origins_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    importlib.reload(config)
    try:
        with pytest.raises(ValueError, match="CORS_ORIGINS must not contain"):
            importlib.reload(app_main)
    finally:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        importlib.reload(config)
        importlib.reload(app_main)
