"""Regression tests for drive_factory's per-user DriveStorage cache.

Covers the concurrent-cache-miss race that produced duplicate "PAWN" root
folders in Drive: several requests missing the cache at once each used to
build (and thus each independently call get_or_create_root() on) their own
DriveStorage instance.
"""

import threading
import time
from unittest.mock import patch

import pytest

from app.core import drive_factory


@pytest.fixture(autouse=True)
def reset_drive_factory_state():
    """Each test gets a clean cache/lock table — module-level state otherwise
    leaks between tests (and between real users in prod, correctly, by design)."""
    drive_factory._CACHE.clear()
    drive_factory._BUILD_LOCKS.clear()
    yield
    drive_factory._CACHE.clear()
    drive_factory._BUILD_LOCKS.clear()


def test_concurrent_cache_miss_builds_exactly_once():
    """N threads racing a cold cache for the same user must trigger exactly one
    _build_drive_for_user call and all must receive the same instance back —
    the bug this guards against let each thread build (and create a Drive root
    folder for) its own separate instance."""
    build_calls = []
    build_started = threading.Event()
    release_build = threading.Event()

    def slow_build(user_id):
        build_calls.append(user_id)
        build_started.set()
        # Hold the "build" open long enough that other threads are guaranteed
        # to hit the cache-miss branch before this one finishes and caches.
        release_build.wait(timeout=5)
        return object()

    results = []

    def call():
        results.append(drive_factory.get_drive_for_user("user-1"))

    with patch.object(drive_factory, "_build_drive_for_user", side_effect=slow_build):
        threads = [threading.Thread(target=call) for _ in range(8)]
        threads[0].start()
        assert build_started.wait(timeout=5), "first thread never started building"
        # Start the rest while the first build is still in flight.
        for t in threads[1:]:
            t.start()
        time.sleep(0.05)
        release_build.set()
        for t in threads:
            t.join(timeout=5)

    assert build_calls == ["user-1"], (
        f"expected exactly one build for the racing threads, got {len(build_calls)}"
    )
    assert len(results) == 8
    assert all(r is results[0] for r in results), "threads received different DriveStorage instances"


def test_different_users_do_not_serialize_on_one_another():
    """Per-user locks — building for user A must not block user B's build."""
    release_a = threading.Event()
    entered_b = threading.Event()

    def build(user_id):
        if user_id == "user-a":
            release_a.wait(timeout=5)
        else:
            entered_b.set()
        return object()

    with patch.object(drive_factory, "_build_drive_for_user", side_effect=build):
        t_a = threading.Thread(target=drive_factory.get_drive_for_user, args=("user-a",))
        t_a.start()
        t_b = threading.Thread(target=drive_factory.get_drive_for_user, args=("user-b",))
        t_b.start()

        assert entered_b.wait(timeout=2), "user-b's build was blocked by user-a's in-flight build"
        release_a.set()
        t_a.join(timeout=5)
        t_b.join(timeout=5)


def test_cache_hit_skips_build():
    with patch.object(drive_factory, "_build_drive_for_user", return_value="drive-instance") as mock_build:
        first = drive_factory.get_drive_for_user("user-2")
        second = drive_factory.get_drive_for_user("user-2")

    assert first == "drive-instance"
    assert second == "drive-instance"
    mock_build.assert_called_once()


def test_evict_user_forces_rebuild():
    with patch.object(drive_factory, "_build_drive_for_user", return_value="drive-instance") as mock_build:
        drive_factory.get_drive_for_user("user-3")
        drive_factory.evict_user("user-3")
        drive_factory.get_drive_for_user("user-3")

    assert mock_build.call_count == 2
