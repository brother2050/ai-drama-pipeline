"""网络工具 — 端口检测"""
from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)

__all__ = ["port_ok", "redis_port"]


def redis_port() -> int:
    """从 REDIS_URL 环境变量解析端口号，未配置则返回默认 6379"""
    url = os.environ.get("REDIS_URL", "")
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.port:
                return parsed.port
        except (ValueError, TypeError):
            logger.debug(f"REDIS_URL 解析失败: {url}")
    return 6379


def port_ok(port: int, host: str = "127.0.0.1", timeout: float = 2) -> bool:
    """检测端口是否可达"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
