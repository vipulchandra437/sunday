import pytest

from app.services.task_orchestrator import (
    TaskStatus,
    build_sunday_graph,
    get_checkpointer,
)

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    MemorySaver = None


def test_graph_builds():
    graph = build_sunday_graph(checkpointer=MemorySaver()) if MemorySaver else None
    if graph is None:
        pytest.skip("langgraph not installed")
    assert graph is not None


def test_graph_happy_path_and_checkpoint():
    graph = build_sunday_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "test-1"}}
    result = graph.invoke(
        {"goal": "write a summary", "status": TaskStatus.CREATED.value},
        config=config,
    )
    assert result["status"] == TaskStatus.COMPLETED.value

    checkpointed = graph.get_state(config)
    assert checkpointed is not None
    assert checkpointed.values["goal"] == "write a summary"
    assert checkpointed.values["status"] == TaskStatus.COMPLETED.value


def test_checkpointer_factory_returns_something():
    checkpointer = get_checkpointer()
    assert checkpointer is not None