"""Google Drive-backed document storage.

Uploaded documents are stored in the user's Drive under:
  PAWN/uploads/{doc_id}.txt

Replaces the in-memory _documents dict from documents.py.
"""

from typing import Optional

from app.storage.drive import DriveStorage


def _uploads_folder(drive: DriveStorage) -> str:
    root = drive.get_or_create_root()
    return drive.get_or_create_folder("uploads", root)


def store_doc(doc_id: str, text: str, drive: DriveStorage) -> None:
    folder_id = _uploads_folder(drive)
    drive.upload_text(f"{doc_id}.txt", text, folder_id)


def load_doc(doc_id: str, drive: DriveStorage) -> Optional[str]:
    folder_id = _uploads_folder(drive)
    return drive.download_text_by_name(f"{doc_id}.txt", folder_id)
