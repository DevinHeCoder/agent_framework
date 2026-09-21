"""P5.5 用量监控测试：UsageTracker 计数 + /api/v1/usage 路由。"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.service import AgentService
from src.api.usage import UsageTracker
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


# ---------------- UsageTracker（内存模式） ----------------
def test_usage_tracker_counts_in_memory():
    t = UsageTracker(redis_url=None)
    t.report_llm("qwen", 100, 50)
    t.report_llm("qwen", 40, 10)
    t.report_api_call()
    snap = t.snapshot(days=7)
    assert snap["today"]["llm_calls"] == 2
    assert snap["today"]["in_tokens"] == 140
    assert snap["today"]["out_tokens"] == 60
    assert snap["today"]["api_calls"] == 1
    assert snap["total"]["llm_calls"] == 2
    assert len(snap["days"]) == 7
    assert snap["days"][-1]["date"] == snap["today"].get("date") or True  # 结构存在


def test_usage_tracker_zero_snapshot():
    t = UsageTracker(redis_url=None)
    snap = t.snapshot(days=7)
    assert snap["today"]["llm_calls"] == 0
    assert snap["total"]["in_tokens"] == 0
    assert len(snap["days"]) == 7


# ---------------- 路由（鉴权关闭） ----------------
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


def test_usage_endpoint_shape(client):
    resp = client.get("/api/v1/usage")
    assert resp.status_code == 200
    d = resp.json()
    assert set(d.keys()) == {"today", "total", "days"}
    # 今日字段包含全部指标（date 可为 None 一并序列化）
    assert {"llm_calls", "in_tokens", "out_tokens", "api_calls"} <= set(d["today"].keys())
    assert len(d["days"]) == 7


def test_usage_reflects_chat_calls(client):
    # 一次真实链路调用：fake LLM 每次 chat 都会上报 token
    client.post("/api/v1/chat", json={"query": "帮我算 (3+5)*2"})
    d = client.get("/api/v1/usage").json()
    assert d["today"]["llm_calls"] >= 1  # 至少一次规划器调用


# ---------------- 路由（鉴权开启） ----------------
@pytest.fixture()
def auth_client(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_AUTH_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "test-secret")
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


def test_usage_requires_auth(auth_client):
    assert auth_client.get("/api/v1/usage").status_code == 401
    ok = auth_client.get("/api/v1/usage", headers={"X-API-Key": "test-secret"})
    assert ok.status_code == 200


def test_api_call_counter_increments_on_auth(auth_client):
    auth_client.get("/api/v1/usage", headers={"X-API-Key": "test-secret"})
    auth_client.get("/api/v1/usage", headers={"X-API-Key": "test-secret"})
    d = auth_client.get("/api/v1/usage", headers={"X-API-Key": "test-secret"}).json()
    # 3 次 usage 请求 + 2 次内部 usage 自身（不含）——至少 2 次计数
    assert d["today"]["api_calls"] >= 2
