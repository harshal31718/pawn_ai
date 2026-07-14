from datetime import datetime, timezone

from .base import ToolContext, ToolSpec

GET_DATETIME_PARAMETERS: dict = {
    "type": "object",
    "properties": {},
}


async def _get_datetime_handler(args: dict, ctx: ToolContext) -> str:
    now_utc = datetime.now(timezone.utc)
    return f"Current UTC time: {now_utc.isoformat()}"


GET_DATETIME_TOOL = ToolSpec(
    name="get_datetime",
    description="Returns the current date and time in UTC, ISO 8601 format.",
    parameters=GET_DATETIME_PARAMETERS,
    handler=_get_datetime_handler,
)
