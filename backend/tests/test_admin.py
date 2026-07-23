"""PAWN 2.0 Phase B.1: require_admin dependency + is_admin() helper.

ADMIN_EMAIL is hardcoded in app.constants -- no schema/JWT change. Route-level
enforcement (403 for non-admins) is covered per-route once Phase B.5's admin
routes exist; this file covers the shared helper in isolation.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.constants import ADMIN_EMAIL
from app.core.admin import is_admin, require_admin


def test_is_admin_true_for_the_admin_email():
    assert is_admin(ADMIN_EMAIL) is True


def test_is_admin_false_for_any_other_email():
    assert is_admin("someone-else@example.com") is False


def test_is_admin_false_for_none_or_empty():
    assert is_admin(None) is False
    assert is_admin("") is False


def test_require_admin_passes_for_admin_email():
    request = SimpleNamespace(state=SimpleNamespace(email=ADMIN_EMAIL))
    require_admin(request)  # must not raise


def test_require_admin_raises_403_for_non_admin():
    request = SimpleNamespace(state=SimpleNamespace(email="user@example.com"))
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request)
    assert exc_info.value.status_code == 403


def test_require_admin_raises_403_when_email_missing():
    """Defensive: a request.state with no email attribute at all (shouldn't
    happen post-AuthMiddleware, but require_admin must not raise AttributeError)."""
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request)
    assert exc_info.value.status_code == 403
