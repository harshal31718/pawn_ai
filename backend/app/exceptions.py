from fastapi import Request
from fastapi.responses import JSONResponse


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)


class NoEndpointError(Exception):
    pass


async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    status = 429 if exc.kind == "rate_limit" else 502
    return JSONResponse({"error": exc.message}, status_code=status)


async def no_endpoint_error_handler(request: Request, exc: NoEndpointError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=503)
