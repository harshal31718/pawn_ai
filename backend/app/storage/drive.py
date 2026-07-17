"""Google Drive storage layer.

DriveStorage wraps the Drive v3 API for PAWN's per-user file operations.
All paths are relative to a user's PAWN/ root folder in Drive.

Folder structure created on first use (Phase M — memory scoping):
  PAWN/
    conversations/
      chats/
        {conv_id}/
          meta.json
          messages.jsonl
          summary.md
          rag_chunks.jsonl
      projects/
        {project_id}/
          project.json
          {conv_id}/            # same shape as a standalone chat
    uploads/
      {doc_id}.txt

Folder placement alone determines a chat's scope (chats/ = standalone,
projects/{pid}/ = that project) — see storage/conversations_drive.py and
storage/projects_drive.py, and workspace/plan/plan_memory_scoping.md §3.
"""

from __future__ import annotations

import io
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import httplib2
from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# Hard socket timeout (seconds) for every Drive HTTP round-trip. Without this,
# a stalled connection hangs the calling thread indefinitely ("no replies").
_DRIVE_TIMEOUT = 20

# Fan-out width for read_files_in_folders. Each of list_conversations/
# list_projects/list_project_chats used to walk N chat/project folders one at
# a time (find_file + download_text per folder, ~2 blocking Drive round-trips
# each) -- with 30 real chats that alone took ~49s and tripped the app's 45s
# request-timeout middleware on every GET /conversations. Fanning the same
# calls out across a small thread pool cuts wall-clock to roughly one
# round-trip's worth regardless of folder count.
_META_FETCH_WORKERS = 8


class DriveStorage:
    """Per-user Drive file operations for PAWN data.

    A single instance is cached and reused across requests (see drive_factory),
    so it keeps an in-memory folder/file-ID cache to avoid re-resolving paths by
    name on every call. Reads go by file ID (strongly consistent) once an ID is
    known, which sidesteps Drive's eventually-consistent name queries.

    googleapiclient's underlying http transport is NOT thread-safe, and the cached
    instance may be hit from multiple threadpool workers, so all API access is
    guarded by a re-entrant lock.
    """

    _MIME_FOLDER = "application/vnd.google-apps.folder"
    _MIME_TEXT = "text/plain"

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: Optional[str],
        user_id: str,
        on_token_refresh=None,
    ):
        self._user_id = user_id
        self._on_token_refresh = on_token_refresh

        expiry = None
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at)
                # Postgres returns timestamptz (tz-aware) — re-stringified to ISO by
                # drive_factory before reaching here — but google-auth compares
                # expiry against a naive UTC now() — convert to naive UTC to avoid
                # "can't compare offset-naive and offset-aware datetimes".
                if expiry.tzinfo is not None:
                    expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                pass

        # client_id/client_secret are REQUIRED for google-auth to refresh an
        # expired access token — without them the refresh raises RefreshError
        # ("credentials do not contain the necessary fields") and every Drive
        # call fails once the initial token expires (~1h after linking).
        self._creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            expiry=expiry,
        )
        self._lock = threading.RLock()
        self._service: Resource = self._build_service()
        self._root_id: Optional[str] = None
        self._folders: dict[str, str] = {}
        # Cache of resolved file IDs keyed by "{parent_id}/{name}". Reading by ID
        # via get_media is strongly consistent, unlike name-based list queries.
        self._file_ids: dict[str, str] = {}

    def _build_service(self) -> Resource:
        if self._creds.expired and self._creds.refresh_token:
            self._creds.refresh(GRequest())
            if self._on_token_refresh:
                self._on_token_refresh(
                    access_token=self._creds.token,
                    refresh_token=self._creds.refresh_token,
                    expires_at=self._creds.expiry.isoformat() if self._creds.expiry else None,
                )
        # Build with an explicit http transport so we can set a socket timeout.
        # AuthorizedHttp also injects/refreshes the OAuth credentials per request.
        authed_http = AuthorizedHttp(self._creds, http=httplib2.Http(timeout=_DRIVE_TIMEOUT))
        return build("drive", "v3", http=authed_http, cache_discovery=False)

    def _files(self):
        return self._service.files()

    def find_file(self, name: str, parent_id: str) -> Optional[str]:
        """Return file_id of the first file matching name in parent_id, or None.

        Positive results are cached so later reads can use the (strongly
        consistent) get_media-by-ID path instead of repeating the
        eventually-consistent name query.
        """
        cache_key = f"{parent_id}/{name}"
        with self._lock:
            cached = self._file_ids.get(cache_key)
            if cached:
                return cached
            q = (
                f"name = {repr(name)} and "
                f"'{parent_id}' in parents and "
                "trashed = false"
            )
            result = self._files().list(q=q, fields="files(id)", pageSize=1).execute()
            files = result.get("files", [])
            fid = files[0]["id"] if files else None
            if fid:
                self._file_ids[cache_key] = fid
            return fid

    def get_or_create_folder(self, name: str, parent_id: str) -> str:
        """Return (or create) a subfolder named `name` inside `parent_id`."""
        cache_key = f"{parent_id}/{name}"
        with self._lock:
            if cache_key in self._folders:
                return self._folders[cache_key]

            existing = self.find_file(name, parent_id)
            if existing:
                self._folders[cache_key] = existing
                return existing

            meta = {
                "name": name,
                "mimeType": self._MIME_FOLDER,
                "parents": [parent_id],
            }
            folder = self._files().create(body=meta, fields="id").execute()
            fid = folder["id"]
            self._folders[cache_key] = fid
            # Cache as a file ID too so find_file(name, parent_id) hits without
            # a name query right after creation (eventual-consistency safe).
            self._file_ids[cache_key] = fid
            return fid

    # How many candidate "PAWN" root folders to fetch when resolving the root.
    # 1 would suffice for the happy path; fetching a few more lets us both
    # pick deterministically (oldest first) and detect+log a pre-existing
    # duplicate-root condition (see the concurrent-cache-miss race fixed in
    # drive_factory, commit 2146b07) instead of silently ignoring it.
    _ROOT_LOOKUP_PAGE_SIZE = 10

    def get_or_create_root(self) -> str:
        """Return (or create) the PAWN/ root folder in the user's Drive.

        Deterministic root selection: orders by createdTime ascending and
        always picks the OLDEST matching folder. Without an explicit
        orderBy, Drive's files.list has no guaranteed, stable ordering --
        for a user with more than one "PAWN" root folder (a pre-existing,
        already-fixed-going-forward race could create one), two separate
        DriveStorage instances (e.g. across a cache eviction) could silently
        resolve to DIFFERENT roots and each see a different subset of that
        user's chats/projects. Oldest-first is deterministic (stable across
        every call, every instance) and favors the root more likely to hold
        the most existing content, minimizing that "missing content"
        symptom -- it does not merge or delete anything, so it's safe to
        apply automatically; an actual multi-root merge still needs manual
        review (see workspace/plan/plan_imagelab_session_issues.md's sibling
        doc, plan_open_issues_2026-07-14.md §2.2)."""
        with self._lock:
            if self._root_id:
                return self._root_id

            # Search in root
            q = "name = 'PAWN' and 'root' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            result = self._files().list(
                q=q, fields="files(id)", pageSize=self._ROOT_LOOKUP_PAGE_SIZE, orderBy="createdTime",
            ).execute()
            files = result.get("files", [])

            if files:
                if len(files) > 1:
                    ids = ", ".join(f["id"] for f in files)
                    print(
                        f"Drive: user {self._user_id} has {len(files)} duplicate 'PAWN' root "
                        f"folders ({ids}) -- using the oldest ({files[0]['id']}) deterministically. "
                        "Manual merge recommended (see plan_open_issues_2026-07-14.md §2.2).",
                        file=sys.stderr,
                    )
                self._root_id = files[0]["id"]
            else:
                meta = {"name": "PAWN", "mimeType": self._MIME_FOLDER}
                folder = self._files().create(body=meta, fields="id").execute()
                self._root_id = folder["id"]

            return self._root_id

    def upload_text(self, name: str, content: str, folder_id: str) -> str:
        """Create or update a text file in folder_id. Returns file_id."""
        cache_key = f"{folder_id}/{name}"
        with self._lock:
            existing = self._file_ids.get(cache_key) or self.find_file(name, folder_id)
            media = MediaIoBaseUpload(
                io.BytesIO(content.encode("utf-8")),
                mimetype=self._MIME_TEXT,
                resumable=False,
            )
            if existing:
                self._files().update(fileId=existing, media_body=media).execute()
                self._file_ids[cache_key] = existing
                return existing
            meta = {"name": name, "parents": [folder_id]}
            f = self._files().create(body=meta, media_body=media, fields="id").execute()
            fid = f["id"]
            self._file_ids[cache_key] = fid
            return fid

    def download_text(self, file_id: str) -> str:
        """Download a text file and return its content as a string."""
        with self._lock:
            request = self._files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue().decode("utf-8")

    def download_text_by_name(self, name: str, folder_id: str) -> Optional[str]:
        """Find a file by name in folder_id and download it, or return None."""
        fid = self.find_file(name, folder_id)
        if not fid:
            return None
        return self.download_text(fid)

    def read_files_in_folders(self, folder_ids: list[str], filename: str) -> dict[str, str]:
        """Fetch `filename`'s text content from each of the given folders,
        in parallel. Returns {folder_id: content} — folders where the file
        is missing or fails to read are simply absent from the result.

        Each worker builds its own short-lived AuthorizedHttp instead of
        going through self._service/self._lock: the shared httplib2 transport
        is not thread-safe (see the class docstring), and self._creds' token
        is already fresh by the time any caller reaches this (DriveStorage.
        __init__ always refreshes via _build_service before this can run), so
        concurrent reads sharing the same Credentials object is safe -- none
        of them trigger a refresh.
        """
        if not folder_ids:
            return {}

        def _one(folder_id: str) -> tuple[str, Optional[str]]:
            try:
                http = AuthorizedHttp(self._creds, http=httplib2.Http(timeout=_DRIVE_TIMEOUT))
                resource = build("drive", "v3", http=http, cache_discovery=False)
                q = (
                    f"name = {filename!r} and "
                    f"'{folder_id}' in parents and "
                    "trashed = false"
                )
                result = resource.files().list(q=q, fields="files(id)", pageSize=1).execute()
                files = result.get("files", [])
                if not files:
                    return folder_id, None
                request = resource.files().get_media(fileId=files[0]["id"])
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return folder_id, buf.getvalue().decode("utf-8")
            except Exception as exc:
                print(f"read_files_in_folders: folder {folder_id} failed: {exc}", file=sys.stderr)
                return folder_id, None

        with ThreadPoolExecutor(max_workers=min(_META_FETCH_WORKERS, len(folder_ids))) as pool:
            pairs = list(pool.map(_one, folder_ids))
        return {fid: content for fid, content in pairs if content is not None}

    def list_folder(self, folder_id: str) -> list[dict]:
        """List files (id, name) in folder_id, excluding trashed items."""
        with self._lock:
            q = f"'{folder_id}' in parents and trashed = false and mimeType != '{self._MIME_FOLDER}'"
            result = self._files().list(q=q, fields="files(id,name)", pageSize=100).execute()
            return result.get("files", [])

    def list_subfolders(self, folder_id: str) -> list[dict]:
        """List subfolders (id, name) in folder_id."""
        with self._lock:
            q = f"'{folder_id}' in parents and mimeType = '{self._MIME_FOLDER}' and trashed = false"
            result = self._files().list(q=q, fields="files(id,name)", pageSize=1000).execute()
            return result.get("files", [])

    def delete_file(self, file_id: str) -> None:
        """Permanently trash a file or folder."""
        with self._lock:
            try:
                self._files().delete(fileId=file_id).execute()
            except HttpError as e:
                if e.resp.status != 404:
                    raise
            # The cached path/ID maps may now reference deleted entries; drop them
            # all (cheap to rebuild) rather than track reverse keys.
            self._folders.clear()
            self._file_ids.clear()

    def delete_folder_by_name(self, name: str, parent_id: str) -> None:
        """Find and delete a subfolder by name inside parent_id."""
        fid = self.find_file(name, parent_id)
        if fid:
            self.delete_file(fid)

    def move_item(self, item_id: str, new_parent_id: str, old_parent_id: str) -> None:
        """Relocate a file or folder to a new parent (single Drive metadata
        call — used for chat moves standalone<->project and the one-time
        legacy-layout migration, Phase M). Drive items can have multiple
        parents, so both adding the new parent and removing the old one are
        required, not just adding."""
        with self._lock:
            self._files().update(
                fileId=item_id,
                addParents=new_parent_id,
                removeParents=old_parent_id,
                fields="id, parents",
            ).execute()
            # Cached path->ID maps may reference the old parent path; drop
            # them all (cheap to rebuild) rather than track reverse keys,
            # mirroring delete_file's cache invalidation.
            self._folders.clear()
            self._file_ids.clear()
