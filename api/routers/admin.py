import logging
import os
import secrets
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
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


reindex_state = {
    "status": "idle",
    "processed": 0,
    "total": 0,
    "started_at": None,
    "completed_at": None,
    "error": None,
    "summary": None,
}


def _run_background_reindex(csv_path, rebuild_faiss: bool = True):
    global reindex_state
    import shutil
    from datetime import datetime, timezone
    from ingestion.ingest import DEFAULT_OUTPUT_DIR

    staging_dir = DEFAULT_OUTPUT_DIR.parent / "catalog_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    reindex_state["status"] = "running"
    reindex_state["started_at"] = datetime.now(timezone.utc).isoformat()
    reindex_state["completed_at"] = None
    reindex_state["error"] = None
    reindex_state["processed"] = 0
    reindex_state["total"] = 0
    logger.info("Background reindexing started with staging directory: %s", staging_dir)

    def on_progress(processed: int, total: int):
        global reindex_state
        reindex_state["processed"] = processed
        reindex_state["total"] = total

    try:
        if rebuild_faiss:
            from ingestion.build_faiss_index import build_catalog
            summary = build_catalog(
                csv_path=csv_path,
                output_dir=staging_dir,
                progress_callback=on_progress,
            )
        else:
            from ingestion.ingest import run_phase1_ingest
            summary = run_phase1_ingest(csv_path, staging_dir)

        for fname in ("catalog.sqlite3", "products.faiss", "manifest.json", "rejects.csv"):
            src = staging_dir / fname
            dst = DEFAULT_OUTPUT_DIR / fname
            if src.is_file():
                shutil.copy2(src, dst)

        try:
            from mcp_service.tools import _catalog_index
            _catalog_index.cache_clear()
        except Exception:
            pass

        reindex_state["status"] = "completed"
        reindex_state["completed_at"] = datetime.now(timezone.utc).isoformat()
        reindex_state["processed"] = summary.rows_loaded
        reindex_state["total"] = summary.rows_loaded
        reindex_state["summary"] = {
            "rows_read": summary.rows_read,
            "rows_loaded": summary.rows_loaded,
            "rows_rejected": summary.rows_rejected,
            "duplicates_removed": summary.duplicates_removed,
        }
        logger.info("Background reindexing completed successfully: %s", reindex_state["summary"])
    except Exception as exc:
        logger.error("Background reindexing failed: %s", exc, exc_info=True)
        reindex_state["status"] = "failed"
        reindex_state["completed_at"] = datetime.now(timezone.utc).isoformat()
        reindex_state["error"] = str(exc)
    finally:
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass


@router.post("/reindex")
def reindex_catalog(
    rebuild_faiss: bool = True,
    _=Depends(get_admin),
):
    global reindex_state
    if reindex_state.get("status") == "running":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "status": "already_running",
                "message": "Catalog reindexing is currently in progress.",
                "started_at": reindex_state.get("started_at"),
            },
        )

    from ingestion.ingest import find_feed

    try:
        csv_path = find_feed()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feed detection failed: {exc}",
        ) from exc

    import threading

    reindex_thread = threading.Thread(
        target=_run_background_reindex,
        args=(csv_path, rebuild_faiss),
        daemon=True,
        name="catalog-reindex-worker",
    )
    reindex_thread.start()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "started",
            "message": "Reindexing started .",
            "rebuild_faiss": rebuild_faiss,
        },
    )


@router.get("/reindex/status")
def reindex_status_endpoint(_=Depends(get_admin)):
    """Check background reindexing status and metrics."""
    return reindex_state
