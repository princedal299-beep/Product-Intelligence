from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)

from core.logger import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.middleware import RateLimitMiddleware, RequestIdAndLoggingMiddleware
from api.routers.admin import router as admin_router
from api.routers.auth import router as auth_router
from api.routers.chat import router as chat_router

app = FastAPI(title="Product Intelligence API")

app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIdAndLoggingMiddleware)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(chat_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "request_id": getattr(request.state, "request_id", ""),
        },
    )
