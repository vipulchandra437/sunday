from app.main import app

try:
    from fastapi.testclient import TestClient
except ImportError:
    from starlette.testclient import TestClient


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


def test_root_endpoint():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Sunday AI Agent API"
        assert body["version"] == "0.2.0"


def test_create_and_get_task():
    with TestClient(app) as client:
        create = client.post("/tasks", json={"goal": "build a tower"})
        assert create.status_code == 201
        task = create.json()
        assert task["goal"] == "build a tower"
        assert task["status"] == "CREATED"
        task_id = task["id"]

        get = client.get(f"/tasks/{task_id}")
        assert get.status_code == 200
        assert get.json()["id"] == task_id

        list_resp = client.get("/tasks")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1


def test_transition_task():
    with TestClient(app) as client:
        task = client.post("/tasks", json={"goal": "test"}).json()
        resp = client.post(f"/tasks/{task['id']}/transition", json={"event": "start"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "PLANNING"


def test_cancel_task():
    with TestClient(app) as client:
        task = client.post("/tasks", json={"goal": "cancel me"}).json()
        resp = client.post(f"/tasks/{task['id']}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "CANCELLED"


def test_invalid_transition_returns_400():
    with TestClient(app) as client:
        task = client.post("/tasks", json={"goal": "bad"}).json()
        resp = client.post(
            f"/tasks/{task['id']}/transition", json={"event": "verified"}
        )
        assert resp.status_code == 400


def test_approvals_list_and_decide():
    with TestClient(app) as client:
        approvals = client.get("/approvals").json()
        assert isinstance(approvals, list)
        resp = client.post("/approvals/999999/decide", json={"decision": "approve"})
        assert resp.status_code == 404


def test_audit_events_endpoint():
    with TestClient(app) as client:
        client.post("/tasks", json={"goal": "audit test"})
        resp = client.get("/audit/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert events[0]["event_type"] == "task_created"


# ---------------------------------------------------------------------------
# Tool execution API
# ---------------------------------------------------------------------------

def test_tools_list():
    with TestClient(app) as client:
        resp = client.post("/api/tools/list")
        assert resp.status_code == 200
        body = resp.json()
        names = [t["name"] for t in body["tools"]]
        assert body["count"] == 10
        assert names == [
            "filesystem.list",
            "filesystem.read",
            "filesystem.write",
            "shell.run",
            "git.status",
            "git.diff",
            "git.commit",
            "git.push",
            "code.edit",
            "test.run",
        ]
        by_name = {t["name"]: t for t in body["tools"]}
        assert by_name["shell.run"]["risk_level"] == "MEDIUM"
        assert by_name["filesystem.write"]["supports_dry_run"] is False


def test_tools_check_permission_allowed():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/check-permission",
            json={"tool_name": "filesystem.list", "context": {}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed"] is True
        assert body["requires_approval"] is False


def test_tools_check_permission_requires_approval():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/check-permission",
            json={"tool_name": "shell.run", "context": {}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed"] is False
        assert body["requires_approval"] is True


def test_tools_check_permission_not_found():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/check-permission",
            json={"tool_name": "nope.run", "context": {}},
        )
        assert resp.status_code == 404


def test_tools_execute_allowed_tool(tmp_path, monkeypatch):
    from app.config.settings import config as app_config

    monkeypatch.setattr(app_config, "workspace_paths", [str(tmp_path)])
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")

    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/execute",
            json={"tool_name": "filesystem.list", "input_data": {"path": str(tmp_path)}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["approval_required"] is False
        names = [entry["name"] for entry in body["output"]]
        assert names == ["a.txt"]


def test_tools_execute_requires_approval():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/execute",
            json={
                "tool_name": "filesystem.write",
                "input_data": {"path": "D:\\tmp\\x.txt", "content": "hi"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["approval_required"] is True


def test_tools_execute_unknown_tool():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/execute",
            json={"tool_name": "nope.run", "input_data": {}},
        )
        assert resp.status_code == 404


def test_tools_execute_invalid_input_returns_400():
    with TestClient(app) as client:
        resp = client.post(
            "/api/tools/execute",
            json={"tool_name": "filesystem.list", "input_data": {}},
        )
        assert resp.status_code == 400


def test_tools_approve_placeholder():
    with TestClient(app) as client:
        resp = client.post("/api/tools/approve?approval_id=abc123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Approval recorded"
        assert body["approval_id"] == "abc123"