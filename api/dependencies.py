from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from api.roles import ADMIN, MERCHANDISER, SHOPPER
from api.security.tokens import decode_token

bearer_auth = HTTPBearer()


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_auth),
) -> dict[str, Any]:
    """Dependency: Extract and validate Bearer JWT token from request header."""
    try:
        return decode_token(credentials.credentials)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_current_user(
    token_payload: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Dependency: Validate that request has a valid token and recognized user role."""
    if token_payload.get("role") not in {SHOPPER, MERCHANDISER, ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid user role is required",
        )
    return token_payload


def get_merchandiser(
    token_payload: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Dependency: Restrict access to Merchandisers and Admins."""
    if token_payload.get("role") not in {MERCHANDISER, ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Merchandiser role required",
        )
    return token_payload


def get_admin(
    token_payload: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Dependency: Restrict access strictly to Admins."""
    if token_payload.get("role") != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )
    return token_payload
