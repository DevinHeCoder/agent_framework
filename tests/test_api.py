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
def client(monkeypatch):
    # 隔离外部 .env：显式置 fake（load_dotenv 不会覆盖已存在的环境变量）
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


@pytest.fixture()
def auth_client(monkeypatch):
    """开启鉴权的客户端：token=test-secret，限流 60/min。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "test-secret")
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
    resp = client.get("/api/v1/system")
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


# ---------------- session messages ----------------
def test_session_messages_after_chat(client):
    sid = client.post("/api/v1/chat", json={"query": "帮我算 (3+5)*2"}).json()["session_id"]
    resp = client.get(f"/api/v1/sessions/{sid}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][0]["content"] == "帮我算 (3+5)*2"
    assert "16" in body["messages"][1]["content"]


def test_session_messages_multi_turn(client):
    sid = client.post("/api/v1/chat", json={"query": "第一问"}).json()["session_id"]
    client.post("/api/v1/chat", json={"query": "第二问", "session_id": sid})
    body = client.get(f"/api/v1/sessions/{sid}/messages").json()
    assert [m["role"] for m in body["messages"]] == [
        "user", "assistant", "user", "assistant"
    ]
    assert body["messages"][2]["content"] == "第二问"


def test_session_messages_empty_for_unknown(client):
    resp = client.get("/api/v1/sessions/sess_unknown/messages")
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


# ---------------- api auth ----------------
def test_auth_disabled_public_endpoints(client):
    """鉴权关闭（默认）：health/system 无需 Key。"""
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/system").status_code == 200
    assert client.get("/api/v1/system").json()["auth_required"] is False


def test_system_branding_defaults(client):
    """白标默认值：system 返回品牌信息。"""
    b = client.get("/api/v1/system").json()["branding"]
    assert b["logo_text"] == "AGENT"
    assert b["primary_color"] == "#4F8CFF"
    assert b["agent_label"] == "AGENT"


def test_system_branding_env_override(monkeypatch):
    """白标可被 .env 覆盖：AGENT_BRAND_* 注入后 system 返回新品牌。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_BRAND_LOGO_TEXT", "Nova")
    monkeypatch.setenv("AGENT_BRAND_APP_NAME", "Nova 智能体平台")
    monkeypatch.setenv("AGENT_BRAND_PRIMARY_COLOR", "#10B981")
    monkeypatch.setenv("AGENT_BRAND_AGENT_LABEL", "NOVA")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)
    b = c.get("/api/v1/system").json()["branding"]
    assert b["logo_text"] == "Nova"
    assert b["app_name"] == "Nova 智能体平台"
    assert b["primary_color"] == "#10B981"
    assert b["agent_label"] == "NOVA"


def test_auth_disabled_api_works_without_key(client):
    resp = client.post("/api/v1/chat", json={"query": "x"})
    assert resp.status_code == 200


def test_auth_enabled_rejects_without_key(auth_client):
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/api/v1/system").json()["auth_required"] is True
    assert auth_client.get("/api/v1/sessions").status_code == 401
    assert auth_client.post("/api/v1/chat", json={"query": "x"}).status_code == 401


def test_auth_enabled_rejects_wrong_key(auth_client):
    headers = {"X-API-Key": "wrong-key"}
    assert auth_client.get("/api/v1/sessions", headers=headers).status_code == 401
    assert auth_client.post(
        "/api/v1/chat", json={"query": "x"}, headers=headers
    ).status_code == 401


def test_auth_enabled_accepts_valid_key(auth_client):
    headers = {"X-API-Key": "test-secret"}
    resp = auth_client.get("/api/v1/sessions", headers=headers)
    assert resp.status_code == 200
    resp = auth_client.post("/api/v1/chat", json={"query": "x"}, headers=headers)
    assert resp.status_code == 200


def test_auth_bearer_header_supported(auth_client):
    resp = auth_client.get(
        "/api/v1/sessions", headers={"Authorization": "Bearer test-secret"}
    )
    assert resp.status_code == 200


def test_auth_enabled_no_token_configured(monkeypatch):
    """开启鉴权但未配置 token：防御性拒绝一切请求。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_AUTH_ENABLED", "true")
    monkeypatch.delenv("AGENT_AUTH_TOKEN", raising=False)
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)
    assert c.get("/api/v1/sessions").status_code == 401
    assert c.get("/health").status_code == 200


def test_auth_rate_limit(monkeypatch):
    """限流：同一 Key 每分钟最多 2 次，第 3 次 429。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "k")
    monkeypatch.setenv("AGENT_AUTH_RATE_LIMIT", "2")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)
    h = {"X-API-Key": "k"}
    assert c.get("/api/v1/sessions", headers=h).status_code == 200
    assert c.get("/api/v1/sessions", headers=h).status_code == 200
    assert c.get("/api/v1/sessions", headers=h).status_code == 429
    # 不同 Key 不受影响（限流按 Key 隔离）
    assert c.get("/api/v1/sessions", headers={"X-API-Key": "other"}).status_code == 401
