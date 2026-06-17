import io
import uuid
import pdfplumber
from fastapi import APIRouter, File, UploadFile, HTTPException, status
from app.storage.documents import store_doc

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    filename = file.filename or ""
    content_type = file.content_type or ""
    
    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf"
    is_txt = filename.lower().endswith(".txt") or content_type.startswith("text/")

    if not (is_pdf or is_txt):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Only PDF and TXT files are allowed."
        )
        
    try:
        file_bytes = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read upload file: {str(e)}"
        )
        
    text = ""
    if is_pdf:
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        pages_text.append(extracted)
                text = "\n".join(pages_text).strip()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse PDF document: {str(e)}"
            )
    else:
        # It's a text file
        try:
            text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            try:
                # Try latin-1 if utf-8 fails
                text = file_bytes.decode("latin-1").strip()
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to decode text file: {str(e)}"
                )

    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file contains no readable text."
        )

    doc_id = str(uuid.uuid4())
    store_doc(doc_id, text)

    return {
        "doc_id": doc_id,
        "filename": filename,
        "char_count": len(text)
    }
