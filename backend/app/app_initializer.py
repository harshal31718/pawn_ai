from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.constants import CHECKPOINTS_DB
from app.agent.graph import build_agent_graph
from app.registry.loader import load_registry
from app.core.rate_limiter import EndpointRateLimiter
from app.resolver.resolver import Resolver

@asynccontextmanager
async def initialize_managers():
    """
    Async context manager that initializes managers, managing the lifetime
    of the persistent SQLite checkpointer context.
    """
    CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registry()
    rate_limiter = EndpointRateLimiter()
    resolver = Resolver(registry, rate_limiter)
    
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINTS_DB)) as checkpointer:
        graph = build_agent_graph(resolver, rate_limiter).compile(checkpointer=checkpointer)
        yield {
            "checkpointer": checkpointer,
            "graph": graph,
            "registry": registry,
            "rate_limiter": rate_limiter,
            "resolver": resolver
        }

