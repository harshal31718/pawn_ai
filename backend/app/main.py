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

app = FastAPI(title="PAWN")

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


@app.get("/health")
async def health():
    return {"status": "ok"}
