import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.storage.documents import store_doc, clear_docs, load_doc

@pytest.fixture()
def client():
    # Clear in-memory docs before/after tests
    clear_docs()
    with TestClient(app) as c:
        yield c
    clear_docs()


def test_upload_text_file(client):
    """Uploading a valid text file should successfully extract text and store it."""
    file_content = b"This is some sample document text.\nLine 2 content."
    response = client.post(
        "/upload",
        files={"file": ("test.txt", file_content, "text/plain")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "doc_id" in data
    assert data["filename"] == "test.txt"
    assert data["char_count"] == len(file_content.decode("utf-8").strip())
    
    # Check that text is stored in-memory
    stored_text = load_doc(data["doc_id"])
    assert stored_text == "This is some sample document text.\nLine 2 content."


def test_upload_pdf_file(client):
    """Uploading a PDF should call pdfplumber and store the extracted text."""
    pdf_text = "This text comes from a PDF page."
    
    # Mock pdfplumber context manager and page extraction
    mock_page = MagicMock()
    mock_page.extract_text.return_value = pdf_text
    
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf
    
    with patch("pdfplumber.open", return_value=mock_pdf) as mock_open:
        response = client.post(
            "/upload",
            files={"file": ("document.pdf", b"dummy pdf content", "application/pdf")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "doc_id" in data
        assert data["filename"] == "document.pdf"
        
        # Verify pdfplumber was called
        mock_open.assert_called_once()
        
        # Verify text was stored
        stored = load_doc(data["doc_id"])
        assert stored == pdf_text


def test_upload_unsupported_file_type(client):
    """Uploading an unsupported file type should return 400 Bad Request."""
    response = client.post(
        "/upload",
        files={"file": ("image.png", b"fake png data", "image/png")}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_empty_file(client):
    """Uploading an empty file should return 400 Bad Request."""
    response = client.post(
        "/upload",
        files={"file": ("empty.txt", b"", "text/plain")}
    )
    assert response.status_code == 400
    assert "contains no readable text" in response.json()["detail"]


def test_chat_injects_document_as_system_message(client):
    """If a valid doc_id is sent to /chat, the document text must be prepended as a system message."""
    doc_id = "test-doc-123"
    doc_text = "Secrets of the universe are here."
    store_doc(doc_id, doc_text)
    
    captured_messages = []
    
    async def capturing_stream(url, model, messages, headers):
        captured_messages.extend(messages)
        yield "response token"
        
    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "summarize the doc"}],
                "doc_id": doc_id
            }
        ) as resp:
            assert resp.status_code == 200
            resp.read()
            
    # 1 planning prompt + 1 document context + 1 user prompt + 1 synthesis prompt = 4 messages
    assert len(captured_messages) == 4
    assert captured_messages[1]["role"] == "system"
    assert doc_text in captured_messages[1]["content"]
    assert captured_messages[2]["role"] == "user"
    assert captured_messages[2]["content"] == "summarize the doc"


def test_chat_with_invalid_doc_id_returns_404(client):
    """If an invalid doc_id is sent to /chat, the request should return 404."""
    response = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "doc_id": "nonexistent-doc-id"
        }
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
