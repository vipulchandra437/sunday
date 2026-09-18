from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Approval, AuditEvent, Task
from app.services.audit_service import AuditService
from app.services.model_provider import provider_status
from app.services.task_orchestrator import TaskStateMachine, TaskStatus

router = APIRouter()


class TaskCreate(BaseModel):
    goal: str = Field(min_length=1)
    parent_task_id: int | None = None


class TaskOut(BaseModel):
    id: int
    goal: str
    status: str
    parent_task_id: int | None
    current_step: str | None
    result_summary: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskTransition(BaseModel):
    event: str


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|deny)$")


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "providers": provider_status()}


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> Task:
    task = Task(
        goal=payload.goal,
        status=TaskStatus.CREATED.value,
        parent_task_id=payload.parent_task_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    AuditService(db).log_task_event(
        task_id=task.id,
        event_type="task_created",
        details={"goal": payload.goal},
    )
    return task


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = None, db: Session = Depends(get_db)
) -> list[Task]:
    query = select(Task)
    if status:
        query = query.where(Task.status == status.upper())
    return list(db.scalars(query).all())


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/tasks/{task_id}/transition", response_model=TaskOut)
async def transition_task(
    task_id: int, payload: TaskTransition, db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        next_status = TaskStateMachine.transition(task.status, payload.event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task.status = next_status.value
    db.commit()
    db.refresh(task)
    AuditService(db).log_task_event(
        task_id=task.id,
        event_type="task_transition",
        outcome=payload.event,
        details={"to": next_status.value},
    )
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: int, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if not TaskStateMachine.is_terminal(task.status):
        next_status = TaskStateMachine.transition(task.status, "cancel")
        task.status = next_status.value
        db.commit()
        db.refresh(task)
        AuditService(db).log_task_event(
            task_id=task.id,
            event_type="task_cancelled",
            details={"from": next_status.value},
        )
    return task


@router.get("/approvals", response_model=list[dict[str, Any]])
async def list_approvals(
    task_id: int | None = None, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    query = select(Approval)
    if task_id is not None:
        query = query.where(Approval.task_id == task_id)
    return [
        {
            "id": a.id,
            "task_id": a.task_id,
            "action": a.action,
            "reason": a.reason,
            "decision": a.decision,
            "created_at": a.created_at,
        }
        for a in db.scalars(query).all()
    ]


@router.post("/approvals/{approval_id}/decide", response_model=dict[str, Any])
async def decide_approval(
    approval_id: int,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    approval.decision = "APPROVED" if payload.decision == "approve" else "DENIED"
    approval.decision_at = datetime.utcnow()
    db.commit()
    db.refresh(approval)
    AuditService(db).log_approval(
        task_id=approval.task_id,
        action=approval.action,
        reason=approval.reason,
        decision=approval.decision,
    )
    return {
        "id": approval.id,
        "action": approval.action,
        "decision": approval.decision,
    }


@router.get("/audit/events", response_model=list[dict[str, Any]])
async def audit_events(
    limit: int = 50, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 500))
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "task_id": e.task_id,
            "action": e.action,
            "decision": e.decision,
            "outcome": e.outcome,
            "details": e.details,
            "created_at": e.created_at,
        }
        for e in db.scalars(query).all()
    ]