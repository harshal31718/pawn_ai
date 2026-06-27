import io
import uuid

import pdfplumber
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.core.drive_factory import get_drive_for_user
from app.storage import documents_drive
from app.storage.documents import store_doc

router = APIRouter()


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
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages).strip()
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
    drive = get_drive_for_user(user_id)
    if drive:
        documents_drive.store_doc(doc_id, text, drive)
    else:
        store_doc(doc_id, text, user_id=user_id)

    return {"doc_id": doc_id, "filename": filename, "char_count": len(text)}
