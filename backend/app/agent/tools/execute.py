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
        return f"TOOL_ERROR: {e}"
