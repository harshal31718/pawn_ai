from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.timeout import RequestTimeoutMiddleware
from app.config import CORS_ORIGINS
from app.exceptions import (
    ProviderError,
    NoEndpointError,
    NotConfiguredError,
    KaggleError,
    UnknownModelError,
    provider_error_handler,
    no_endpoint_error_handler,
    generate_error_handler,
)
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.upload import router as upload_router
from app.routes.conversations import router as conversations_router
from app.routes.registry import router as registry_router
from app.routes.keys import router as keys_router
from app.routes.generate import router as generate_router
from app.routes.crypto import router as crypto_router
from app.app_initializer import initialize_managers
from app.core.llm_core import close_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with initialize_managers() as deps:
        app.state.graph = deps["graph"]
        app.state.checkpointer = deps["checkpointer"]
        app.state.registry = deps["registry"]
        app.state.rate_limiter = deps["rate_limiter"]
        app.state.resolver = deps["resolver"]
        yield
    await close_client()




app = FastAPI(title="PAWN", lifespan=lifespan)

app.add_exception_handler(ProviderError, provider_error_handler)
app.add_exception_handler(NoEndpointError, no_endpoint_error_handler)
# More specific than ProviderError — registered so subclasses map to 412/502 + code.
app.add_exception_handler(NotConfiguredError, generate_error_handler)
app.add_exception_handler(KaggleError, generate_error_handler)
app.add_exception_handler(UnknownModelError, generate_error_handler)

app.add_middleware(AuthMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestTimeoutMiddleware, timeout=45, sse_paths=["/chat", "/generate"])
app.add_middleware(SecurityHeadersMiddleware)
_cors_origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
if "*" in _cors_origins:
    raise ValueError("CORS_ORIGINS must not contain '*' — list explicit allowed origins")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(conversations_router)
app.include_router(registry_router)
app.include_router(keys_router)
app.include_router(generate_router)
app.include_router(crypto_router)



@app.get("/health")
async def health():
    return {"status": "ok"}
