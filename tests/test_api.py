import os

os.environ.setdefault("SUPER_WORKSPACES", "/tmp/super-muse-test-studio")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

# Entered once, for the whole module: async runs execute on the client's
# event loop between requests, so the loop must outlive single requests.
import atexit  # noqa: E402

_cm = TestClient(app, raise_server_exceptions=False)
client = _cm.__enter__()
atexit.register(_cm.__exit__, None, None, None)
AUTH = {"Authorization": "Bearer demo:alice"}


def test_health_and_auth():
    assert client.get("/healthz").json()["model"]
    assert client.post("/api/session", json={"user": "alice"}).status_code == 401


def test_root_is_api_not_ui():
    body = client.get("/").json()
    assert body["service"] == "super-muse-api"


def test_cors_allows_the_react_ui_origin():
    r = client.options("/api/session", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def _session():
    r = client.post("/api/session", json={"user": "alice"}, headers=AUTH)
    assert r.status_code == 200
    return r.json()["session_id"]


def _wait_done(run_id, tries=100):
    import time
    for _ in range(tries):
        body = client.get(f"/api/runs/{run_id}", headers=AUTH).json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never finished: {body['status']}")


def test_chat_is_nonblocking_and_completes_with_trace():
    sid = _session()
    out = client.post("/api/chat", json={
        "session_id": sid, "message": "Draft a short note about focus"}, headers=AUTH)
    assert out.status_code == 202
    run_id = out.json()["run_id"]
    body = _wait_done(run_id)
    assert body["status"] == "done"
    result = body["result"]
    assert result["summary"] and result["steps"]
    assert result["steps"][0]["kind"] == "plan"
    assert "run.completed" in result["trace_events"]
    step_events = [e for e in body["events"] if e["type"] == "step"]
    assert step_events and step_events[0]["step"]["kind"] == "plan"


def test_runs_queue_and_queued_run_can_be_cancelled(monkeypatch):
    # Slow the orchestrator down so the queue is observable — with the
    # instant test model both runs could finish before the cancel lands.
    import asyncio as _asyncio

    import api.main as api_main
    from core.schemas import SuperResult

    async def slow_ask(prompt, ctx, emit=None):
        await _asyncio.sleep(1.0)
        return SuperResult(summary="slow", steps=[])

    monkeypatch.setattr(api_main, "ask", slow_ask)
    sid = _session()
    r1 = client.post("/api/chat", json={
        "session_id": sid, "message": "First task"}, headers=AUTH).json()
    r2 = client.post("/api/chat", json={
        "session_id": sid, "message": "Second task"}, headers=AUTH).json()
    assert r1["run_id"] != r2["run_id"]
    cancelled = client.post(f"/api/runs/{r2['run_id']}/cancel", headers=AUTH)
    assert cancelled.status_code == 200
    body2 = _wait_done(r2["run_id"])
    assert body2["status"] == "cancelled" and body2["result"] is None
    assert _wait_done(r1["run_id"])["status"] == "done"


def test_run_events_stream_replays_steps():
    sid = _session()
    run_id = client.post("/api/chat", json={
        "session_id": sid, "message": "Third task"}, headers=AUTH).json()["run_id"]
    _wait_done(run_id)
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=AUTH) as resp:
        text = "".join(resp.iter_text())
    assert '"type": "step"' in text and '"type": "result"' in text
