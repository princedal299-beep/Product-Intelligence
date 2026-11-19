from pathlib import Path
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "api.log"

from core.logger import current_request_id, get_logger

logger = get_logger("api.access")

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60


class RequestIdAndLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        token = current_request_id.set(request_id)
        start_time = time.perf_counter()

        path = request.url.path
        is_api = not path.startswith(("/docs", "/openapi.json", "/favicon.ico"))

        if is_api:
            logger.info("--> START %s %s", request.method, path)

        try:
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000
            response.headers["X-Request-ID"] = request_id

            if is_api:
                status_label = "DONE" if response.status_code < 400 else f"WARN({response.status_code})"
                logger.info(
                    "<-- %s  %s %s | status=%d | duration=%.1fms",
                    status_label,
                    request.method,
                    path,
                    response.status_code,
                    duration_ms,
                )
            return response
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "<-- FAIL  %s %s | status=500 | duration=%.1fms | error=%s",
                request.method,
                path,
                duration_ms,
                exc,
                exc_info=True,
            )
            raise exc
        finally:
            current_request_id.reset(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.request_timestamps = {}

    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            client_key = auth_header
        elif request.client:
            client_key = request.client.host
        else:
            client_key = "unknown"

        now = time.time()
        timestamps = self.request_timestamps.get(client_key, [])

        recent_timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        self.request_timestamps[client_key] = recent_timestamps

        if len(recent_timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            req_id = getattr(request.state, "request_id", "")
            logger.warning(
                f"req_id={req_id} client={client_key} status=429 Rate limit exceeded (20 req/min)"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Maximum 20 requests per minute.",
                    "request_id": req_id,
                },
                headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
            )

        self.request_timestamps[client_key].append(now)
        return await call_next(request)
