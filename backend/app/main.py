from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.timeout import RequestTimeoutMiddleware
from app.exceptions import (
    ProviderError,
    NoEndpointError,
    provider_error_handler,
    no_endpoint_error_handler,
)
from app.routes.chat import router as chat_router
from app.routes.upload import router as upload_router
from app.routes.conversations import router as conversations_router
from app.routes.registry import router as registry_router
from app.app_initializer import initialize_managers
from app.core.llm_core import close_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with initialize_managers() as deps:
        app.state.graph = deps["graph"]
        app.state.checkpointer = deps["checkpointer"]
        app.state.registry = deps["registry"]
        yield
    await close_client()




app = FastAPI(title="PAWN", lifespan=lifespan)

app.add_exception_handler(ProviderError, provider_error_handler)
app.add_exception_handler(NoEndpointError, no_endpoint_error_handler)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestTimeoutMiddleware, timeout=45, sse_paths=["/chat"])
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(conversations_router)
app.include_router(registry_router)



@app.get("/health")
async def health():
    return {"status": "ok"}
