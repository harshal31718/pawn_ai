import asyncio

from app.constants import TOOL_TIMEOUT_SECONDS

from .base import ToolContext, ToolSpec


async def run_tool(spec: ToolSpec, args: dict, ctx: ToolContext) -> str:
    """Runs a tool's handler under a wall-clock timeout. Tools never raise into
    the graph — any exception or timeout becomes a "TOOL_ERROR: ..." observation
    the agent can adapt to and keep going."""
    try:
        return await asyncio.wait_for(spec.handler(args, ctx), timeout=TOOL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return f"TOOL_ERROR: {spec.name} timed out after {TOOL_TIMEOUT_SECONDS}s"
    except Exception as e:
        # Security note (flagged by the A.9 security-auditor pass): this string is
        # no longer just transiently streamed -- Phase A / A.8 persists tool_log
        # observations (including TOOL_ERROR text) as part of a chat's trace and
        # serves it back via GET /conversations/{id}. No current handler's
        # exceptions embed secrets, but a future tool whose underlying library puts
        # request headers/body into its exception message could leak into stored,
        # API-served data through this catch-all. Keep new tool handlers' exception
        # paths free of anything sensitive in their __str__.
        return f"TOOL_ERROR: {e}"
