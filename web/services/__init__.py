"""Web 服务层 — 日志配置

提供统一的日志格式和级别配置。
"""
from __future__ import annotations


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """统一日志配置 — 委托给 infra.logging"""
    from infra.logging import setup_logging as _setup
    _setup(level=level, log_file=log_file)
