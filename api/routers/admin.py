import logging
import os
import secrets
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import get_admin
from api.roles import ADMIN
from api.security.passwords import verify_password
from api.security.tokens import create_user_token
from api.store.audit import get_audit_logs
from api.store.user_repository import get_user_by_email, set_user_role

load_dotenv()

logger = logging.getLogger("api.admin")
router = APIRouter(prefix="/admin", tags=["Admin & User Management"])


def admin_login(username: str, password: str) -> dict:
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    legacy_admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if not admin_email or username.strip().casefold() != admin_email.casefold():
        logger.warning("Admin login rejected: Username '%s' does not match ADMIN_EMAIL", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    is_valid = False
    if admin_password_hash:
        try:
            is_valid = verify_password(password, admin_password_hash)
        except Exception as exc:
            logger.error("Admin password hash verification failed with exception: %s", exc, exc_info=True)
            is_valid = False
    elif legacy_admin_password:
        is_valid = secrets.compare_digest(password, legacy_admin_password)

    if not is_valid:
        logger.warning("Admin login rejected: Invalid password for '%s'", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    logger.info("Admin login succeeded for '%s'", username)
    return {
        "access_token": create_user_token("admin", ADMIN),
        "token_type": "bearer",
        "user_id": "admin",
        "email": admin_email,
        "role": ADMIN,
    }


class UserRoleUpdate(BaseModel):
    role: Literal["Shopper", "Merchandiser"]


@router.get("/users")
def find_user(email: Optional[str] = None, _=Depends(get_admin)):
    """Find a user by email address."""
    if not email or not email.strip():
        raise HTTPException(status_code=400, detail="Provide a valid email")

    try:
        user = get_user_by_email(email.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
    }


@router.patch("/users/{user_id}/role")
def update_user_role(user_id: int, update: UserRoleUpdate, _=Depends(get_admin)):
    """Update a user's role to Shopper or Merchandiser."""
    user = set_user_role(user_id, update.role)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("/audit")
def audit_endpoint(limit: int = 50, offset: int = 0, _=Depends(get_admin)):
    """Admin endpoint to view query history and tools used."""
    return get_audit_logs(limit=limit, offset=offset)


@router.post("/reindex")
def reindex_catalog(_=Depends(get_admin)):
    """Admin endpoint to reload the feed data (runs Phase 1 data cleaning)."""
    from ingestion.ingest import DEFAULT_OUTPUT_DIR, find_feed, run_phase1_ingest

    try:
        csv_path = find_feed()
        summary = run_phase1_ingest(csv_path, DEFAULT_OUTPUT_DIR)
        return {
            "status": "success",
            "phase": "Phase 1: Data Cleaning & Feed Reload",
            "rows_read": summary.rows_read,
            "rows_loaded": summary.rows_loaded,
            "rows_rejected": summary.rows_rejected,
            "duplicates_removed": summary.duplicates_removed,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Feed reload failed: {exc}",
        ) from exc
