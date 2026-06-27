"""Google Drive storage layer.

DriveStorage wraps the Drive v3 API for PAWN's per-user file operations.
All paths are relative to a user's PAWN/ root folder in Drive.

Folder structure created on first use:
  PAWN/
    conversations/
      {conv_id}/
        meta.json
        messages.jsonl
        summary.md
    uploads/
      {doc_id}.txt
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Optional

from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


class DriveStorage:
    """Per-user Drive file operations for PAWN data."""

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
            except ValueError:
                pass

        self._creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            expiry=expiry,
        )
        self._service: Resource = self._build_service()
        self._root_id: Optional[str] = None
        self._folders: dict[str, str] = {}

    def _build_service(self) -> Resource:
        if self._creds.expired and self._creds.refresh_token:
            self._creds.refresh(GRequest())
            if self._on_token_refresh:
                self._on_token_refresh(
                    access_token=self._creds.token,
                    refresh_token=self._creds.refresh_token,
                    expires_at=self._creds.expiry.isoformat() if self._creds.expiry else None,
                )
        return build("drive", "v3", credentials=self._creds, cache_discovery=False)

    def _files(self):
        return self._service.files()

    def find_file(self, name: str, parent_id: str) -> Optional[str]:
        """Return file_id of the first file matching name in parent_id, or None."""
        q = (
            f"name = {repr(name)} and "
            f"'{parent_id}' in parents and "
            "trashed = false"
        )
        result = self._files().list(q=q, fields="files(id)", pageSize=1).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def get_or_create_folder(self, name: str, parent_id: str) -> str:
        """Return (or create) a subfolder named `name` inside `parent_id`."""
        cache_key = f"{parent_id}/{name}"
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
        return fid

    def get_or_create_root(self) -> str:
        """Return (or create) the PAWN/ root folder in the user's Drive."""
        if self._root_id:
            return self._root_id

        # Search in root
        q = "name = 'PAWN' and 'root' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        result = self._files().list(q=q, fields="files(id)", pageSize=1).execute()
        files = result.get("files", [])

        if files:
            self._root_id = files[0]["id"]
        else:
            meta = {"name": "PAWN", "mimeType": self._MIME_FOLDER}
            folder = self._files().create(body=meta, fields="id").execute()
            self._root_id = folder["id"]

        return self._root_id

    def upload_text(self, name: str, content: str, folder_id: str) -> str:
        """Create or update a text file in folder_id. Returns file_id."""
        existing = self.find_file(name, folder_id)
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=self._MIME_TEXT,
            resumable=False,
        )
        if existing:
            self._files().update(fileId=existing, media_body=media).execute()
            return existing
        else:
            meta = {"name": name, "parents": [folder_id]}
            f = self._files().create(body=meta, media_body=media, fields="id").execute()
            return f["id"]

    def download_text(self, file_id: str) -> str:
        """Download a text file and return its content as a string."""
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

    def list_folder(self, folder_id: str) -> list[dict]:
        """List files (id, name) in folder_id, excluding trashed items."""
        q = f"'{folder_id}' in parents and trashed = false and mimeType != '{self._MIME_FOLDER}'"
        result = self._files().list(q=q, fields="files(id,name)", pageSize=100).execute()
        return result.get("files", [])

    def list_subfolders(self, folder_id: str) -> list[dict]:
        """List subfolders (id, name) in folder_id."""
        q = f"'{folder_id}' in parents and mimeType = '{self._MIME_FOLDER}' and trashed = false"
        result = self._files().list(q=q, fields="files(id,name)", pageSize=1000).execute()
        return result.get("files", [])

    def delete_file(self, file_id: str) -> None:
        """Permanently trash a file or folder."""
        try:
            self._files().delete(fileId=file_id).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise

    def delete_folder_by_name(self, name: str, parent_id: str) -> None:
        """Find and delete a subfolder by name inside parent_id."""
        fid = self.find_file(name, parent_id)
        if fid:
            self.delete_file(fid)
