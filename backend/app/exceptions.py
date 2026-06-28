from fastapi import Request
from fastapi.responses import JSONResponse


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)


class NoEndpointError(Exception):
    pass


class NotConfiguredError(ProviderError):
    """A feature the user must configure (e.g. Kaggle creds) is missing.

    Distinct stable code ("not_configured") + HTTP 412 so the frontend can render
    a "set this up in settings" prompt instead of a generic failure.
    """

    http_status = 412

    def __init__(self, message: str):
        super().__init__("not_configured", message)


class KaggleError(ProviderError):
    """A Kaggle round-trip failed (push/run/output). Maps to HTTP 502."""

    http_status = 502

    def __init__(self, message: str):
        super().__init__("kaggle", message)


async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    status = 429 if exc.kind == "rate_limit" else 502
    return JSONResponse({"error": exc.message}, status_code=status)


async def no_endpoint_error_handler(request: Request, exc: NoEndpointError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=503)


async def generate_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    """Handler for NotConfiguredError / KaggleError.

    Returns `detail` (so the frontend's error reader surfaces the message) plus a
    stable `code` for branching.
    """
    status = getattr(exc, "http_status", 502)
    return JSONResponse({"detail": exc.message, "code": exc.kind}, status_code=status)
