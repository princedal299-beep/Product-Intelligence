import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from api.security.passwords import hash_password

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_DATABASE = Path(
    os.environ.get("USER_DATABASE_PATH", PROJECT_ROOT / "data" / "users.sqlite3")
)


def _connect():
    USER_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USER_DATABASE, timeout=300)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Shopper'
                CHECK (role IN ('Shopper', 'Merchandiser')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def normalize_email(email):
    normalized = email.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


def create_user(email, password):
    normalized = normalize_email(email)
    hashed = hash_password(password)
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (normalized, hashed),
        )
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def get_user_by_email(email):
    normalized = normalize_email(email)
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = ?",
            (normalized,),
        ).fetchone()
    return dict(row) if row else None



def get_user_by_id(user_id):
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def set_user_role(user_id, role):
    if role not in {"Shopper", "Merchandiser"}:
        raise ValueError("Only Shopper and Merchandiser roles can be assigned.")
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id),
        )
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None
