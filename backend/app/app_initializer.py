from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.constants import CHECKPOINTS_DB
from app.agent.graph import build_agent_graph

@asynccontextmanager
async def initialize_managers():
    """
    Async context manager that initializes managers, managing the lifetime
    of the persistent SQLite checkpointer context.
    """
    CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINTS_DB)) as checkpointer:
        graph = build_agent_graph().compile(checkpointer=checkpointer)
        yield {
            "checkpointer": checkpointer,
            "graph": graph
        }
