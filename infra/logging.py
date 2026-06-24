"""统一结构化日志模块 — JSON 格式 + 文件轮转

替代分散在各文件中的 logging.basicConfig 调用，
提供统一的日志配置入口。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            log_data["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """统一日志配置（带轮转）

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_file: 日志文件路径（None 时仅输出到控制台）
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # 控制台：人类可读格式
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root.addHandler(console)

    # 文件：JSON 格式 + 10MB 轮转，保留 5 份
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
