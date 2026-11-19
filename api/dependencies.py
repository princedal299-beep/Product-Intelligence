from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from api.roles import ADMIN, MERCHANDISER, SHOPPER
from api.security.tokens import decode_token

bearer_auth = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_auth)) -> dict:
    try:
        payload = decode_token(credentials.credentials)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("token_type") == "mcp":
        raise HTTPException(status_code=401, detail="MCP scoped tokens cannot be used as user session tokens.")

    return payload

def get_current_user(token_payload: dict = Depends(verify_token)) -> dict:
    user_id = token_payload.get("user_id")
    if str(user_id) == "admin":
        return token_payload

    from api.store.user_repository import get_user_by_id
    db_user = get_user_by_id(user_id)
    if not db_user:
        raise HTTPException(status_code=401, detail="User account no longer exists.")

    token_payload["role"] = db_user["role"]
    return token_payload


def get_admin(
    token_payload: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    if token_payload.get("role") != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )
    return token_payload
