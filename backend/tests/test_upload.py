import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations_drive, documents_drive
from tests.fake_drive import FakeDriveStorage

# Must match conftest.TEST_USER_ID
TEST_USER_ID = "test-user-id"


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


def test_upload_text_file(client, fake_drive):
    """Uploading a valid text file should successfully extract text and store it."""
    file_content = b"This is some sample document text.\nLine 2 content."
    response = client.post(
        "/upload",
        files={"file": ("test.txt", file_content, "text/plain")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "doc_id" in data
    assert data["filename"] == "test.txt"
    assert data["char_count"] == len(file_content.decode("utf-8").strip())

    stored_text = documents_drive.load_doc(data["doc_id"], fake_drive)
    assert stored_text == "This is some sample document text.\nLine 2 content."


def test_upload_pdf_file(client, fake_drive):
    """Uploading a PDF should call pdfplumber and store the extracted text."""
    pdf_text = "This text comes from a PDF page."
    mock_page = MagicMock()
    mock_page.extract_text.return_value = pdf_text
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch("pdfplumber.open", return_value=mock_pdf):
        response = client.post(
            "/upload",
            files={"file": ("document.pdf", b"dummy pdf content", "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "doc_id" in data
        assert data["filename"] == "document.pdf"
        stored = documents_drive.load_doc(data["doc_id"], fake_drive)
        assert stored == pdf_text


def test_upload_unsupported_file_type(client):
    response = client.post(
        "/upload",
        files={"file": ("image.png", b"fake png data", "image/png")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_empty_file(client):
    response = client.post(
        "/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
    assert "contains no readable text" in response.json()["detail"]


def test_upload_requires_drive_when_unavailable():
    """No local fallback anymore — if Drive isn't linked, the request must
    fail clearly (412 not_configured) instead of silently degrading."""
    with patch("app.core.drive_factory.get_drive_for_user", return_value=None):
        with TestClient(app) as c:
            resp = c.post(
                "/upload",
                files={"file": ("test.txt", b"some text", "text/plain")},
            )
    assert resp.status_code == 412
    assert resp.json()["code"] == "not_configured"


def test_chat_no_longer_injects_document_as_system_message(client, fake_drive):
    """Phase A / A.4: doc_id no longer triggers whole-doc injection — content
    reaches the model only via the doc_search tool. A doc_id that doesn't
    even exist must NOT 404 (the field is now inert in /chat)."""
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
                "doc_id": "nonexistent-doc-id",
            },
        ) as resp:
            assert resp.status_code == 200
            resp.read()

    assert not any(m["role"] == "system" and "uploaded document" in m.get("content", "") for m in captured_messages)


def test_upload_with_conversation_id_lazy_creates_and_schedules_indexing(client, fake_drive):
    """Draft-chat edge (locked rule): uploading with a conversation_id that
    doesn't exist yet on Drive must lazy-create it, exactly as /chat does,
    so the doc always ends up with a scope."""
    conv_id = "draft-conv-1"
    assert conversations_drive.get_conversation_meta(fake_drive, conv_id) is None

    with patch("app.routes.upload.index_document_task") as mock_index_task:
        response = client.post(
            "/upload",
            files={"file": ("test.txt", b"some doc content", "text/plain")},
            data={"conversation_id": conv_id},
        )
    assert response.status_code == 200
    assert conversations_drive.get_conversation_meta(fake_drive, conv_id) is not None
    # Scheduled (and, under TestClient, run) via BackgroundTasks with the right args.
    mock_index_task.assert_called_once()
    call_args = mock_index_task.call_args[0]
    assert call_args[0] == TEST_USER_ID
    assert call_args[1] == conv_id
    assert call_args[4] == "some doc content"


def test_upload_without_conversation_id_does_not_index(client):
    """No conversation_id (e.g. a doc dropped before any chat exists) — the
    doc is stored but not scoped/indexed anywhere."""
    with patch("app.routes.upload.index_document_task") as mock_index_task:
        response = client.post(
            "/upload",
            files={"file": ("test.txt", b"some doc content", "text/plain")},
        )
    assert response.status_code == 200
    mock_index_task.assert_not_called()
