"""LLM 后端 Mixin — 提供 HTTP 重试、错误学习、配置解析等通用能力

Mixin 遵循"窄接口"原则，每个 Mixin 只负责一个单一职责：
- HttpRetryMixin: 客户端存活检查 & 自动重建
- ErrorLearningMixin: 从 API 错误中学习模型限制
- ConfigMixin: 通用配置参数解析（base_url / model / timeout / ctx / temperature / top_p / stream）
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from infra.http_pool import get_client

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

__all__ = ["HttpRetryMixin", "ErrorLearningMixin", "ConfigMixin"]


# ═══════════════════════════════════════════════════════════
#  HttpRetryMixin — HTTP 客户端自动恢复
# ═══════════════════════════════════════════════════════════

class HttpRetryMixin:
    """HTTP 客户端存活检查 & 自动重建。

    使用方式：
        class MyLLM(HttpRetryMixin, BaseLLM):
            self._client = get_client(timeout=self._timeout)
            self._fast_client = get_client(timeout=5)
            ...
            self._client = self._ensure_client(self._client, self._timeout)
    """

    @staticmethod
    def _ensure_client(client: "httpx.Client", timeout: float) -> "httpx.Client":
        """检查 httpx.Client 是否可用，已关闭则从连接池获取新实例"""
        if client.is_closed:
            logger.warning("HTTP 客户端已关闭，自动重建")
            return get_client(timeout=timeout)
        return client


# ═══════════════════════════════════════════════════════════
#  ErrorLearningMixin — 错误驱动的模型限制发现
# ═══════════════════════════════════════════════════════════

class ErrorLearningMixin:
    """从 API 错误中学习模型限制。

    使用方式：
        def chat(self, ...):
            try:
                ...
            except Exception as e:
                self._try_learn_limits(self._model, e)
                raise
    """

    @staticmethod
    def _try_learn_limits(model: str, error: Exception) -> None:
        """从 API 错误中学习模型限制（静默，不影响正常错误处理）"""
        try:
            from infra.config.registry import ModelRegistry
            limits = ModelRegistry.parse_limits_from_error(str(error))
            if limits:
                ModelRegistry.cache_discovered_limits(model, limits)
                logger.info(f"从错误中学习到 {model} 限制: {limits}")
        except Exception:
            logger.debug(f"学习模型限制跳过: {model}")


# ═══════════════════════════════════════════════════════════
#  ConfigMixin — 通用配置解析
# ═══════════════════════════════════════════════════════════

class ConfigMixin:
    """LLM 后端通用配置解析 Mixin。

    子类 __init__ 调用 self._init_llm_config(config) 即可完成通用配置解析，
    之后可以追加自身专有配置（如 api_key / top_k 等）。

    解析的字段:
        - _url: API 地址（来自 base_url）
        - _model: 模型名
        - _timeout: 请求超时（来自 timeouts.llm）
        - _ctx: 配置指定的上下文窗口（0=自动探测）
        - _temperature: 默认温度参数
        - _top_p: 默认 top_p 参数
        - _stream: 默认流式开关
        - _client / _fast_client: httpx 客户端实例
    """

    def _init_llm_config(self, config: dict) -> None:
        """从 config dict 解析通用参数。子类 __init__ 中调用。"""
        self._url = config.get("base_url", "")
        self._model = config.get("model", "")
        self._timeout = config.get("timeouts", {}).get("llm", 300)
        self._ctx = config.get("context_length", 0)
        self._temperature = config.get("temperature")
        self._top_p = config.get("top_p")
        self._stream = config.get("stream", False)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=5)

    def _resolve_options(self, kwargs: dict, *, extra_fields: dict | None = None) -> dict:
        """将 kwargs 覆盖默认温度/top_p，组装为请求参数。

        Args:
            kwargs: 调用方传入的覆盖参数（temperature, top_p 等）
            extra_fields: 额外的固定字段（如 Ollama 的 num_predict / top_k）

        Returns:
            合并后的参数字典（temperature/top_p 有值才加入）
        """
        result: dict = {}
        if extra_fields:
            result.update(extra_fields)
        temp = kwargs.get("temperature", self._temperature)
        if temp is not None:
            result["temperature"] = temp
        top_p = kwargs.get("top_p", self._top_p)
        if top_p is not None:
            result["top_p"] = top_p
        return result
