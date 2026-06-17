import pytest
from unittest.mock import AsyncMock, patch

from app.agent.parser import parse_action
from app.agent.routing import resolve_level
from app.agent.graph import (
    load_context_node,
    agent_node,
    search_memory_node,
    ask_model_node,
    final_node,
    route_action,
    build_agent_graph
)

def test_parser_valid_json():
    # standard json
    res1 = parse_action('{"action": "search_memory", "query": "hello"}')
    assert res1 == {"action": "search_memory", "query": "hello"}
    
    # prose wrapped json
    res2 = parse_action('Thought: I should search memory.\n{"action": "search_memory", "query": "hello"}\nDone.')
    assert res2 == {"action": "search_memory", "query": "hello"}
    
    # markdown wrapped json
    res3 = parse_action('```json\n{"action": "final", "answer": "complete"}\n```')
    assert res3 == {"action": "final", "answer": "complete"}

def test_parser_fallback():
    # no json
    res = parse_action('I cannot find any action. The answer is 42.')
    assert res == {"action": "final", "answer": "I cannot find any action. The answer is 42."}
    
    # malformed json
    res2 = parse_action('{"action": "search_memory", ')
    assert res2 == {"action": "final", "answer": '{"action": "search_memory",'}

def test_routing():
    p, m = resolve_level("fast")
    assert p == "gemini"
    
    p2, m2 = resolve_level("balanced", purpose="draft")
    assert p2 in ["groq", "cerebras", "gemini"]

@pytest.mark.asyncio
@patch("app.memory.retrieve.retrieve", new_callable=AsyncMock)
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_load_context_node(mock_dispatch, mock_retrieve):
    mock_retrieve.return_value = [{"text": "memory content"}]
    state = {
        "conversation_id": "c1",
        "history": [{"role": "user", "content": "user query"}],
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": None,
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 0
    }
    
    res = await load_context_node(state)
    assert res["retrieved_memory"] == ["memory content"]
    mock_retrieve.assert_called_once_with("user query", active_conv_id="c1", top_k=3)
    mock_dispatch.assert_called_once_with("memory_hit", {"summary": "memory content"})

@pytest.mark.asyncio
@patch("app.core.normalize.chat_stream")
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_agent_node(mock_dispatch, mock_chat_stream):
    async def mock_stream(*args, **kwargs):
        yield '{"action": "search_memory", "query": "more context"}'
        
    mock_chat_stream.side_effect = mock_stream
    
    state = {
        "conversation_id": "c1",
        "history": [{"role": "user", "content": "user query"}],
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": None,
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 0
    }
    
    res = await agent_node(state)
    assert res["next_action"] == {"action": "search_memory", "query": "more context"}
    assert res["step_count"] == 1
    mock_dispatch.assert_called_once_with("step", {"label": "Thinking", "detail": "step 1"})

@pytest.mark.asyncio
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_agent_node_hard_cap(mock_dispatch):
    state = {
        "conversation_id": "c1",
        "history": [{"role": "user", "content": "user query"}],
        "retrieved_memory": [],
        "scratchpad": [{"action": "ask_model", "result": "prior draft"}],
        "next_action": None,
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 8
    }
    
    res = await agent_node(state)
    assert res["next_action"] == {"action": "final", "answer": "prior draft"}

@pytest.mark.asyncio
@patch("app.memory.retrieve.retrieve", new_callable=AsyncMock)
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_search_memory_node(mock_dispatch, mock_retrieve):
    mock_retrieve.return_value = [{"text": "found fact"}]
    state = {
        "conversation_id": "c1",
        "history": [],
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": {"action": "search_memory", "query": "lookup"},
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 1
    }
    
    res = await search_memory_node(state)
    assert len(res["scratchpad"]) == 1
    assert res["scratchpad"][0]["action"] == "search_memory"
    assert res["scratchpad"][0]["result"] == "found fact"
    assert res["next_action"] is None

@pytest.mark.asyncio
@patch("app.core.normalize.chat_stream")
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_ask_model_node(mock_dispatch, mock_chat_stream):
    async def mock_stream(*args, **kwargs):
        yield "draft response"
        
    mock_chat_stream.side_effect = mock_stream
    state = {
        "conversation_id": "c1",
        "history": [],
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": {"action": "ask_model", "purpose": "draft", "prompt": "draft it"},
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 1
    }
    
    res = await ask_model_node(state)
    assert len(res["scratchpad"]) == 1
    assert res["scratchpad"][0]["action"] == "ask_model"
    assert res["scratchpad"][0]["result"] == "draft response"
    assert res["next_action"] is None

@pytest.mark.asyncio
@patch("app.core.normalize.chat_stream")
@patch("app.agent.graph.adispatch_custom_event", new_callable=AsyncMock)
async def test_final_node(mock_dispatch, mock_chat_stream):
    async def mock_stream(*args, **kwargs):
        yield "synthesized"
        yield " answer"
        
    mock_chat_stream.side_effect = mock_stream
    state = {
        "conversation_id": "c1",
        "history": [{"role": "user", "content": "hello"}],
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": {"action": "final", "answer": ""},
        "final_answer": None,
        "user_model_id": "gemini",
        "step_count": 1
    }
    
    res = await final_node(state)
    assert res["final_answer"] == "synthesized answer"
    assert mock_dispatch.call_count == 3  # step + 2 tokens

def test_route_action():
    assert route_action({"next_action": {"action": "search_memory"}}) == "search_memory"
    assert route_action({"next_action": {"action": "ask_model"}}) == "ask_model"
    assert route_action({"next_action": {"action": "final"}}) == "final"
    assert route_action({"next_action": {"action": "unknown"}}) == "agent"
