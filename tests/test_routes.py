from app.main import app

try:
    from fastapi.testclient import TestClient
except ImportError:
    from starlette.testclient import TestClient


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "providers" in body


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