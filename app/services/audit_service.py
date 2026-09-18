from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import Approval, AuditEvent, ToolRun

logger = logging.getLogger("sunday.audit")

SECRET_KEY_HINTS = (
    "api",
    "token",
    "secret",
    "password",
    "passwd",
    "key",
    "authorization",
    "auth",
    "credential",
    "private",
    "cookie",
    "session_id",
)

REDACTED = "[REDACTED]"


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def sanitize(data: Any) -> Any:
        if isinstance(data, dict):
            return {
                str(k): REDACTED
                if any(hint in str(k).lower() for hint in SECRET_KEY_HINTS)
                else AuditService.sanitize(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [AuditService.sanitize(item) for item in data]
        if isinstance(data, str):
            return data[:2000]
        return data

    def log_permission_eval(
        self,
        *,
        task_id: int | None,
        tool_name: str,
        decision: str,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type="permission_eval",
            task_id=task_id,
            action=tool_name,
            decision=decision,
            details=self.sanitize({"reason": reason, "context": context}),
        )
        self.db.add(event)
        self.db.commit()
        logger.info("permission_eval tool=%s decision=%s task_id=%s", tool_name, decision, task_id)

    def log_task_event(
        self,
        *,
        task_id: int | None,
        event_type: str,
        outcome: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            task_id=task_id,
            outcome=outcome,
            details=self.sanitize(details),
        )
        self.db.add(event)
        self.db.commit()
        logger.info("task_event type=%s task_id=%s outcome=%s", event_type, task_id, outcome)

    def log_tool_run(
        self,
        *,
        task_id: int | None,
        tool_name: str,
        policy_outcome: str,
        status: str | None = None,
        result: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> None:
        run = ToolRun(
            task_id=task_id,
            tool_name=tool_name,
            policy_outcome=policy_outcome,
            status=status,
            start_time=start_time,
            end_time=end_time,
            result=result[:2000] if result else None,
        )
        self.db.add(run)
        self.db.commit()
        logger.info(
            "tool_run tool=%s policy=%s status=%s task_id=%s",
            tool_name,
            policy_outcome,
            status,
            task_id,
        )

    def log_approval(
        self,
        *,
        task_id: int | None,
        action: str,
        reason: str | None = None,
        decision: str | None = None,
        preview: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> Approval:
        approval = Approval(
            task_id=task_id,
            action=action,
            reason=reason,
            decision=decision,
            decision_at=datetime.utcnow() if decision else None,
            expires_at=expires_at,
            preview=self.sanitize(preview),
        )
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        logger.info(
            "approval action=%s decision=%s task_id=%s",
            action,
            decision,
            task_id,
        )
        return approval