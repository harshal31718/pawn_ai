"""Tests for memory/chunker.py's turn-splitting logic (Phase M, M.3)."""

from app.memory.chunker import chunk_turn
from app.constants import MEMORY_CHUNK_TOKENS, MEMORY_CHUNK_OVERLAP_TOKENS

_CHUNK_CHARS = MEMORY_CHUNK_TOKENS * 4
_OVERLAP_CHARS = MEMORY_CHUNK_OVERLAP_TOKENS * 4


def test_chunk_turn_short_message_yields_one_chunk():
    turn = [{"role": "user", "content": "hello there"}]
    chunks = chunk_turn(turn, msg_index_start=5)

    assert len(chunks) == 1
    assert chunks[0]["text"] == "hello there"
    assert chunks[0]["msg_index"] == 5
    assert "chunk_id" in chunks[0]
    assert "created_at" in chunks[0]
    assert "conv_id" not in chunks[0]  # caller stamps this in, not the chunker


def test_chunk_turn_assigns_msg_index_per_message_offset():
    turn = [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "second message"},
    ]
    chunks = chunk_turn(turn, msg_index_start=10)

    assert [c["msg_index"] for c in chunks] == [10, 11]


def test_chunk_turn_skips_empty_or_whitespace_messages():
    turn = [
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "real content"},
    ]
    chunks = chunk_turn(turn, msg_index_start=0)

    assert len(chunks) == 1
    assert chunks[0]["text"] == "real content"
    assert chunks[0]["msg_index"] == 2


def test_chunk_turn_splits_long_message_with_overlap():
    long_text = "".join(f"word{i:04d} " for i in range(2000))  # far exceeds one chunk
    turn = [{"role": "user", "content": long_text}]
    chunks = chunk_turn(turn, msg_index_start=0)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c["text"]) <= _CHUNK_CHARS
        assert c["msg_index"] == 0

    # Overlap: the tail of one chunk should reappear at the head of the next.
    stride = _CHUNK_CHARS - _OVERLAP_CHARS
    first_chunk_tail = chunks[0]["text"][stride:]
    assert chunks[1]["text"].startswith(first_chunk_tail)


def test_chunk_turn_empty_list_yields_no_chunks():
    assert chunk_turn([], msg_index_start=0) == []
