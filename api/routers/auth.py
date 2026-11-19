"""Authentication and user session endpoints."""

import logging
import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_current_user, verify_token
from api.roles import SHOPPER
from api.routers.admin import admin_login
from api.security.passwords import verify_password
from api.security.tokens import create_mcp_token, create_user_token
from api.store.user_repository import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    normalize_email,
)

logger = logging.getLogger("api.auth")
router = APIRouter(tags=["Authentication"])


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate):
    """Register a new Shopper account."""
    try:
        created_user = create_user(user.email, user.password)
    except ValueError as exc:
        logger.warning("Registration validation error for '%s': %s", user.email, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        logger.warning("Registration conflict: email '%s' already exists", user.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    logger.info("New user registered: %s (id=%s)", created_user["email"], created_user["id"])
    return {
        "id": created_user["id"],
        "email": created_user["email"],
        "role": SHOPPER,
    }


def _process_login(form_data: OAuth2PasswordRequestForm):
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().casefold()
    submitted_email = form_data.username.strip().casefold()
    if admin_email and submitted_email == admin_email:
        return admin_login(form_data.username, form_data.password)

    try:
        db_user = get_user_by_email(form_data.username)
    except ValueError as exc:
        logger.warning("Login failed (invalid email format) for: '%s'", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc

    if not db_user or not verify_password(form_data.password, db_user["password_hash"]):
        logger.warning("Login failed (invalid credentials) for user: '%s'", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    role = db_user["role"]
    logger.info("User logged in successfully: '%s' (role=%s)", form_data.username, role)
    return {
        "access_token": create_user_token(db_user["id"], role),
        "token_type": "bearer",
        "user_id": db_user["id"],
        "email": db_user["email"],
        "role": role,
    }


@router.post("/Login")
def login_legacy(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password login endpoint (legacy /Login)."""
    return _process_login(form_data)


@router.post("/login")
def login_standard(form_data: OAuth2PasswordRequestForm = Depends()):
    """Standard REST login endpoint (/login)."""
    return _process_login(form_data)


@router.post("/mcp-token")
def issue_mcp_token(user=Depends(verify_token)):
    """Issue a short-lived token specifically scoped for MCP tool calls."""
    return {
        "access_token": create_mcp_token(user["user_id"], user["role"]),
        "token_type": "bearer",
    }


@router.get("/me")
def get_current_user_profile(user=Depends(verify_token)):
    """Get the profile of the currently logged in user."""
    user_id = user.get("user_id")
    role = user.get("role")
    if str(user_id) == "admin":
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
        return {
            "user_id": "admin",
            "email": admin_email,
            "role": role,
        }

    db_user = get_user_by_id(user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return {
        "user_id": db_user["id"],
        "email": db_user["email"],
        "role": db_user["role"],
    }
