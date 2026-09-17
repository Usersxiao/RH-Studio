from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema import normalize_node, parse_field_data, widget_for, accept_for

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "rh_studio.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")
    return _conn


def init_db() -> None:
    conn = connect()
    with _lock:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webapp_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                cover_url TEXT DEFAULT '',
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                raw_schema TEXT DEFAULT '{}',
                schema_fetched_at TEXT,
                warning TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                node_name TEXT DEFAULT '',
                field_name TEXT NOT NULL,
                field_type TEXT DEFAULT 'STRING',
                field_value TEXT DEFAULT '',
                field_data TEXT DEFAULT '',
                description TEXT DEFAULT '',
                description_en TEXT DEFAULT '',
                display_label TEXT DEFAULT '',
                hidden INTEGER DEFAULT 0,
                required INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                UNIQUE(tool_id, node_id, field_name),
                FOREIGN KEY(tool_id) REFERENCES tools(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER,
                webapp_id TEXT NOT NULL,
                rh_task_id TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                status_code INTEGER,
                instance_type TEXT DEFAULT 'default',
                node_info_list TEXT DEFAULT '[]',
                outputs TEXT DEFAULT '[]',
                error_message TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(tool_id) REFERENCES tools(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS media_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                local_path TEXT NOT NULL,
                rh_file_name TEXT DEFAULT '',
                mime_type TEXT DEFAULT '',
                size INTEGER DEFAULT 0,
                file_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_media_hash ON media_files(file_hash);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            """
        )
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def _field_public(row: sqlite3.Row) -> dict[str, Any]:
    parsed = parse_field_data(row["field_data"])
    extra = parsed.get("extra") or {}
    return {
        "id": row["id"],
        "node_id": row["node_id"],
        "node_name": row["node_name"],
        "field_name": row["field_name"],
        "field_type": row["field_type"],
        "field_value": row["field_value"],
        "field_data": row["field_data"],
        "description": row["description"],
        "description_en": row["description_en"],
        "display_label": row["display_label"] or row["description"] or row["field_name"],
        "hidden": bool(row["hidden"]),
        "required": bool(row["required"]),
        "sort_order": row["sort_order"],
        "widget": widget_for(row["field_type"], extra),
        "options": parsed.get("options") or [],
        "extra": extra,
        "accept": accept_for(row["field_type"]),
        "key": f"{row['node_id']}::{row['field_name']}",
    }


def _tool_public(row: sqlite3.Row, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "webapp_id": row["webapp_id"],
        "name": row["name"],
        "display_name": row["display_name"] or row["name"],
        "cover_url": row["cover_url"],
        "description": row["description"],
        "category": row["category"],
        "warning": row["warning"],
        "enabled": bool(row["enabled"]),
        "schema_fetched_at": row["schema_fetched_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "field_count": len(fields) if fields is not None else None,
        "fields": fields,
    }


def list_tools() -> list[dict[str, Any]]:
    conn = connect()
    with _lock:
        rows = conn.execute("SELECT * FROM tools ORDER BY updated_at DESC, id DESC").fetchall()
        counts = {
            item["tool_id"]: item["c"]
            for item in conn.execute("SELECT tool_id, COUNT(*) AS c FROM tool_fields GROUP BY tool_id")
        }
    result = []
    for row in rows:
        item = _tool_public(row)
        item["field_count"] = counts.get(row["id"], 0)
        result.append(item)
    return result


def get_tool(tool_id: int) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
        if not row:
            return None
        fields = conn.execute(
            "SELECT * FROM tool_fields WHERE tool_id = ? ORDER BY sort_order ASC, id ASC",
            (tool_id,),
        ).fetchall()
    return _tool_public(row, [_field_public(field) for field in fields])


def get_tool_by_webapp(webapp_id: str) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT id FROM tools WHERE webapp_id = ?", (webapp_id,)).fetchone()
    return get_tool(row["id"]) if row else None


def upsert_tool_from_schema(
    webapp_id: str,
    name: str,
    cover_url: str,
    raw_schema: dict[str, Any],
    node_info_list: list[dict[str, Any]],
    warning: str = "",
) -> dict[str, Any]:
    conn = connect()
    stamp = now_iso()
    existing = get_tool_by_webapp(webapp_id)
    preserved: dict[tuple[str, str], dict[str, Any]] = {}
    if existing:
        for field in existing.get("fields") or []:
            preserved[(str(field["node_id"]), str(field["field_name"]))] = field

    with _lock:
        if existing:
            conn.execute(
                """
                UPDATE tools
                SET name = ?, cover_url = ?, raw_schema = ?, schema_fetched_at = ?, warning = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, cover_url, json.dumps(raw_schema, ensure_ascii=False), stamp, warning, stamp, existing["id"]),
            )
            tool_id = existing["id"]
            conn.execute("DELETE FROM tool_fields WHERE tool_id = ?", (tool_id,))
        else:
            cur = conn.execute(
                """
                INSERT INTO tools(webapp_id, name, cover_url, description, category, display_name, raw_schema, schema_fetched_at, warning, enabled, created_at, updated_at)
                VALUES(?, ?, ?, '', '', '', ?, ?, ?, 1, ?, ?)
                """,
                (webapp_id, name, cover_url, json.dumps(raw_schema, ensure_ascii=False), stamp, warning, stamp, stamp),
            )
            tool_id = cur.lastrowid

        for index, node in enumerate(node_info_list):
            normalized = normalize_node(node, index)
            old = preserved.get((normalized["node_id"], normalized["field_name"]))
            display_label = normalized["display_label"]
            hidden = normalized["hidden"]
            required = normalized["required"]
            if old:
                display_label = old.get("display_label") or display_label
                hidden = 1 if old.get("hidden") else 0
                required = 1 if old.get("required") else 0
            conn.execute(
                """
                INSERT INTO tool_fields(
                    tool_id, node_id, node_name, field_name, field_type, field_value, field_data,
                    description, description_en, display_label, hidden, required, sort_order
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_id,
                    normalized["node_id"],
                    normalized["node_name"],
                    normalized["field_name"],
                    normalized["field_type"],
                    normalized["field_value"],
                    normalized["field_data"],
                    normalized["description"],
                    normalized["description_en"],
                    display_label,
                    hidden,
                    required,
                    index,
                ),
            )
        conn.commit()
    return get_tool(tool_id)


def update_tool(tool_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    current = get_tool(tool_id)
    if not current:
        return None
    conn = connect()
    stamp = now_iso()
    with _lock:
        conn.execute(
            """
            UPDATE tools
            SET display_name = ?, category = ?, description = ?, enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.get("display_name", current["display_name"]),
                payload.get("category", current["category"]),
                payload.get("description", current["description"]),
                1 if payload.get("enabled", current["enabled"]) else 0,
                stamp,
                tool_id,
            ),
        )
        for field in payload.get("fields") or []:
            field_id = field.get("id")
            if not field_id:
                continue
            conn.execute(
                """
                UPDATE tool_fields
                SET display_label = COALESCE(?, display_label),
                    hidden = COALESCE(?, hidden),
                    required = COALESCE(?, required),
                    field_value = COALESCE(?, field_value)
                WHERE id = ? AND tool_id = ?
                """,
                (
                    field.get("display_label"),
                    None if "hidden" not in field else (1 if field.get("hidden") else 0),
                    None if "required" not in field else (1 if field.get("required") else 0),
                    field.get("field_value"),
                    field_id,
                    tool_id,
                ),
            )
        conn.commit()
    return get_tool(tool_id)


def delete_tool(tool_id: int) -> bool:
    conn = connect()
    with _lock:
        cur = conn.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
        conn.commit()
        return cur.rowcount > 0


def create_task(tool_id: int | None, webapp_id: str, instance_type: str, node_info_list: list[dict[str, str]]) -> dict[str, Any]:
    conn = connect()
    stamp = now_iso()
    with _lock:
        cur = conn.execute(
            """
            INSERT INTO tasks(tool_id, webapp_id, rh_task_id, status, status_code, instance_type, node_info_list, outputs, error_message, created_at, updated_at)
            VALUES(?, ?, '', 'submitting', NULL, ?, ?, '[]', '', ?, ?)
            """,
            (tool_id, webapp_id, instance_type or "default", json.dumps(node_info_list, ensure_ascii=False), stamp, stamp),
        )
        task_id = cur.lastrowid
        conn.commit()
    return get_task(task_id)


def update_task(task_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "rh_task_id",
        "status",
        "status_code",
        "instance_type",
        "node_info_list",
        "outputs",
        "error_message",
    }
    assignments = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in {"node_info_list", "outputs"} and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        return get_task(task_id)
    assignments.append("updated_at = ?")
    values.append(now_iso())
    values.append(task_id)
    conn = connect()
    with _lock:
        conn.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", values)
        conn.commit()
    return get_task(task_id)


def _task_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tool_id": row["tool_id"],
        "webapp_id": row["webapp_id"],
        "rh_task_id": row["rh_task_id"],
        "status": row["status"],
        "status_code": row["status_code"],
        "instance_type": row["instance_type"],
        "node_info_list": json.loads(row["node_info_list"] or "[]"),
        "outputs": json.loads(row["outputs"] or "[]"),
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "tool_name": row["tool_name"] if "tool_name" in row.keys() else None,
        "display_name": row["display_name"] if "display_name" in row.keys() else None,
        "cover_url": row["cover_url"] if "cover_url" in row.keys() else None,
    }


def get_task(task_id: int) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute(
            """
            SELECT tasks.*, tools.name AS tool_name, tools.display_name AS display_name, tools.cover_url AS cover_url
            FROM tasks
            LEFT JOIN tools ON tools.id = tasks.tool_id
            WHERE tasks.id = ?
            """,
            (task_id,),
        ).fetchone()
    return _task_public(row) if row else None


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    with _lock:
        rows = conn.execute(
            """
            SELECT tasks.*, tools.name AS tool_name, tools.display_name AS display_name, tools.cover_url AS cover_url
            FROM tasks
            LEFT JOIN tools ON tools.id = tasks.tool_id
            ORDER BY tasks.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_task_public(row) for row in rows]


def list_pending_tasks() -> list[dict[str, Any]]:
    conn = connect()
    with _lock:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN ('queued', 'running', 'submitting') AND rh_task_id != ''
            ORDER BY id ASC
            """
        ).fetchall()
    return [_task_public(row) for row in rows]


def get_media_by_hash(file_hash: str) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT * FROM media_files WHERE file_hash = ? ORDER BY id DESC LIMIT 1", (file_hash,)).fetchone()
    return dict(row) if row else None


def get_media(media_id: int) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT * FROM media_files WHERE id = ?", (media_id,)).fetchone()
    return dict(row) if row else None


def save_media(
    original_name: str,
    local_path: str,
    rh_file_name: str,
    mime_type: str,
    size: int,
    file_hash: str,
) -> dict[str, Any]:
    conn = connect()
    stamp = now_iso()
    with _lock:
        cur = conn.execute(
            """
            INSERT INTO media_files(original_name, local_path, rh_file_name, mime_type, size, file_hash, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (original_name, local_path, rh_file_name, mime_type, size, file_hash, stamp),
        )
        media_id = cur.lastrowid
        conn.commit()
    return get_media(media_id)


def counts() -> dict[str, int]:
    conn = connect()
    with _lock:
        tools = conn.execute("SELECT COUNT(*) AS c FROM tools").fetchone()["c"]
        tasks = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status IN ('queued', 'running', 'submitting')"
        ).fetchone()["c"]
    return {"tools": tools, "tasks": tasks, "pending": pending}
