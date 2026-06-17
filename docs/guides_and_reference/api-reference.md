# PAWN — API Reference

This document serves as the complete REST API reference for the PAWN backend server.

---

## 1. System Endpoints

### Health Check
* **Endpoint:** `GET /health`
* **Description:** Verifies that the FastAPI server is running and returns basic security validation.
* **Response:** `200 OK`
  ```json
  {
    "status": "ok"
  }
  ```

---

## 2. Model Registry Endpoints

### List User-Facing Models
* **Endpoint:** `GET /registry/models`
* **Description:** Returns the complete user-facing model catalogue along with the count of active providers for each model.
* **Response:** `200 OK`
  ```json
  [
    {
      "model_id": "gemini-2.5-flash",
      "display_name": "Gemini 2.5 Flash",
      "capability_level": "balanced",
      "capability_tags": ["general", "summarization", "instruction-following", "coding"],
      "context_window": 1048576,
      "endpoint_count": 1
    },
    {
      "model_id": "llama-3.3-70b",
      "display_name": "Llama 3.3 70B",
      "capability_level": "balanced",
      "capability_tags": ["coding", "reasoning", "general"],
      "context_window": 128000,
      "endpoint_count": 5
    }
  ]
  ```

---

## 3. Document Management Endpoints

### Upload Document
* **Endpoint:** `POST /upload`
* **Description:** Uploads a text (`.txt`) or PDF (`.pdf`) file, extracts the layout-preserved content using `pdfplumber`, and saves it in-memory.
* **Payload:** `multipart/form-data`
  * `file`: Binary file upload
* **Response:** `200 OK`
  ```json
  {
    "doc_id": "4a7b0559-6725-4cde-a178-5db0d603a11e",
    "filename": "sample_document.pdf",
    "char_count": 4580
  }
  ```

---

## 4. Chat & Streaming Endpoints

### Streaming Agent Chat
* **Endpoint:** `POST /chat`
* **Description:** Posts user messages and returns a chunked `text/event-stream` using the LangGraph agent state graph. Integrates context memory retrieval, document context embedding, rate limiting failover routing, and custom event tracing.
* **Payload:** `application/json`
  ```json
  {
    "messages": [
      {
        "role": "user",
        "content": "What was the summary of my last topic?"
      }
    ],
    "model_id": "gemini-2.5-flash",
    "doc_id": "4a7b0559-6725-4cde-a178-5db0d603a11e",
    "conversation_id": "7bf3ad20-7212-4ebf-801b-90fba4bf94a1"
  }
  ```
* **Response:** `200 OK` (`text/event-stream` chunked response)

### SSE Event Format Protocol
All events emitted are formatted as JSON lines prefixed by `data: `:

* **Token Content:**
  `data: {"type": "token", "delta": "word"}`
* **Agent Execution Step:**
  `data: {"type": "step", "label": "Planning", "detail": "Resolving user intent..."}`
* **Memory Hit (RAG retrieval):**
  `data: {"type": "memory_hit", "summary": "User prefers concise Python code."}`
* **Sub-agent/Model Call:**
  `data: {"type": "model_call", "model": "gemini-2.5-flash", "purpose": "planning"}`
* **Failover Provider Switch:**
  `data: {"type": "provider_switch", "from": "groq", "to": "cerebras"}`
* **Stream Error:**
  `data: {"type": "error", "message": "All endpoints exhausted or rate-limited"}`
* **Stream Done:**
  `data: {"type": "done", "via_provider": "cerebras"}`

---

## 5. Conversations CRUD Endpoints

### List Conversations
* **Endpoint:** `GET /conversations`
* **Description:** Lists metadata logs of all persisted chats sorted descending by modification timestamp.
* **Response:** `200 OK`
  ```json
  [
    {
      "id": "7bf3ad20-7212-4ebf-801b-90fba4bf94a1",
      "title": "Python Async Code",
      "created_at": "2026-06-17T12:30:15.112Z",
      "updated_at": "2026-06-17T12:35:10.450Z",
      "model_id": "llama-3.3-70b",
      "message_count": 4
    }
  ]
  ```

### Create Conversation
* **Endpoint:** `POST /conversations`
* **Description:** Seeds folder workspace directories under `/data/conversations/<uuid>` and initializes thread metadata.
* **Payload:** `application/json`
  ```json
  {
    "title": "New Conversation",
    "model_id": "gemini-2.5-flash"
  }
  ```
* **Response:** `200 OK` (returns created conversation meta payload)

### Fetch Conversation Detail
* **Endpoint:** `GET /conversations/{conv_id}`
* **Description:** Loads stored logs (`meta.json` and `messages.jsonl`) for a specific chat ID.
* **Response:** `200 OK`
  ```json
  {
    "meta": {
      "id": "7bf3ad20-7212-4ebf-801b-90fba4bf94a1",
      "title": "Python Async Code",
      "created_at": "...",
      "updated_at": "...",
      "model_id": "llama-3.3-70b",
      "message_count": 2
    },
    "messages": [
      {
        "role": "user",
        "content": "Let's discuss python asyncio."
      },
      {
        "role": "assistant",
        "content": "Asyncio is a library to write concurrent code..."
      }
    ]
  }
  ```

### Rename Conversation
* **Endpoint:** `PATCH /conversations/{conv_id}`
* **Description:** Updates the title of the conversation in `meta.json`.
* **Payload:** `application/json`
  ```json
  {
    "title": "Renamed Thread Topic"
  }
  ```
* **Response:** `200 OK` (returns updated metadata logs)

### Delete Conversation
* **Endpoint:** `DELETE /conversations/{conv_id}`
* **Description:** Deletes the directory containing metadata, summaries, and chat history.
* **Response:** `200 OK`
  ```json
  {
    "status": "ok"
  }
  ```

