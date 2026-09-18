from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Approval, AuditEvent, Task
from app.core.security import PermissionEngine, PolicyDecision
from app.services.audit_service import AuditService
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


# ---------------------------------------------------------------------------
# Tool execution API (Phase 2, Part 6)
# ---------------------------------------------------------------------------
tools_router = APIRouter(prefix="/api", tags=["tools"])

_permission_engine = PermissionEngine()


def _policy_decision(
    tool_name: str, context: dict[str, Any] | None = None
) -> PolicyDecision:
    return _permission_engine.evaluate(tool_name, context)


class ToolExecutionRequest(BaseModel):
    tool_name: str
    input_data: dict[str, Any]


class ToolExecutionResponse(BaseModel):
    success: bool
    output: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = False


class ToolListResponse(BaseModel):
    tools: list[dict[str, Any]]
    count: int


class PermissionCheckRequest(BaseModel):
    tool_name: str
    context: dict[str, Any] = Field(default_factory=dict)


class PermissionCheckResponse(BaseModel):
    tool_name: str
    allowed: bool
    requires_approval: bool
    reason: str


# Tool execution state (simple in-memory for now)
pending_approvals: dict[str, dict] = {}


@tools_router.post("/tools/list", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """List all available tools with metadata."""
    from app.services.tools import TOOLS

    tools = [
        {
            "name": tool.name,
            "purpose": tool.purpose,
            "risk_level": tool.risk_level,
            "supports_dry_run": tool.supports_dry_run,
        }
        for tool in TOOLS
    ]

    return ToolListResponse(tools=tools, count=len(tools))


@tools_router.post("/tools/check-permission", response_model=PermissionCheckResponse)
async def check_permission(
    request: PermissionCheckRequest,
) -> PermissionCheckResponse:
    """Check if a tool is allowed, denied, or requires approval."""
    from app.services.tools import TOOLS

    tool_exists = any(t.name == request.tool_name for t in TOOLS)
    if not tool_exists:
        raise HTTPException(status_code=404, detail=f"Tool '{request.tool_name}' not found")

    decision = _policy_decision(request.tool_name, request.context)

    return PermissionCheckResponse(
        tool_name=request.tool_name,
        allowed=decision is PolicyDecision.ALLOW,
        requires_approval=decision is PolicyDecision.REQUEST_APPROVAL,
        reason=f"Policy: {decision.value}",
    )


@tools_router.post("/tools/execute", response_model=ToolExecutionResponse)
async def execute_tool(request: ToolExecutionRequest) -> ToolExecutionResponse:
    """Execute a tool after checking permissions."""
    from app.services.tools import TOOLS

    tool = next((t for t in TOOLS if t.name == request.tool_name), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{request.tool_name}' not found")

    try:
        tool.validate_input(request.input_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid input: {exc}") from exc

    decision = _policy_decision(request.tool_name)

    if decision is PolicyDecision.DENY:
        raise HTTPException(status_code=403, detail=f"Tool '{request.tool_name}' is denied by policy")

    if decision is PolicyDecision.BLOCK:
        raise HTTPException(status_code=403, detail=f"Tool '{request.tool_name}' is permanently blocked")

    if decision is PolicyDecision.REQUEST_APPROVAL:
        return ToolExecutionResponse(
            success=False,
            output=None,
            error=f"Approval required for tool '{request.tool_name}'",
            metadata={
                "approval_required": True,
                "tool_name": request.tool_name,
            },
            approval_required=True,
        )

    result = await tool.execute(request.input_data)
    return ToolExecutionResponse(
        success=result.success,
        output=result.output,
        error=result.error,
        metadata=result.metadata or {},
    )


@tools_router.post("/tools/approve")
async def submit_approval(approval_id: str) -> dict[str, Any]:
    """Submit approval for a pending action (placeholder for approval UI integration)."""
    # This is a placeholder - in real implementation, would validate approval token
    # and allow the original request to proceed
    return {"message": "Approval recorded", "approval_id": approval_id}