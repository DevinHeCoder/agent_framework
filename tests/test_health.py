"""P0-1 可观测性测试：healthz / readyz / 全局异常兜底 / request_id / 结构化日志。"""
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from src.api.main import create_app
from src.api.service import AgentService
from src.common.exceptions import LLMError
from src.llm_client.fake import FakeLLMClient
from src.utils.config_loader import load_config
from src.utils.logger import ContextFilter, JsonFormatter, request_id_var

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


def _add_route_first(app: FastAPI, path: str, endpoint) -> None:
    """把测试用路由插到 routes 头部（StaticFiles mount('/') 之前），避免被兜底 404。"""
    app.router.routes.insert(0, Route(path, endpoint))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


# ---------------- 健康探针 ----------------
def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok_in_memory(client):
    """in_memory 模式：redis 未启用视为就绪。"""
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["config"]["ok"] is True
    assert body["checks"]["llm"]["ok"] is True
    assert body["checks"]["redis"]["note"] == "not_used"


def test_readyz_503_when_redis_down(monkeypatch):
    """redis/hybrid 模式且 Redis 不可达：就绪探针返回 503 且不抛异常。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MEMORY_PROVIDER", "hybrid")
    monkeypatch.setenv("AGENT_REDIS_URL", "redis://127.0.0.1:6399/0")  # 必然不可达
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)
    resp = c.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"]["ok"] is False


# ---------------- 全局异常兜底 ----------------
def test_unhandled_exception_returns_request_id(monkeypatch):
    """未捕获异常 → 500 JSON 含 code/message/request_id。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)

    async def boom(request):
        raise ValueError("boom")

    _add_route_first(app, "/_boom", boom)
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/_boom", headers={"X-Request-Id": "test-rid-123"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "InternalError"
    assert body["message"] == "服务器内部错误"
    assert body["request_id"] == "test-rid-123"


def test_framework_error_maps_to_code(monkeypatch):
    """框架异常（LLMError 等）→ 500 且 code 为异常类名。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)

    async def boom2(request):
        raise LLMError("LLM 调用失败")

    _add_route_first(app, "/_boom2", boom2)
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/_boom2")
    assert resp.status_code == 500
    assert resp.json()["code"] == "LLMError"
    assert resp.json()["message"] == "LLM 调用失败"
    assert resp.json()["request_id"]


def test_validation_error_keeps_422(client):
    """FastAPI 自带 422 校验不被兜底 handler 覆盖。"""
    resp = client.post("/api/v1/chat", json={"query": ""})
    assert resp.status_code == 422


def test_request_id_generated_and_echoed(client):
    """未传 X-Request-Id 时自动生成并回写响应头。"""
    resp = client.get("/healthz")
    rid = resp.headers.get("X-Request-Id")
    assert rid and len(rid) >= 8


# ---------------- 结构化日志 ----------------
def test_json_formatter_output():
    """JsonFormatter：合法 JSON 行 + 包含结构化字段 + 脱敏生效。"""
    fmt = JsonFormatter()
    record = logging.LogRecord(
        "agent_framework.agent", logging.INFO, "react_agent.py", 1,
        "tool_step action=calc", None, None,
    )
    record.session_id = "sess_abc"
    record.duration_ms = 12.3
    out = fmt.format(record)
    obj = json.loads(out)
    assert obj["msg"] == "tool_step action=calc"
    assert obj["session_id"] == "sess_abc"
    assert obj["duration_ms"] == 12.3
    assert obj["request_id"] == "-"


def test_json_formatter_redacts_secret():
    fmt = JsonFormatter()
    record = logging.LogRecord(
        "agent_framework.llm", logging.ERROR, "client.py", 1,
        "key=sk-abcdefghijklmn123456", None, None,
    )
    out = fmt.format(record)
    assert "sk-abcdefghijklmn123456" not in out
    assert "sk-***" in out


def test_context_filter_injects_request_id():
    filt = ContextFilter()
    record = logging.LogRecord("t", logging.INFO, "f", 1, "msg", None, None)
    token = request_id_var.set("rid-abc123")
    try:
        assert filt.filter(record) is True
        assert record.request_id == "rid-abc123"
    finally:
        request_id_var.reset(token)


def test_context_filter_default_dash():
    filt = ContextFilter()
    record = logging.LogRecord("t", logging.INFO, "f", 1, "msg", None, None)
    token = request_id_var.set("-")
    try:
        filt.filter(record)
        assert record.request_id == "-"
    finally:
        request_id_var.reset(token)
