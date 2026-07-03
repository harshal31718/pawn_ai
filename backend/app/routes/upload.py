import io
import uuid

import pdfplumber
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user
from app.storage import documents_drive

router = APIRouter()


def _extract_pdf_text(file_bytes: bytes) -> str:
    """CPU-bound PDF text extraction — run off the event loop."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages).strip()


def _store(drive, doc_id, text, user_id):
    documents_drive.store_doc(doc_id, text, drive)


@router.post("/upload")
async def upload_document(request: Request, file: UploadFile = File(...)):
    user_id = request.state.user_id
    filename = file.filename or ""
    content_type = file.content_type or ""

    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf"
    is_txt = filename.lower().endswith(".txt") or content_type.startswith("text/")

    if not (is_pdf or is_txt):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Only PDF and TXT files are allowed.",
        )

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read upload file: {exc}",
        )

    text = ""
    if is_pdf:
        try:
            text = await run_in_threadpool(_extract_pdf_text, file_bytes)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse PDF document: {exc}",
            )
    else:
        try:
            text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("latin-1").strip()
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to decode text file: {exc}",
                )

    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file contains no readable text.",
        )

    doc_id = str(uuid.uuid4())
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    await run_in_threadpool(call_drive, _store, drive, doc_id, text, user_id)

    return {"doc_id": doc_id, "filename": filename, "char_count": len(text)}
