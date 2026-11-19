import asyncio
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from workflow.graph import run_workflow
from api.roles import SHOPPER
from api.security.tokens import create_mcp_token
from api.store.audit import record_audit
from api.dependencies import get_current_user

logger = logging.getLogger("api.chat")

router = APIRouter(tags=["Chat"])


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    thread_id: Optional[str] = "default"
    stream: Optional[bool] = False


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    trace_id: str
    request_id: str


@router.post("/chat")
async def chat_endpoint(
    chat_req: ChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    query = chat_req.query.strip()
    role = current_user.get("role", SHOPPER)
    user_id = current_user.get("user_id", "anonymous")
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    trace_id = f"trace-{uuid.uuid4().hex[:12]}"


    raw_thread = (chat_req.thread_id or "default").strip()
    clean_session_id = re.sub(r"^user_[^_]+_", "", raw_thread)
    if not clean_session_id or clean_session_id == "default":
        clean_session_id = "default"
    thread_id = f"user_{user_id}_{clean_session_id}"

    logger.info("Chat query from user='%s' (role=%s, thread='%s'): '%.60s'", user_id, role, thread_id, query)

    try:
        mcp_token = create_mcp_token(user_id, role)
        workflow_result = await run_workflow(
            query=query,
            role=role,
            login_token=mcp_token,
            thread_id=thread_id,
        )
    except ValueError as exc:
        logger.warning(f"req_id={request_id} Invalid request credentials: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request credentials: {exc}",
        ) from exc
    except PermissionError as exc:
        logger.warning(f"req_id={request_id} Permission denied: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {exc}",
        ) from exc
    except Exception as exc:
        logger.error(f"req_id={request_id} Upstream chat workflow error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable or upstream processing error: {exc}",
        ) from exc

    plan = workflow_result.get("plan")
    if plan == "forbidden":
        logger.warning(
            f"req_id={request_id} forbidden_access user_id={user_id} role={role} attempted_route=catalog_analytics"
        )
        record_audit(
            request_id,
            str(user_id),
            role,
            query,
            route="forbidden",
            agent="access_control (forbidden)",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Catalog analytics and numerical metrics are available to merchandisers and admins only.",
        )

    answer = workflow_result.get("generation", "No response generated.")

    
    # Step 3: Determine sources for response
    sources = []
    if (
        "I can't help with that request" not in answer
        and "Sorry, I could not confirm" not in answer
        and "not available" not in answer.lower()
    ):
        if plan == "jewellery_help":
            sources = ["jewellery_care", "ring_sizes"]
        elif plan in {"product_search", "product_details", "catalog_analytics"}:
            sources = ["catalog.sqlite3"]

    # Step 4: Record audit log
    record_audit(request_id, str(user_id), role, query, plan or "product_search")

    # Step 5: Return streaming or direct JSON response
    if chat_req.stream or request.headers.get("accept") in {"text/event-stream", "text/plain"}:
        async def stream_generator():
            for line in answer.splitlines(keepends=True):
                words = line.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words) - 1 else "")
                    yield chunk
                    await asyncio.sleep(0.015)

        return StreamingResponse(
            stream_generator(),
            media_type="text/plain",
            headers={
                "X-Trace-ID": trace_id,
                "X-Request-ID": request_id,
                "Cache-Control": "no-cache",
            },
        )

    return ChatResponse(
        answer=answer,
        sources=sources,
        trace_id=trace_id,
        request_id=request_id,
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(
    chat_req: ChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    chat_req.stream = True
    return await chat_endpoint(chat_req, request, current_user)
