"""PAWN 2.0 Phase E.1/E.3: constants.py's env-derived Drive root name and
Kaggle slug suffixing. kaggle_slug() reads the module-level PAWN_ENV binding
(a snapshot of config.PAWN_ENV taken at import time), so tests monkeypatch
that module attribute directly rather than the process environment — cheap
and avoids needing a module reload to observe the effect."""

from app import constants


def test_kaggle_slug_suffixes_in_dev(monkeypatch):
    monkeypatch.setattr(constants, "PAWN_ENV", "dev")
    assert constants.kaggle_slug("pawn-cube-poc") == "pawn-cube-poc-dev"


def test_kaggle_slug_unsuffixed_in_prod(monkeypatch):
    monkeypatch.setattr(constants, "PAWN_ENV", "prod")
    assert constants.kaggle_slug("pawn-cube-poc") == "pawn-cube-poc"


def test_drive_root_name_matches_current_env():
    """DRIVE_ROOT_NAME is computed once at import time from config.PAWN_ENV --
    unlike kaggle_slug (a function, re-evaluated per call), it can't be
    monkeypatched after the fact. Assert it's consistent with whatever
    PAWN_ENV this test process actually started with."""
    expected = "PAWN-dev" if constants.PAWN_ENV == "dev" else "PAWN"
    assert constants.DRIVE_ROOT_NAME == expected
