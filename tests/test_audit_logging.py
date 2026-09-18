from __future__ import annotations

import sqlite3

import pytest

from app.core.audit_service import AuditService, audit_log, audit_service


@pytest.fixture()
def audit_db(tmp_path):
    """Point the singleton at a fresh, empty audit database."""
    db_file = tmp_path / "audit_test.db"
    audit_service.db_path = db_file
    audit_service._create_schema()
    return db_file


def read_table(db_file, table: str) -> list[dict]:
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    conn.close()
    return rows


def test_singleton_same_instance():
    assert AuditService() is audit_service


def test_log_task_event(audit_db):
    audit_service.log_task_event(
        task_id="42", event_type="task_created", metadata={"goal": "build a tower"}
    )
    rows = read_table(audit_db, "audit_events")
    assert len(rows) == 1
    assert rows[0]["event_type"] == "task_created"
    assert rows[0]["category"] == "task_lifecycle"
    assert rows[0]["task_id"] == "42"
    assert "build a tower" in rows[0]["metadata"]


def test_log_tool_run(audit_db):
    audit_service.log_tool_run(
        tool_name="filesystem.list",
        task_id=None,
        policy_outcome="ALLOW",
        success=True,
        duration_ms=12,
    )
    rows = read_table(audit_db, "tool_runs")
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "filesystem.list"
    assert rows[0]["policy_outcome"] == "ALLOW"
    assert rows[0]["success"] == 1
    assert rows[0]["duration_ms"] == 12


def test_log_tool_run_failure(audit_db):
    audit_service.log_tool_run(
        tool_name="shell.run",
        task_id="7",
        policy_outcome="REQUEST_APPROVAL",
        success=False,
        error="Approval required for tool 'shell.run'",
    )
    rows = read_table(audit_db, "tool_runs")
    assert rows[0]["success"] == 0
    assert rows[0]["task_id"] == "7"
    assert "Approval required" in rows[0]["error"]


def test_log_permission_eval(audit_db):
    audit_service.log_permission_eval(
        tool_name="git.diff", decision="ALLOW", context_keys=["zone"]
    )
    rows = read_table(audit_db, "permission_logs")
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "git.diff"
    assert rows[0]["decision"] == "ALLOW"
    assert "zone" in rows[0]["context_keys"]


def test_log_approval_request_and_decision(audit_db):
    audit_service.log_approval_request(
        approval_id="ap-1",
        tool_name="filesystem.write",
        input_preview='{"path": "D:/important.txt"}',
    )
    audit_service.log_approval_decision("ap-1", "APPROVED", decided_by="user")

    rows = read_table(audit_db, "approvals")
    assert len(rows) == 2
    assert rows[0]["approval_id"] == "ap-1"
    assert rows[0]["status"] == "pending"
    assert rows[1]["decision"] == "APPROVED"
    assert rows[1]["decided_by"] == "user"


def test_get_recent_logs_merges_and_orders(audit_db):
    audit_service.log_task_event(
        task_id="1", event_type="task_created", metadata=None
    )
    audit_service.log_tool_run(
        tool_name="filesystem.read", task_id=None,
        policy_outcome="ALLOW", success=True,
    )

    logs = audit_service.get_recent_logs()
    assert len(logs) == 2
    # most recently logged entry first
    assert logs[0]["_source"] == "tool_runs"
    assert logs[0]["tool_name"] == "filesystem.read"
    assert logs[1]["_source"] == "audit_events"
    assert logs[1]["event_type"] == "task_created"


def test_get_recent_logs_respects_limit(audit_db):
    for i in range(5):
        audit_service.log_task_event(task_id=str(i), event_type="task_created", metadata=None)
    logs = audit_service.get_recent_logs(limit=3)
    assert len(logs) == 3


def test_audit_log_convenience(audit_db):
    audit_log("task_started", {"task_id": "99", "metadata": {"zone": "test"}})
    rows = read_table(audit_db, "audit_events")
    assert rows[0]["event_type"] == "task_started"
    assert rows[0]["task_id"] == "99"
    assert "zone" in rows[0]["metadata"]


def test_unknown_table_rejected(audit_db):
    with pytest.raises(ValueError):
        audit_service._insert_record(table="evil; DROP TABLE x", data={"a": 1})


def test_tool_failure_is_audited_via_base_execute(audit_db):
    import asyncio

    from app.services.tools.base import Tool

    class _FailingTool(Tool):
        name = "audit.test"
        purpose = "always fails"
        risk_level = "LOW"
        allowed_scope = []

        async def _execute(self, input_data):
            raise RuntimeError("boom")

        def validate_input(self, data):
            pass

    result = asyncio.run(_FailingTool().execute({}))
    assert result.success is False
    assert "boom" in result.error

    rows = read_table(audit_db, "audit_events")
    assert len(rows) == 1
    assert rows[0]["event_type"] == "tool_failure"
    assert "audit.test" in rows[0]["metadata"]
    assert "boom" in rows[0]["metadata"]