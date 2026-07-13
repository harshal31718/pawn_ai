"""Tests for the agent tool layer: ToolSpec/ToolContext, get_tools assembly,
run_tool's timeout/error wrapping, and the calculator's safe AST evaluator."""

import asyncio

import pytest

from app.agent.tools.base import ToolContext, ToolSpec
from app.agent.tools.calculator import CALCULATOR_TOOL, safe_eval_arithmetic
from app.agent.tools.execute import run_tool
from app.agent.tools.get_datetime import GET_DATETIME_TOOL
from app.agent.tools.registry import get_tools
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _ctx(scope_type=None, scope_id=None):
    resolver = Resolver(load_registry(), EndpointRateLimiter(), secrets={})
    return ToolContext(
        user_id="u1",
        scope_type=scope_type,
        scope_id=scope_id,
        resolver=resolver,
        rate_limiter=resolver._rate_limiter,
    )


# ── registry.get_tools ───────────────────────────────────────────────────────

def test_get_tools_always_includes_calculator_and_datetime():
    tools = get_tools(_ctx())
    names = {t.name for t in tools}
    assert "calculator" in names
    assert "get_datetime" in names


def test_get_tools_stateless_and_scoped_both_get_the_always_on_tools():
    """calculator/get_datetime don't depend on scope — present either way.
    (search_memory/doc_search scope-gating lands in A.4; web_search's own
    key-gating is covered separately in test_agent_tools_search.py.)"""
    stateless = {t.name for t in get_tools(_ctx(scope_type=None, scope_id=None))}
    scoped = {t.name for t in get_tools(_ctx(scope_type="chat", scope_id="c1"))}
    assert stateless == scoped
    assert {"calculator", "get_datetime"} <= stateless


# ── execute.run_tool ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_tool_returns_handler_result():
    async def handler(args, ctx):
        return "ok"

    spec = ToolSpec(name="t", description="d", parameters={}, handler=handler)
    result = await run_tool(spec, {}, _ctx())
    assert result == "ok"


@pytest.mark.asyncio
async def test_run_tool_wraps_timeout_as_tool_error():
    async def handler(args, ctx):
        await asyncio.sleep(999)

    spec = ToolSpec(name="slow_tool", description="d", parameters={}, handler=handler)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.agent.tools.execute.TOOL_TIMEOUT_SECONDS", 0.05)
        result = await run_tool(spec, {}, _ctx())
    assert result.startswith("TOOL_ERROR:")
    assert "slow_tool" in result
    assert "timed out" in result


@pytest.mark.asyncio
async def test_run_tool_wraps_exception_as_tool_error():
    async def handler(args, ctx):
        raise ValueError("boom")

    spec = ToolSpec(name="broken_tool", description="d", parameters={}, handler=handler)
    result = await run_tool(spec, {}, _ctx())
    assert result == "TOOL_ERROR: boom"


@pytest.mark.asyncio
async def test_run_tool_never_raises_into_caller():
    """The graph must never see a raw exception from a tool call."""
    async def handler(args, ctx):
        raise RuntimeError("should never propagate")

    spec = ToolSpec(name="t", description="d", parameters={}, handler=handler)
    # No pytest.raises — this call must complete normally.
    result = await run_tool(spec, {}, _ctx())
    assert "TOOL_ERROR" in result


# ── calculator ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 2", 4),
        ("2 + 2 * 3", 8),
        ("(2 + 2) * 3", 12),
        ("10 / 4", 2.5),
        ("10 // 4", 2),
        ("2 ** 8", 256),
        ("-5 + 3", -2),
        ("7 % 3", 1),
    ],
)
def test_safe_eval_arithmetic_computes_correctly(expression, expected):
    assert safe_eval_arithmetic(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd')",
        "[x for x in range(10)]",
        "os.getcwd()",
        "1; import os",
        "lambda: 1",
        "(1).__class__",
        "True",
    ],
)
def test_safe_eval_arithmetic_rejects_non_arithmetic(expression):
    with pytest.raises(ValueError):
        safe_eval_arithmetic(expression)


def test_safe_eval_arithmetic_rejects_division_by_zero_cleanly():
    with pytest.raises(ZeroDivisionError):
        safe_eval_arithmetic("1 / 0")


def test_safe_eval_arithmetic_rejects_oversized_exponent():
    """A huge ** exponent is a valid expression under the AST whitelist but a
    resource-exhaustion vector — must be rejected before it's ever computed."""
    with pytest.raises(ValueError):
        safe_eval_arithmetic("99999999999999 ** 99999999999999")


def test_safe_eval_arithmetic_allows_reasonable_exponent():
    assert safe_eval_arithmetic("2 ** 10") == 1024


def test_safe_eval_arithmetic_rejects_overlong_expression():
    with pytest.raises(ValueError):
        safe_eval_arithmetic("1+" * 500 + "1")


@pytest.mark.asyncio
async def test_calculator_tool_handler_returns_tool_error_for_bad_expression():
    result = await CALCULATOR_TOOL.handler({"expression": "__import__('os')"}, _ctx())
    assert result.startswith("TOOL_ERROR:")


@pytest.mark.asyncio
async def test_calculator_tool_handler_computes_via_run_tool():
    result = await run_tool(CALCULATOR_TOOL, {"expression": "3 * 4"}, _ctx())
    assert result == "12"


@pytest.mark.asyncio
async def test_calculator_never_uses_eval_source_check():
    """Static guard: the calculator module's source must not call the builtin
    eval()/exec() (as opposed to our own safe_eval_arithmetic/_eval_node names,
    which merely contain "eval" as a substring)."""
    import inspect
    import re

    from app.agent.tools import calculator as calc_module

    source = inspect.getsource(calc_module)
    assert re.search(r"\beval\(", source) is None
    assert re.search(r"\bexec\(", source) is None


# ── get_datetime ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_datetime_returns_iso_utc():
    result = await run_tool(GET_DATETIME_TOOL, {}, _ctx())
    assert "UTC" in result
    assert "+00:00" in result
