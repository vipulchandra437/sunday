from __future__ import annotations

import enum
import sqlite3
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config.settings import settings

try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    SQLITE_CHECKPOINTER_AVAILABLE = True
except ImportError:
    SqliteSaver = None  # type: ignore[assignment,misc]
    SQLITE_CHECKPOINTER_AVAILABLE = False

from langgraph.checkpoint.memory import MemorySaver  # always available


class TaskStatus(str, enum.Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStateMachine:
    TRANSITIONS: dict[TaskStatus, dict[str, TaskStatus]] = {
        TaskStatus.CREATED: {"start": TaskStatus.PLANNING, "cancel": TaskStatus.CANCELLED},
        TaskStatus.PLANNING: {
            "plan_ready": TaskStatus.READY,
            "fail": TaskStatus.FAILED,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.READY: {
            "begin_execution": TaskStatus.EXECUTING,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.EXECUTING: {
            "need_approval": TaskStatus.WAITING_FOR_APPROVAL,
            "verify_ok": TaskStatus.VERIFYING,
            "fail": TaskStatus.FAILED,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.VERIFYING: {
            "verified": TaskStatus.COMPLETED,
            "fail": TaskStatus.FAILED,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.WAITING_FOR_APPROVAL: {
            "approval_granted": TaskStatus.EXECUTING,
            "approval_denied": TaskStatus.BLOCKED,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {
            "retry": TaskStatus.EXECUTING,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.FAILED: {
            "retry": TaskStatus.READY,
            "cancel": TaskStatus.CANCELLED,
        },
        TaskStatus.COMPLETED: {},
        TaskStatus.CANCELLED: {},
    }

    @classmethod
    def transition(cls, current: TaskStatus | str, event: str) -> TaskStatus:
        current_status = current if isinstance(current, TaskStatus) else TaskStatus(current)
        next_status = cls.TRANSITIONS[current_status].get(event)
        if next_status is None:
            raise ValueError(f"invalid transition: {current_status} --{event}--> ?")
        return next_status

    @classmethod
    def is_terminal(cls, status: TaskStatus | str) -> bool:
        status = status if isinstance(status, TaskStatus) else TaskStatus(status)
        return status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)


class TaskState(TypedDict, total=False):
    task_id: int | None
    goal: str
    status: str
    steps: list[dict[str, Any]]
    current_step_index: int
    pending_approval: bool
    result_summary: str | None
    error: str | None


def _plan_node(state: TaskState) -> dict[str, Any]:
    steps = state.get("steps") or [
        {"step": 1, "action": "decompose_goal", "tool_calls": [], "status": "PLANNED"}
    ]
    return {"status": TaskStatus.READY.value, "steps": steps, "current_step_index": 0}


def _execute_node(state: TaskState) -> dict[str, Any]:
    if state.get("pending_approval"):
        return {"status": TaskStatus.WAITING_FOR_APPROVAL.value}
    return {"status": TaskStatus.VERIFYING.value}


def _verify_node(state: TaskState) -> dict[str, Any]:
    return {
        "status": TaskStatus.COMPLETED.value,
        "result_summary": "Phase 1 skeleton: no tools registered, nothing executed",
    }


def _needs_cancel(state: TaskState) -> bool:
    return state.get("status") in (
        TaskStatus.CANCELLED.value,
        TaskStatus.FAILED.value,
    )


def get_checkpointer():
    if SQLITE_CHECKPOINTER_AVAILABLE and SqliteSaver is not None:
        checkpoint_path = settings.langgraph_checkpoint_path or "checkpoints.sqlite3"
        conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        return saver
    return MemorySaver()


def build_sunday_graph(checkpointer=None):
    graph = StateGraph(TaskState)

    graph.add_node("plan", _plan_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("verify", _verify_node)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        lambda state: "cancel" if _needs_cancel(state) else "execute",
        {"execute": "execute", "cancel": END},
    )
    graph.add_conditional_edges(
        "execute",
        lambda state: "end" if state.get("status") == TaskStatus.WAITING_FOR_APPROVAL.value else "verify",
        {"verify": "verify", "end": END},
    )
    graph.add_edge("verify", END)

    return graph.compile(checkpointer=checkpointer or get_checkpointer())