from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.core.rate_limiter import EndpointRateLimiter
from app.resolver.resolver import Resolver


@dataclass
class ToolContext:
    """Per-request context threaded into every tool handler."""
    user_id: str
    scope_type: Optional[str]  # [Phase M] None for stateless chats
    scope_id: Optional[str]    # [Phase M] None for stateless chats
    resolver: Resolver
    rate_limiter: EndpointRateLimiter


@dataclass
class ToolSpec:
    """A native tool exposed to the model. `parameters` is an OAI-format JSON
    schema dict; `handler` is the async function invoked with the model's
    parsed tool-call arguments and the current ToolContext."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], Awaitable[str]]
