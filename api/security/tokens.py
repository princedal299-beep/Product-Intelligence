import os
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt

from api.keys.key_loader import PRIVATE_KEY, PUBLIC_KEY
from api.roles import scopes_for_role

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
MCP_TOKEN_EXPIRE_SECONDS = int(os.getenv("MCP_TOKEN_EXPIRE_SECONDS", "60"))


def create_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta is not None:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)


def create_user_token(user_id: int | str, role: str) -> str:
    """Create a standard user session token."""
    return create_token({
        "user_id": user_id,
        "sub": str(user_id),
        "role": role,
        "token_type":"session",
    })


def create_mcp_token(user_id: int | str, role: str) -> str:
    """Create a short-lived token specifically scoped for MCP catalog tool calls."""
    return create_token(
        {
            "user_id": user_id,
            "sub": str(user_id),
            "role": role,
            "token_type":"mcp",
            "scope": " ".join(scopes_for_role(role)),
        },
        expires_delta=timedelta(seconds=MCP_TOKEN_EXPIRE_SECONDS),
    )


def decode_token(token: str) -> dict:
    """Decode and validate a signed RS256 JWT token."""
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("user_id")
    role = payload.get("role")
    if user_id is None or role is None:
        raise ValueError("Token missing user_id or role")
    return payload
