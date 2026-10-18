"""P0-4 SSRF 防护：外部 URL 校验器。

validate_public_url() 供所有会发起外部请求的工具/模块在请求前调用：
- 仅允许 http/https 协议；
- 拒绝 IP 字面量：环回、内网、链路本地、CGNAT、保留段、云元数据地址；
- 拒绝 localhost / *.localhost / *.local 等特殊主机名；
- 域名主机名做 DNS 解析后复验每个解析 IP（防 DNS rebinding）；
- 支持 SECURITY_BLOCKED_HOSTS 追加黑名单。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Iterable, Optional, Set
from urllib.parse import urlparse

from src.common.exceptions import SecurityError

_CLOUD_METADATA_HOSTS = frozenset({"169.254.169.254", "169.254.170.2"})

# 拒绝的地址段（IPv4 + IPv6）
_BLOCKED_NETWORKS: tuple = tuple(
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8",        # "本网络"
        "10.0.0.0/8",       # 私网
        "100.64.0.0/10",    # CGNAT
        "127.0.0.0/8",      # 环回
        "169.254.0.0/16",   # 链路本地（含云元数据）
        "172.16.0.0/12",    # 私网
        "192.0.0.0/24",     # IETF 保留
        "192.168.0.0/16",   # 私网
        "198.18.0.0/15",    # 基准测试
        "::1/128",          # IPv6 环回
        "fc00::/7",         # IPv6 ULA（私网）
        "fe80::/10",        # IPv6 链路本地
    )
)


def _check_ip(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        raise SecurityError(f"拒绝访问内网/保留地址: {ip_str}")
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            raise SecurityError(f"拒绝访问内网/保留地址: {ip_str}")


def validate_public_url(
    url: str,
    blocked_hosts: Optional[Iterable[str]] = None,
) -> str:
    """校验 URL 是否指向公网可访问地址；通过则原样返回，失败抛 SecurityError。

    Args:
        url: 待校验的完整 URL。
        blocked_hosts: 追加黑名单（主机名，小写匹配）。

    Raises:
        SecurityError: 协议非法 / 地址为内网或保留 / 解析失败或解析到内网。
    """
    if not url:
        raise SecurityError("URL 为空")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError(f"仅允许 http/https 协议: {url}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SecurityError(f"URL 缺少主机名: {url}")

    # 黑名单（含云元数据）
    blacklist = set(_CLOUD_METADATA_HOSTS)
    if blocked_hosts:
        blacklist.update(h.lower().strip() for h in blocked_hosts if h and h.strip())
    if host in blacklist:
        raise SecurityError(f"拒绝访问黑名单主机: {host}")

    # 特殊主机名：localhost / *.localhost / *.local
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise SecurityError(f"拒绝访问本地主机名: {host}")

    # 字面量 IP：直接校验
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        _check_ip(host)
        return url

    # 域名：DNS 解析后复验全部解析结果（防 DNS rebinding）
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise SecurityError(f"域名解析失败: {host}") from None
    resolved: Set[str] = set()
    for info in infos:
        ip_str = info[4][0]
        resolved.add(ip_str)
        _check_ip(ip_str)
    if not resolved:
        raise SecurityError(f"域名无有效解析结果: {host}")
    return url
