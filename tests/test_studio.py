import os

os.environ.setdefault("SUPER_WORKSPACES", "/tmp/super-muse-test-studio")

from fastapi.testclient import TestClient  # noqa: E402

from studio.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
AUTH = {"Authorization": "Bearer demo:alice"}


def test_health_and_auth():
    assert client.get("/healthz").json()["model"]
    assert client.post("/api/session", json={"user": "alice"}).status_code == 401


def test_chat_flow_shows_trace():
    r = client.post("/api/session", json={"user": "alice"}, headers=AUTH)
    assert r.status_code == 200
    sid = r.json()["session_id"]
    out = client.post("/api/chat", json={
        "session_id": sid, "message": "Draft a short note about focus"}, headers=AUTH)
    assert out.status_code == 200
    body = out.json()
    assert body["summary"] and body["steps"]
    assert body["steps"][0]["kind"] == "plan"
    assert "run.completed" in body["trace_events"]
