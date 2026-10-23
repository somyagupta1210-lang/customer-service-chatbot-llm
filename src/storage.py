"""Small SQLite persistence layer for versions, jobs, documents, metrics and audit logs."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from .config import settings

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_connection() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_database() -> None:
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS versions (
            version_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
            activated_at TEXT, parent_version TEXT, manifest_json TEXT NOT NULL, quality_json TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, username TEXT,
            action TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            metric_name TEXT NOT NULL, value REAL NOT NULL, details_json TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT, details_json TEXT
        );
        CREATE TABLE IF NOT EXISTS documents (
            path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, normalized_sha256 TEXT NOT NULL,
            status TEXT NOT NULL, reason TEXT DEFAULT '', rows_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL, last_version TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

def record_audit(action: str, status: str, username: str = "system", details: dict[str, Any] | None = None) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO audit_log(created_at, username, action, status, details_json) VALUES (?, ?, ?, ?, ?)",
                     (utc_now(), username, action, status, json.dumps(details or {}, default=str)))

def record_metric(name: str, value: float, details: dict[str, Any] | None = None) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO metrics(created_at, metric_name, value, details_json) VALUES (?, ?, ?, ?)",
                     (utc_now(), name, float(value), json.dumps(details or {}, default=str)))

def update_version_status(version_id: str, status: str, quality: dict[str, Any] | None = None) -> None:
    with get_connection() as conn:
        if quality is None:
            conn.execute("UPDATE versions SET status=? WHERE version_id=?", (status, version_id))
        else:
            conn.execute("UPDATE versions SET status=?, quality_json=? WHERE version_id=?",
                         (status, json.dumps(quality, default=str), version_id))

def save_version(version_id: str, status: str, manifest: dict[str, Any], parent_version: str | None = None,
                 quality: dict[str, Any] | None = None, activated_at: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute("""INSERT OR REPLACE INTO versions
        (version_id,status,created_at,activated_at,parent_version,manifest_json,quality_json)
        VALUES (?,?,?,?,?,?,?)""", (version_id,status,utc_now(),activated_at,parent_version,
                                      json.dumps(manifest, default=str),json.dumps(quality or {}, default=str)))

def get_active_version() -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT version_id FROM versions WHERE status='active' ORDER BY activated_at DESC LIMIT 1").fetchone()
    return row["version_id"] if row else None

def get_version_status(version_id: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT status FROM versions WHERE version_id=?", (version_id,)).fetchone()
    return row["status"] if row else None

def set_active_version(version_id: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE versions SET status='previous' WHERE status='active' AND version_id != ?", (version_id,))
        conn.execute("UPDATE versions SET status='active', activated_at=? WHERE version_id=?", (utc_now(), version_id))

def get_previous_version(exclude: str | None = None) -> str | None:
    with get_connection() as conn:
        if exclude:
            row = conn.execute("SELECT version_id FROM versions WHERE status='previous' AND version_id != ? ORDER BY activated_at DESC LIMIT 1", (exclude,)).fetchone()
        else:
            row = conn.execute("SELECT version_id FROM versions WHERE status='previous' ORDER BY activated_at DESC LIMIT 1").fetchone()
    return row["version_id"] if row else None

def list_versions(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM versions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

def recent_metrics(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM metrics ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

def recent_audit(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

def get_document(path: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()
    return dict(row) if row else None

def upsert_document(path: str, sha256: str, normalized_sha256: str, status: str,
                    reason: str = "", rows: list[tuple[str, str]] | None = None,
                    last_version: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute("""INSERT INTO documents(path,sha256,normalized_sha256,status,reason,rows_json,updated_at,last_version)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,
        normalized_sha256=excluded.normalized_sha256,status=excluded.status,reason=excluded.reason,
        rows_json=excluded.rows_json,updated_at=excluded.updated_at,last_version=COALESCE(excluded.last_version,documents.last_version)""",
        (path,sha256,normalized_sha256,status,reason,json.dumps(rows or []),utc_now(),last_version))

def list_documents() -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY path").fetchall()]
