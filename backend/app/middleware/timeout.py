import asyncio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout: int = 45, sse_paths: list[str] | None = None):
        super().__init__(app)
        self.timeout = timeout
        self.sse_paths = sse_paths or []

    async def dispatch(self, request: Request, call_next):
        for path in self.sse_paths:
            if request.url.path.startswith(path):
                return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            return Response("Request timeout", status_code=504)
