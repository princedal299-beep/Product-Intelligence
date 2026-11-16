
import logging
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

logger = logging.getLogger("api.access")
logger.setLevel(logging.INFO)
logger.propagate = False

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

has_file_handler = any(
    isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")) == LOG_FILE
    for h in logger.handlers
)
if not has_file_handler:
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

has_stream_handler = any(
    isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    for h in logger.handlers
)
if not has_stream_handler:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60


class RequestIdAndLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000
            response.headers["X-Request-ID"] = request_id

            logger.info(
                f"req_id={request_id} method={request.method} path={request.url.path} "
                f"status={response.status_code} duration={duration_ms:.1f}ms"
            )
            return response
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"req_id={request_id} method={request.method} path={request.url.path} "
                f"error={exc} duration={duration_ms:.1f}ms"
            )
            raise exc


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
