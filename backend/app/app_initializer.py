from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.constants import CHECKPOINTS_DB
from app.agent.graph import build_agent_graph
from app.registry.loader import load_registry
from app.core.rate_limiter import EndpointRateLimiter
from app.resolver.resolver import Resolver
from app import config

@asynccontextmanager
async def initialize_managers():
    """
    Async context manager that initializes managers, managing the lifetime
    of the persistent SQLite checkpointer context.
    """
    CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registry()
    rate_limiter = EndpointRateLimiter()
    secrets = {
        "gemini_api_key":      config.GEMINI_API_KEY,
        "cerebras_api_key":    config.CEREBRAS_API_KEY,
        "groq_api_key":        config.GROQ_API_KEY,
        "huggingface_api_key": config.HUGGINGFACE_API_KEY,
        "github_api_key":      config.GITHUB_API_KEY,
        "openrouter_api_key":  config.OPENROUTER_API_KEY,
    }
    resolver = Resolver(registry, rate_limiter, secrets)
    
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINTS_DB)) as checkpointer:
        graph = build_agent_graph(resolver, rate_limiter).compile(checkpointer=checkpointer)
        yield {
            "checkpointer": checkpointer,
            "graph": graph,
            "registry": registry,
            "rate_limiter": rate_limiter,
            "resolver": resolver
        }

