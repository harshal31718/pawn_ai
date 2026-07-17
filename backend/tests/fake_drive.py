"""In-memory fake for DriveStorage's low-level primitives.

Google Drive is the only storage backend for user data (see
core/drive_factory.py) — there is no local-filesystem fallback anymore, so
tests exercising conversations/uploads/memory-summary/crypto-salt routes now
run the REAL conversations_drive.py/documents_drive.py logic against this fake
in-memory folder/file tree instead of the real Drive API, rather than mocking
those modules' functions directly.

Usage:
    fake_drive = FakeDriveStorage()
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        ...  # every route's require_drive_for_user() now returns fake_drive

Patching `get_drive_for_user` at its defining module (app.core.drive_factory)
is enough for every route module — require_drive_for_user() resolves
get_drive_for_user by bare name in that same module's namespace at call time,
regardless of which module imported require_drive_for_user by reference.
"""


class FakeDriveStorage:
    def __init__(self):
        self._next_id = 0
        self._folders: dict[str, dict] = {}  # id -> {"name": str, "parent": str|None}
        self._files: dict[str, dict] = {}     # id -> {"name": str, "parent": str, "content": str}
        self._root_id: str | None = None

    def _new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def get_or_create_root(self) -> str:
        if self._root_id is None:
            self._root_id = self._new_id("folder")
            self._folders[self._root_id] = {"name": "PAWN", "parent": None}
        return self._root_id

    def get_or_create_folder(self, name: str, parent_id: str) -> str:
        for fid, f in self._folders.items():
            if f["name"] == name and f["parent"] == parent_id:
                return fid
        fid = self._new_id("folder")
        self._folders[fid] = {"name": name, "parent": parent_id}
        return fid

    def find_file(self, name: str, parent_id: str) -> str | None:
        """Matches files OR folders by name+parent (mirrors real Drive's
        find_file, which doesn't filter by mimeType)."""
        for fid, f in self._files.items():
            if f["name"] == name and f["parent"] == parent_id:
                return fid
        for fid, f in self._folders.items():
            if f["name"] == name and f["parent"] == parent_id:
                return fid
        return None

    def upload_text(self, name: str, content: str, folder_id: str) -> str:
        existing = self.find_file(name, folder_id)
        if existing and existing in self._files:
            self._files[existing]["content"] = content
            return existing
        fid = self._new_id("file")
        self._files[fid] = {"name": name, "parent": folder_id, "content": content}
        return fid

    def download_text(self, file_id: str) -> str:
        return self._files[file_id]["content"]

    def download_text_by_name(self, name: str, folder_id: str) -> str | None:
        fid = self.find_file(name, folder_id)
        if not fid or fid not in self._files:
            return None
        return self._files[fid]["content"]

    def list_subfolders(self, folder_id: str) -> list[dict]:
        return [
            {"id": fid, "name": f["name"]}
            for fid, f in self._folders.items()
            if f["parent"] == folder_id
        ]

    def read_files_in_folders(self, folder_ids: list[str], filename: str) -> dict[str, str]:
        results = {}
        for folder_id in folder_ids:
            fid = self.find_file(filename, folder_id)
            if fid and fid in self._files:
                results[folder_id] = self._files[fid]["content"]
        return results

    def delete_file(self, file_id: str) -> None:
        children = [
            fid
            for fid, f in {**self._folders, **self._files}.items()
            if f.get("parent") == file_id
        ]
        for fid in children:
            self.delete_file(fid)
        self._folders.pop(file_id, None)
        self._files.pop(file_id, None)

    def move_item(self, item_id: str, new_parent_id: str, old_parent_id: str) -> None:
        """Mirrors DriveStorage.move_item — relocates a file or folder to a
        new parent. old_parent_id is accepted for interface parity but unused
        here (this fake models single-parent items, unlike real Drive)."""
        if item_id in self._folders:
            self._folders[item_id]["parent"] = new_parent_id
        elif item_id in self._files:
            self._files[item_id]["parent"] = new_parent_id
