"""P5 API 层测试：chat / tools / system / sessions 端点（注入 fake LLM 全链路）。"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.service import AgentService
from src.llm_client.fake import FakeLLMClient
from src.utils.config_loader import load_config

PLAN = (
    '{"steps": [{"action": "calc", "args": {"expression": "(3+5)*2"}, "thought": "算"},'
    '{"action": "respond", "args": {}, "thought": "答"}]}'
)


def make_responder(answer="结果是 16"):
    def responder(messages, kwargs):
        sys_prompt = messages[0].content if messages else ""
        if "任务规划器" in sys_prompt:
            return PLAN
        return answer

    return responder


@pytest.fixture()
def client():
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


# ---------------- chat ----------------
def test_chat_endpoint_ok(client):
    resp = client.post("/api/v1/chat", json={"query": "帮我算 (3+5)*2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"].startswith("sess_")
    assert body["answer"] == "结果是 16"
    assert body["success"] is True
    assert len(body["trace"]) == 2
    assert body["trace"][0]["action"] == "calc"
    assert "16" in body["trace"][0]["observation"]


def test_chat_multi_turn_same_session(client):
    r1 = client.post("/api/v1/chat", json={"query": "第一问"}).json()
    sid = r1["session_id"]
    r2 = client.post("/api/v1/chat", json={"query": "第二问", "session_id": sid}).json()
    assert r2["session_id"] == sid
    # 会话出现在列表中，消息数应为 4（两轮 user/assistant）
    sessions = client.get("/api/v1/sessions").json()
    item = next(s for s in sessions if s["session_id"] == sid)
    assert item["message_count"] == 4


def test_chat_invalid_query_422(client):
    resp = client.post("/api/v1/chat", json={"query": ""})
    assert resp.status_code == 422


# ---------------- tools ----------------
def test_tools_endpoint(client):
    resp = client.get("/api/v1/tools")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    names = {t["name"] for t in tools}
    assert {"calc", "time", "weather", "kb_search"} <= names
    calc = next(t for t in tools if t["name"] == "calc")
    assert "expression" in calc["parameters"]["properties"]


# ---------------- system ----------------
def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "agent_framework"


def test_root_info_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_provider"] == "fake"
    assert body["memory_provider"] == "in_memory"
    assert body["agent_provider"] == "react"
    assert len(body["enabled_tools"]) == 4


# ---------------- sessions ----------------
def test_sessions_list_and_delete(client):
    sid = client.post("/api/v1/chat", json={"query": "x"}).json()["session_id"]
    sessions = client.get("/api/v1/sessions").json()
    assert any(s["session_id"] == sid for s in sessions)

    resp = client.delete(f"/api/v1/sessions/{sid}")
    assert resp.json() == {"deleted": True}
    sessions = client.get("/api/v1/sessions").json()
    assert not any(s["session_id"] == sid for s in sessions)
