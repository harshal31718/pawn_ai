import io
import sys
import uuid

import pdfplumber
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user
from app.exceptions import NotConfiguredError
from app.memory.indexer import index_document_task, resolve_scope
from app.storage import conversations_drive, documents_drive

router = APIRouter()


def _extract_pdf_text(file_bytes: bytes) -> str:
    """CPU-bound PDF text extraction — run off the event loop."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages).strip()


def _store(drive, doc_id, text, user_id):
    documents_drive.store_doc(doc_id, text, drive)


def _ensure_conversation(drive, conv_id: str, user_id: str | None):
    """Blocking: lazy-create the conversation if it doesn't exist yet — the
    exact same pattern chat.py's `/chat` uses for a client-owned draft
    conversation id, so uploading from a draft chat (no server-side
    conversation yet) always ends up with a scope to index into, per the
    plan's locked draft-chat rule (a doc upload therefore always has a
    scope; no unscoped document rows can exist)."""
    meta = conversations_drive.get_conversation_meta(drive, conv_id)
    if not meta:
        conversations_drive.create_conversation(
            drive, user_id=user_id, conv_id=conv_id, title="New Chat", model_id="gemini-2.5-flash"
        )


@router.post("/upload")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: str | None = Form(None),
):
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
        print(f"Failed to read upload file {filename!r}: {exc}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read upload file.",
        )

    text = ""
    if is_pdf:
        try:
            text = await run_in_threadpool(_extract_pdf_text, file_bytes)
        except Exception as exc:
            print(f"Failed to parse PDF document {filename!r}: {exc}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to parse PDF document.",
            )
    else:
        try:
            text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("latin-1").strip()
            except Exception as exc:
                print(f"Failed to decode text file {filename!r}: {exc}", file=sys.stderr)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to decode text file.",
                )

    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file contains no readable text.",
        )

    doc_id = str(uuid.uuid4())
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    await run_in_threadpool(call_drive, _store, drive, doc_id, text, user_id)

    # Chunk + index into the uploading chat's scope (Phase A / A.4) — content
    # reaches the model only via the doc_search tool, never whole-doc-injected.
    # No conversation_id means no chat to scope into (e.g. a doc dropped
    # before any chat exists at all); the doc is stored but not indexed.
    if conversation_id:
        await run_in_threadpool(call_drive, _ensure_conversation, drive, conversation_id, user_id)
        try:
            scope = await run_in_threadpool(resolve_scope, user_id, conversation_id, drive)
        except NotConfiguredError:
            scope = None
        background_tasks.add_task(
            index_document_task, user_id, conversation_id, scope, doc_id, text, filename,
        )

    return {"doc_id": doc_id, "filename": filename, "char_count": len(text)}
