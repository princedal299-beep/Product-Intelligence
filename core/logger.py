import contextvars
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "api.log"

current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        req_id = current_request_id.get("-")
        if req_id and req_id != "-":
            record.req_id = f"req:{req_id[:8]}"
        else:
            record.req_id = "sys"
        return True


DEFAULT_FORMAT = "%(asctime)s [%(levelname)-5s] [%(req_id)s] [%(name)s:%(lineno)d] %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str | int | None = None,
    log_file: Path | str | None = None,
) -> None:
    if level is None:
        level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

    target_file = Path(log_file) if log_file else LOG_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    req_filter = RequestIdFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(req_filter)
    stream_handler.setLevel(level)

    file_handler = RotatingFileHandler(
        target_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(req_filter)
    file_handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    noisy_loggers = [
        "httpx",
        "httpcore",
        "urllib3",
        "google_genai",
        "google.genai",
        "google",
        "langchain_google_genai",
        "langsmith",
        "langchain",
        "mcp.server.streamable_http_manager",
        "mcp.client.streamable_http",
        "mcp.server.streamable_http",
    ]
    for noisy in noisy_loggers:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("asyncio").setLevel(logging.CRITICAL)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
