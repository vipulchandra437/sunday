import pytest

from app.services.task_orchestrator import TaskStateMachine, TaskStatus


def test_created_to_completed_happy_path():
    status = TaskStateMachine.transition(TaskStatus.CREATED, "start")
    assert status is TaskStatus.PLANNING
    status = TaskStateMachine.transition(status, "plan_ready")
    assert status is TaskStatus.READY
    status = TaskStateMachine.transition(status, "begin_execution")
    assert status is TaskStatus.EXECUTING
    status = TaskStateMachine.transition(status, "verify_ok")
    assert status is TaskStatus.VERIFYING
    status = TaskStateMachine.transition(status, "verified")
    assert status is TaskStatus.COMPLETED


def test_approval_cycle():
    status = TaskStateMachine.transition(TaskStatus.EXECUTING, "need_approval")
    assert status is TaskStatus.WAITING_FOR_APPROVAL
    status = TaskStateMachine.transition(status, "approval_granted")
    assert status is TaskStatus.EXECUTING


def test_approval_denied_blocks_task():
    status = TaskStateMachine.transition(TaskStatus.WAITING_FOR_APPROVAL, "approval_denied")
    assert status is TaskStatus.BLOCKED


def test_failed_retry_returns_to_ready():
    status = TaskStateMachine.transition(TaskStatus.VERIFYING, "fail")
    assert status is TaskStatus.FAILED
    status = TaskStateMachine.transition(status, "retry")
    assert status is TaskStatus.READY


def test_cancel_anywhere():
    for status in TaskStatus:
        if TaskStateMachine.is_terminal(status):
            continue
        cancelled = TaskStateMachine.transition(status, "cancel")
        assert cancelled is TaskStatus.CANCELLED


def test_invalid_transition_raises():
    with pytest.raises(ValueError):
        TaskStateMachine.transition(TaskStatus.CREATED, "verified")
    with pytest.raises(ValueError):
        TaskStateMachine.transition(TaskStatus.COMPLETED, "begin_execution")


def test_terminal_states():
    assert TaskStateMachine.is_terminal(TaskStatus.COMPLETED)
    assert TaskStateMachine.is_terminal(TaskStatus.CANCELLED)
    assert not TaskStateMachine.is_terminal(TaskStatus.EXECUTING)