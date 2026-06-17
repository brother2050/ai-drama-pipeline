"""OpenAI SDK 后端 — 基于官方 openai 包，自动处理 SSE / 错误 / 思考模型

相比手写的 openai.py，本实现：
- 流式响应：SDK 原生 SSE 解析，无需手写 iter_bytes + 分行逻辑
- 错误处理：SDK 提供 RateLimitError / APIError / APIConnectionError 等类型化异常
- 思考模型：SDK 原生支持 reasoning_content 过滤，无需 is_thinking_model 判断
- 连接管理：SDK 内置 httpx 连接池复用
- 代码量：chat() 逻辑从 ~80 行缩减到 ~30 行

依赖：pip install openai
"""
from __future__ import annotations

import logging
import os
import time

from api.registry import BackendMeta, registry

from .base import BaseLLM
from .mixins import ConfigMixin, ErrorLearningMixin, HttpRetryMixin

logger = logging.getLogger(__name__)

__all__ = ["OpenAISdkLLM"]


class OpenAISdkLLM(ConfigMixin, ErrorLearningMixin, HttpRetryMixin, BaseLLM):
    """基于 openai 官方 SDK 的 LLM 后端。

    自动兼容所有 OpenAI 格式 API（智谱 / 百炼 / 火山 / 混元 / Kimi / DeepSeek / 硅基等），
    无需任何平台特殊处理。
    """

    def __init__(self, config: dict):
        self._init_llm_config(config)
        if not self._url:
            raise ValueError("OpenAI base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        self._url = self._url.rstrip("/")
        if not self._model:
            self._model = "qwen2.5-7b"

        self._api_key = config.get("api_key") or os.environ.get("LLM_API_KEY", "") or "sk-placeholder"

        # 延迟创建 client（确保测试场景下不会立即连接）
        self._sdk_client = None

    # ── 接口实现 ──

    @property
    def name(self) -> str:
        return "openai-sdk"

    @property
    def context_length(self) -> int:
        """上下文窗口：配置 > API 探测 > 注册表静态配置 > 默认 8192"""
        if self._ctx > 0:
            return self._ctx

        # 1. API 实时探测（vLLM/llama.cpp 等返回 max_model_len）
        self._ctx = self._detect_context_from_api()
        if self._ctx > 0:
            return self._ctx

        # 2. 注册表静态配置回退
        try:
            from infra.config.registry import ModelRegistry
            limits = ModelRegistry().get_model_limits(self._model)
            self._ctx = limits["context_window"]
            return self._ctx
        except Exception:
            pass

        logger.warning(f"无法检测 {self._model} 上下文窗口，使用默认 8192")
        self._ctx = 8192
        return 8192

    def _detect_context_from_api(self) -> int:
        """通过 /v1/models 探测上下文长度（vLLM 返回 max_model_len，llama.cpp 返回 context_length 等）。

        智谱/SiliconFlow 等不支持 /models 的服务商此处静默失败，回退到注册表。
        """
        client = self._get_client()
        try:
            models = client.models.list()
            data = models.data if hasattr(models, "data") else []
            for m in data:
                if getattr(m, "id", "") != self._model:
                    continue
                for attr in (
                    "max_model_len",       # vLLM
                    "context_length",       # llama.cpp / 部分服务商
                    "context_window",        # 非标准字段
                    "max_input_tokens",      # OpenAI Responses API
                ):
                    val = getattr(m, attr, None)
                    if isinstance(val, int) and val > 0:
                        logger.info(
                            f"API 探测 {self._model} context_length={val} (via {attr})"
                        )
                        return val
                break
        except Exception:
            logger.debug("API 模型列表查询不可用，回退到静态配置")
        return 0

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        """使用 openai SDK 发起对话请求。

        SDK 自动处理：
        - SSE 流式解析（无需手写 iter_bytes 分行）
        - thinking 模型的 reasoning_content 过滤
        - 连接重试 & 超时
        - 异常类型化（APIError / RateLimitError 等）
        """
        client = self._get_client()
        use_stream = kwargs.get("stream", self._stream)

        logger.info(f"LLM 请求 [{self._model}] system={system[:80]!r} prompt={prompt[:200]!r}")
        t0 = time.time()

        try:
            if use_stream:
                result = self._chat_stream(client, prompt, system, kwargs)
                if result:
                    elapsed = time.time() - t0
                    logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s 流式 len={len(result)} preview={result[:200]!r}")
                    return result
                logger.warning("SDK 流式返回空内容，降级为非流式重试")

            result = self._chat_non_stream(client, prompt, system, kwargs)
            elapsed = time.time() - t0
            logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s len={len(result)} preview={result[:200]!r}")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM 失败 [{self._model}] {elapsed:.1f}s {type(e).__name__}: {e}")
            self._try_learn_limits(self._model, e)
            raise

    def health_check(self) -> tuple[bool, str]:
        try:
            client = self._get_client()
            # 不能用 client.models.list() — 智谱/SiliconFlow/llama.cpp 等很多兼容 API 不支持 /models
            # 用最小 chat 请求做连通检测，所有 OpenAI 兼容服务都支持
            client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            return True, f"OpenAI SDK reachable ({self._url})"
        except Exception as e:
            return False, f"OpenAI SDK unreachable: {e}"

    # ── SDK 客户端管理 ──

    def _get_client(self):
        """延迟创建 openai.OpenAI 实例（线程安全）"""
        if self._sdk_client is None:
            import openai
            self._sdk_client = openai.OpenAI(
                base_url=self._url,
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=1,  # 重试由上层 handle
            )
        return self._sdk_client

    # ── 请求方法 ──

    @staticmethod
    def _build_message(prompt: str, system: str) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _chat_stream(self, client, prompt: str, system: str, kwargs: dict) -> str:
        """SDK 流式请求。SDK 自动过滤 reasoning_content，只返回 content。"""
        response = client.chat.completions.create(
            model=self._model,
            messages=self._build_message(prompt, system),
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", self._temperature),
            top_p=kwargs.get("top_p", self._top_p),
            stream=True,
        )
        parts: list[str] = []
        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                parts.append(delta.content)
        return "".join(parts)

    def _chat_non_stream(self, client, prompt: str, system: str, kwargs: dict) -> str:
        """SDK 非流式请求。"""
        response = client.chat.completions.create(
            model=self._model,
            messages=self._build_message(prompt, system),
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", self._temperature),
            top_p=kwargs.get("top_p", self._top_p),
            stream=False,
        )
        content = response.choices[0].message.content or ""
        if not content:
            logger.warning(f"LLM 非流式返回空内容, finish_reason={response.choices[0].finish_reason}")
        return content

    def shutdown(self) -> None:
        if self._sdk_client is not None:
            try:
                self._sdk_client.close()
            except Exception:
                pass
            self._sdk_client = None


# ── 注册 ──

def _factory(config): return OpenAISdkLLM(config)


registry.register(BackendMeta(
    name="openai-sdk", service_type="llm", factory=_factory,
    description="OpenAI 官方 SDK（推荐，自动处理流式/错误/思考模型）",
    priority=40, tags=["api"], deployment="cloud",
))
