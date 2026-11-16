
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / "data" / "audit.sqlite3"

ROUTE_TO_AGENT = {
    "product_search": "catalog_agent",
    "product_details": "catalog_agent",
    "catalog_analytics": "catalog_agent",
    "jewellery_help": "knowledge_agent",
    "forbidden": "access_control (forbidden)",
    "unsupported": "safe_response",
}


def resolve_agent(route: str) -> str:
    return ROUTE_TO_AGENT.get(route, "catalog_agent")


def init_audit_db():
    AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(AUDIT_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                query TEXT NOT NULL,
                route TEXT NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL
            )
            """
        )


def record_audit(
    request_id: str,
    user_id: str,
    role: str,
    query: str,
    route: str,
    agent: str = "",
):
    init_audit_db()
    assigned_agent = agent or resolve_agent(route)
    timestamp = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(AUDIT_DB) as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (request_id, user_id, role, query, route, agent, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                str(user_id),
                role,
                query,
                route,
                assigned_agent,
                timestamp,
            ),
        )


def get_audit_logs(limit: int = 50, offset: int = 0):
    init_audit_db()
    safe_limit = max(0, limit)
    safe_offset = max(0, offset)

    with sqlite3.connect(AUDIT_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT request_id, user_id, role, query, route, agent, timestamp
            FROM audit_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        ).fetchall()

    logs = []
    for row in rows:
        item = dict(row)
        if not item.get("agent"):
            item["agent"] = resolve_agent(item.get("route", ""))
        logs.append(item)
    return logs
