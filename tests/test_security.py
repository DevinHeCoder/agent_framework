"""P0-4 安全加固测试：SSRF 校验器 / CORS 白名单 / 安全响应头 / 请求体限制。"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.service import AgentService
from src.common.exceptions import SecurityError
from src.common.net import validate_public_url
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
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    llm = FakeLLMClient(responder=make_responder())
    service = AgentService.build_from_config(cfg, llm=llm)
    app = create_app(config=cfg, service=service)
    return TestClient(app)


# ---------------- SSRF 校验器 ----------------
def test_ssrf_rejects_cloud_metadata():
    with pytest.raises(SecurityError):
        validate_public_url("http://169.254.169.254/latest/meta-data/")


def test_ssrf_rejects_loopback():
    with pytest.raises(SecurityError):
        validate_public_url("http://127.0.0.1/")
    with pytest.raises(SecurityError):
        validate_public_url("http://localhost/admin")


def test_ssrf_rejects_private_ip():
    with pytest.raises(SecurityError):
        validate_public_url("http://192.168.1.1/")
    with pytest.raises(SecurityError):
        validate_public_url("http://10.0.0.8/")


def test_ssrf_rejects_link_local_and_ipv6_loopback():
    with pytest.raises(SecurityError):
        validate_public_url("http://169.254.5.5/")
    with pytest.raises(SecurityError):
        validate_public_url("http://[::1]/")


def test_ssrf_rejects_non_http_protocol():
    with pytest.raises(SecurityError):
        validate_public_url("ftp://example.com/file")


def test_ssrf_rejects_blocked_host(monkeypatch):
    """黑名单追加：域名主机名在 blocked_hosts 中直接拒绝（无需 DNS）。"""
    with pytest.raises(SecurityError):
        validate_public_url("http://evil.internal/x", blocked_hosts=["evil.internal"])


def test_ssrf_allows_public_ip_literal():
    """公网 IP 字面量放行（不触发 DNS）。"""
    assert validate_public_url("http://8.8.8.8/") == "http://8.8.8.8/"


def test_ssrf_allows_public_domain(monkeypatch):
    """公网域名：mock DNS 解析到公网 IP 后放行；解析到内网 IP 拒绝。"""
    import src.common.net as net

    monkeypatch.setattr(
        net.socket, "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert validate_public_url("https://example.com/path") == "https://example.com/path"

    # DNS rebinding：解析结果回到内网 → 拒绝
    monkeypatch.setattr(
        net.socket, "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("10.0.0.1", 0))],
    )
    with pytest.raises(SecurityError):
        validate_public_url("https://example.com/")


def test_ssrf_rejects_unresolvable_domain(monkeypatch):
    import socket as _socket

    import src.common.net as net

    monkeypatch.setattr(net.socket, "getaddrinfo", _socket.getaddrinfo)
    # 无法解析的域名：拒绝
    monkeypatch.setattr(
        net.socket, "getaddrinfo",
        lambda host, port: (_ for _ in ()).throw(OSError("nxdomain")),
    )
    with pytest.raises(SecurityError):
        validate_public_url("https://no-such-host-abc123.invalid/")


# ---------------- 安全响应头 ----------------
def test_security_headers_present(client):
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]


def test_security_headers_on_error_response(client):
    """异常 500 响应同样带安全头（中间件统一注入）。"""
    resp = client.get("/healthz")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


# ---------------- CORS ----------------
def test_cors_disabled_by_default(client):
    """未配置白名单：跨域来源不带 ACAO 头。"""
    resp = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers


def test_cors_whitelist_blocks_other_origin(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_SECURITY_CORS_ORIGINS", "https://app.example.com")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)

    resp = c.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers

    resp = c.get("/health", headers={"Origin": "https://app.example.com"})
    assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"


# ---------------- 请求体限制 ----------------
def test_body_limit_rejects_oversized(monkeypatch):
    """Content-Length 超过 1MB → 413（含 request_id）。"""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    cfg = load_config()
    service = AgentService.build_from_config(cfg, llm=FakeLLMClient(responder=make_responder()))
    app = create_app(config=cfg, service=service)
    c = TestClient(app)

    big = "x" * (1024 * 1024 + 100)  # 1MB + 100B
    resp = c.post("/api/v1/chat", content=big)
    assert resp.status_code == 413
    body = resp.json()
    assert body["code"] == "PayloadTooLarge"
    assert body["request_id"]


def test_body_limit_allows_normal_request(client):
    resp = client.post("/api/v1/chat", json={"query": "帮我算 (3+5)*2"})
    assert resp.status_code == 200
