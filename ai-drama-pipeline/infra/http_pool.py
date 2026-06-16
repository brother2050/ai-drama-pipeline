"""共享 HTTP 连接池 — 全后端复用 httpx.Client

按 base_url + timeout 组合缓存 Client 实例，进程退出时统一关闭。
同时提供 auth_headers() 等通用 HTTP 工具函数。
"""
from __future__ import annotations

import logging
import threading

import httpx

logger = logging.getLogger(__name__)

__all__ = ["get_client", "get_fast_client", "shutdown_all", "auth_headers"]


def auth_headers(api_key: str = "", content_type: str = "application/json",
                 api_key_header: str = "Authorization") -> dict:
    """构建带 API Key 的请求头

    Args:
        api_key: API Key（为空时不添加认证头）
        content_type: Content-Type 值（为空时不添加）
        api_key_header: API Key 的 header 名（默认 "Authorization"，MiMo 用 "api-key"）

    Returns:
        请求头字典
    """
    h: dict[str, str] = {}
    if content_type:
        h["Content-Type"] = content_type
    if api_key:
        if api_key_header == "Authorization":
            h["Authorization"] = f"Bearer {api_key}"
        else:
            h[api_key_header] = api_key
    return h

_clients: dict[tuple[str, float], httpx.Client] = {}
_lock = threading.Lock()

_DEFAULT_TIMEOUT = 60.0
_FAST_TIMEOUT = 5.0


def _normalize_base_url(url: str | None) -> str:
    """统一 base_url：None/空 → ''，去尾斜杠"""
    return (url or "").rstrip("/")


def get_client(base_url: str | None = "", *, timeout: float = _DEFAULT_TIMEOUT) -> httpx.Client:
    """获取或创建共享 httpx.Client。base_url 为 None 或空字符串时等效。

    特性：
    - 自动复用已有连接（连接池机制）
    - 连接关闭后自动重建（支持配置热重载）
    """
    key = (_normalize_base_url(base_url), timeout)

    # 快速路径：检查缓存中是否有可用连接
    client = _clients.get(key)
    if client is not None and not client.is_closed:
        return client

    with _lock:
        # 双重检查：锁内再次确认
        client = _clients.get(key)
        if client is not None and not client.is_closed:
            return client

        # 创建新客户端（覆盖已关闭的连接或首次创建）
        kwargs: dict = {
            "timeout": httpx.Timeout(timeout, connect=10),
            "follow_redirects": True,
            "limits": httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
        }
        normalized = _normalize_base_url(base_url)
        if normalized:
            kwargs["base_url"] = normalized
        client = httpx.Client(**kwargs)
        _clients[key] = client
        logger.debug(f"HTTP 连接池创建: base_url={normalized!r}, timeout={timeout}")
        return client


def get_fast_client(base_url: str | None = "") -> httpx.Client:
    """获取快速检查用 Client（5s 超时）"""
    return get_client(base_url, timeout=_FAST_TIMEOUT)


def shutdown_all() -> None:
    """关闭所有共享 Client"""
    with _lock:
        for client in _clients.values():
            try:
                client.close()
            except Exception:
                logger.debug("HTTP 客户端关闭失败")
        _clients.clear()


# 注册清理钩子：进程退出时自动关闭 HTTP 连接池
try:
    from infra.hooks import on_cleanup
    on_cleanup(priority=50)(shutdown_all)
except ImportError:
    pass
