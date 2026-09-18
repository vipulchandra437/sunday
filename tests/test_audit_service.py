from app.core.models import Approval, AuditEvent, ToolRun
from app.services.audit_service import AuditService


def _sample_payload() -> dict:
    return {
        "api_key": "sk-secret-123",
        "password": "hunter2",
        "Authorization": "Bearer abc",
        "safe_field": "harmless value",
        "nested": {"private_key": "xxxx", "note": "ok", "items": ["a", "b"]},
    }


def test_sanitize_redacts_secret_keys(db):
    audit = AuditService(db)
    cleaned = audit.sanitize(_sample_payload())
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["Authorization"] == "[REDACTED]"
    assert cleaned["nested"]["private_key"] == "[REDACTED]"
    assert cleaned["safe_field"] == "harmless value"
    assert cleaned["nested"]["note"] == "ok"


def test_log_permission_eval(db):
    audit = AuditService(db)
    audit.log_permission_eval(
        task_id=None, tool_name="shell.run", decision="REQUEST_APPROVAL", context={"path": "/tmp"}
    )
    event = db.query(AuditEvent).one()
    assert event.event_type == "permission_eval"
    assert event.action == "shell.run"
    assert event.decision == "REQUEST_APPROVAL"


def test_log_tool_run(db):
    audit = AuditService(db)
    audit.log_tool_run(
        task_id=None, tool_name="filesystem.read", policy_outcome="ALLOW", status="SUCCESS",
        result="file content",
    )
    run = db.query(ToolRun).one()
    assert run.tool_name == "filesystem.read"
    assert run.policy_outcome == "ALLOW"


def test_log_approval(db):
    audit = AuditService(db)
    approval = audit.log_approval(
        task_id=None, action="email.send", reason="send reply", preview={"api_token": "x"}
    )
    assert approval.decision is None
    saved = db.query(Approval).one()
    assert saved.action == "email.send"
    assert saved.preview["api_token"] == "[REDACTED]"


def test_log_task_event_sanitizes_details(db):
    audit = AuditService(db)
    audit.log_task_event(
        task_id=None, event_type="task_created", details={"goal": "hello", "api_key": "leak"}
    )
    event = db.query(AuditEvent).one()
    assert event.details["api_key"] == "[REDACTED]"
    assert event.details["goal"] == "hello"