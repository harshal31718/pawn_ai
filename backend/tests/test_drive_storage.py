"""Tests for DriveStorage's own root-folder resolution (storage/drive.py).

Covers the deterministic-root-selection fix (plan_open_issues_2026-07-14.md
§2.2): a pre-existing race (fixed at the drive_factory layer, commit
2146b07) could leave some users with more than one "PAWN" root folder in
Drive. Drive's files.list has no guaranteed ordering without an explicit
orderBy, so two separate DriveStorage instances could previously resolve to
DIFFERENT roots and silently see different subsets of that user's data.
get_or_create_root() now orders by createdTime ascending and always picks
the oldest -- deterministic across every call/instance, and logs a warning
when duplicates are found instead of silently picking one. This does NOT
merge or delete anything -- an actual multi-root merge still needs manual
review.

DriveStorage's constructor talks to the real Google OAuth/Drive client
libraries, so every test here patches _build_service to avoid any real
network access, per the pattern already used by test_drive_factory.py for
the higher-level drive_factory cache (which mocks _build_drive_for_user
instead -- this file is the layer below that, DriveStorage's own query
logic)."""

from unittest.mock import patch

from app.storage.drive import DriveStorage
from app import constants


class _Exec:
    """Mimics a googleapiclient HttpRequest's .execute()."""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeFilesResource:
    def __init__(self, list_result=None, create_result=None):
        self._list_result = list_result if list_result is not None else {"files": []}
        self._create_result = create_result or {"id": "new-root"}
        self.list_calls = []
        self.create_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _Exec(self._list_result)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Exec(self._create_result)


class _FakeService:
    def __init__(self, files_resource):
        self._files_resource = files_resource

    def files(self):
        return self._files_resource


def _make_drive(files_resource, user_id="user-1") -> DriveStorage:
    fake_service = _FakeService(files_resource)
    with patch.object(DriveStorage, "_build_service", return_value=fake_service):
        return DriveStorage(
            access_token="tok", refresh_token="reftok", expires_at=None, user_id=user_id,
        )


def test_get_or_create_root_queries_ordered_by_created_time_ascending():
    """Without an explicit orderBy, Drive's files.list has no guaranteed
    stable ordering -- must request createdTime ascending so the oldest
    match is always files[0], deterministically, across every call."""
    files_resource = _FakeFilesResource(list_result={"files": [{"id": "root-1"}]})
    drive = _make_drive(files_resource)

    drive.get_or_create_root()

    assert files_resource.list_calls[0]["orderBy"] == "createdTime"


def test_get_or_create_root_picks_oldest_when_duplicates_exist():
    """Drive returns createdTime-ascending results -- files[0] is always the
    oldest folder, picked deterministically over the newer duplicate(s)."""
    files_resource = _FakeFilesResource(
        list_result={"files": [{"id": "old-root"}, {"id": "new-root-1"}, {"id": "new-root-2"}]}
    )
    drive = _make_drive(files_resource)

    root_id = drive.get_or_create_root()

    assert root_id == "old-root"
    assert files_resource.create_calls == []  # never creates when a root already exists


def test_get_or_create_root_logs_warning_on_duplicates(capsys):
    files_resource = _FakeFilesResource(
        list_result={"files": [{"id": "old-root"}, {"id": "new-root"}]}
    )
    drive = _make_drive(files_resource, user_id="user-42")

    drive.get_or_create_root()

    err = capsys.readouterr().err
    assert "user-42" in err
    assert "2 duplicate" in err
    assert "old-root" in err and "new-root" in err


def test_get_or_create_root_no_warning_when_single_root(capsys):
    files_resource = _FakeFilesResource(list_result={"files": [{"id": "only-root"}]})
    drive = _make_drive(files_resource)

    drive.get_or_create_root()

    assert capsys.readouterr().err == ""


def test_get_or_create_root_creates_when_none_exist():
    files_resource = _FakeFilesResource(list_result={"files": []}, create_result={"id": "brand-new-root"})
    drive = _make_drive(files_resource)

    root_id = drive.get_or_create_root()

    assert root_id == "brand-new-root"
    assert len(files_resource.create_calls) == 1


def test_get_or_create_root_caches_result_no_repeat_query():
    files_resource = _FakeFilesResource(list_result={"files": [{"id": "root-1"}]})
    drive = _make_drive(files_resource)

    first = drive.get_or_create_root()
    second = drive.get_or_create_root()

    assert first == second == "root-1"
    assert len(files_resource.list_calls) == 1  # second call served from the in-memory cache


def test_get_or_create_root_uses_env_scoped_folder_name():
    """PAWN 2.0 Phase E.2: the root folder name is constants.DRIVE_ROOT_NAME
    (env-derived: "PAWN" in prod, "PAWN-dev" outside it), not a hardcoded
    literal — this is the single chokepoint that isolates all Drive data
    (chats/projects/uploads) between dev/staging and production."""
    files_resource = _FakeFilesResource(list_result={"files": []}, create_result={"id": "new-root"})
    drive = _make_drive(files_resource)

    drive.get_or_create_root()

    assert f"name = '{constants.DRIVE_ROOT_NAME}'" in files_resource.list_calls[0]["q"]
    assert files_resource.create_calls[0]["body"]["name"] == constants.DRIVE_ROOT_NAME
