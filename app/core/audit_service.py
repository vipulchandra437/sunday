from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA = {
    "audit_events": """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            category TEXT NOT NULL,
            task_id TEXT,
            metadata TEXT,
            timestamp TEXT NOT NULL
        )
    """,
    "tool_runs": """
        CREATE TABLE IF NOT EXISTS tool_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            task_id TEXT,
            policy_outcome TEXT NOT NULL,
            success BOOLEAN,
            duration_ms INTEGER DEFAULT 0,
            error TEXT,
            timestamp TEXT NOT NULL
        )
    """,
    "permission_logs": """
        CREATE TABLE IF NOT EXISTS permission_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            decision TEXT NOT NULL,
            context_keys TEXT,
            timestamp TEXT NOT NULL
        )
    """,
    "approvals": """
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_id TEXT,
            tool_name TEXT,
            input_preview TEXT,
            status TEXT,
            decision TEXT,
            decided_by TEXT,
            timestamp TEXT NOT NULL
        )
    """,
}


class AuditService:
    """Thread-safe audit logging service with SQLite backend."""

    _instance: AuditService | None = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "AuditService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str | Path | None = None) -> None:
        if self._initialized:
            return

        if db_path is None:
            from app.config.settings import settings

            sqlite_path = Path(settings.database_url.replace("sqlite:///", ""))
            db_path = sqlite_path.with_name(sqlite_path.stem + "_audit.db")

        self.db_path = Path(db_path)
        self._create_schema()
        self._initialized = True

    def _create_schema(self) -> None:
        """Create audit tables if they don't exist yet."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                for ddl in _SCHEMA.values():
                    conn.execute(ddl)
                conn.commit()
            finally:
                conn.close()

    def log_task_event(
        self, task_id: str, event_type: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Log a task lifecycle event (created, planning, executing, completed, failed)."""
        self._insert_record(
            table="audit_events",
            data={
                "event_type": event_type,
                "category": "task_lifecycle",
                "task_id": task_id,
                "metadata": json.dumps(metadata) if metadata else "{}",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def log_tool_run(
        self,
        tool_name: str,
        task_id: str | None,
        policy_outcome: str,
        success: bool,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> None:
        """Log a tool execution attempt."""
        self._insert_record(
            table="tool_runs",
            data={
                "tool_name": tool_name,
                "task_id": task_id,
                "policy_outcome": policy_outcome,
                "success": success,
                "duration_ms": duration_ms,
                "error": error,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def log_permission_eval(
        self, tool_name: str, decision: str, context_keys: list | None = None
    ) -> None:
        """Log a permission evaluation."""
        self._insert_record(
            table="permission_logs",
            data={
                "tool_name": tool_name,
                "decision": decision,
                "context_keys": json.dumps(context_keys) if context_keys else "[]",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def log_approval_request(
        self, approval_id: str, tool_name: str, input_preview: str
    ) -> None:
        """Log an approval request."""
        self._insert_record(
            table="approvals",
            data={
                "approval_id": approval_id,
                "tool_name": tool_name,
                "input_preview": input_preview,
                "status": "pending",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def log_approval_decision(
        self, approval_id: str, decision: str, decided_by: str = "user"
    ) -> None:
        """Log an approval decision."""
        self._insert_record(
            table="approvals",
            data={
                "approval_id": approval_id,
                "decision": decision,
                "decided_by": decided_by,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def _insert_record(self, table: str, data: dict[str, Any]) -> None:
        """Insert a record into SQLite (thread-safe)."""
        if table not in _SCHEMA:
            raise ValueError(f"Unknown audit table: {table}")

        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                cursor = conn.cursor()

                columns = ", ".join(data.keys())
                placeholders = ", ".join(["?" for _ in data])

                query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
                cursor.execute(query, list(data.values()))
                conn.commit()
            finally:
                conn.close()

    def get_recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent audit logs for UI display."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                rows: list[dict[str, Any]] = []
                for table in ("audit_events", "tool_runs"):
                    columns = [
                        col[1] for col in conn.execute(f"PRAGMA table_info({table})")
                    ]
                    for record in conn.execute(f"SELECT * FROM {table}").fetchall():
                        row = dict(zip(columns, record))
                        row["_source"] = table
                        rows.append(row)
            finally:
                conn.close()

        rows.sort(
            key=lambda r: (r.get("timestamp") or "", r.get("id") or 0),
            reverse=True,
        )
        return rows[:limit]


# Singleton instance
audit_service = AuditService()


# Convenience function for easy import
def audit_log(event_type: str, data: dict[str, Any]) -> None:
    """Convenience function to log audit events."""
    audit_service.log_task_event(
        task_id=data.get("task_id"),
        event_type=event_type,
        metadata={k: v for k, v in data.items() if k != "task_id"},
    )