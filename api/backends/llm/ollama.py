"""Ollama LLM 后端 — 基于 Ollama NDJSON 流式协议（/api/chat）

协议特点：
- 请求：POST /api/chat，参数放在 options 子对象中
- 响应：NDJSON 流（每行一个 JSON），非流式为标准 JSON
- 认证：无需 API Key（本地部署）
- 特有参数：top_k
"""
from __future__ import annotations

import logging
import time
from json import JSONDecodeError as _JSONDecodeError, loads as _json_loads

from api.registry import BackendMeta, registry
from .base import BaseLLM
from .mixins import ConfigMixin, ErrorLearningMixin, HttpRetryMixin

logger = logging.getLogger(__name__)

__all__ = ["OllamaLLM"]


class OllamaLLM(ConfigMixin, ErrorLearningMixin, HttpRetryMixin, BaseLLM):
    """Ollama 本地 LLM 后端。

    支持 num_predict / temperature / top_p / top_k 等参数。
    流式响应使用 NDJSON 格式（每行一个 JSON 对象）。
    """

    def __init__(self, config: dict):
        self._init_llm_config(config)
        if not self._url:
            raise ValueError("Ollama base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        if not self._model:
            self._model = "qwen3:8b"
        self._top_k = config.get("top_k")

    # ── 接口实现 ──

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def context_length(self) -> int:
        """模型上下文长度：配置 > /api/show 探测 > 默认 8192"""
        if self._ctx > 0:
            return self._ctx
        try:
            self._fast_client = self._ensure_client(self._fast_client, 5)
            r = self._fast_client.post(f"{self._url}/api/show", json={"name": self._model})
            if r.status_code == 200:
                params = r.json().get("model_info", {})
                for key, val in params.items():
                    if key.endswith(".context_length") and isinstance(val, int) and val > 0:
                        self._ctx = val
                        return val
        except Exception as e:
            logger.debug(f"{type(e).__name__}: {e}")
        self._ctx = 8192
        return 8192

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = self._build_messages(prompt, system)
        logger.info(f"LLM 请求 [{self._model}] system={system[:80]!r} prompt={prompt[:200]!r}")

        options = self._resolve_options(kwargs, extra_fields={
            "num_predict": kwargs.get("max_tokens", 2048),
        })
        # Ollama 特有：top_k
        top_k = kwargs.get("top_k", self._top_k)
        if top_k is not None:
            options["top_k"] = top_k

        self._client = self._ensure_client(self._client, self._timeout)
        use_stream = kwargs.get("stream", self._stream)
        body = {"model": self._model, "messages": messages, "stream": use_stream, "options": options}

        t0 = time.time()
        try:
            if use_stream:
                result = self._try_stream(body)
                if result:
                    elapsed = time.time() - t0
                    logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s 流式 len={len(result)} preview={result[:200]!r}")
                    return result
                logger.warning("Ollama 流式返回空内容，降级为非流式重试")

            body["stream"] = False
            result = self._try_non_stream(body)
            elapsed = time.time() - t0
            logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s len={len(result)} preview={result[:200]!r}")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM 失败 [{self._model}] {elapsed:.1f}s {type(e).__name__}: {e}")
            self._try_learn_limits(self._model, e)
            raise

    def health_check(self) -> tuple[bool, str]:
        self._fast_client = self._ensure_client(self._fast_client, 5)
        try:
            r = self._fast_client.get(f"{self._url}/api/tags")
            return True, f"Ollama reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"

    # ── 协议专有方法 ──

    def _try_stream(self, body: dict) -> str:
        """尝试流式请求，返回解析后的文本（失败则抛异常）"""
        with self._client.stream("POST", f"{self._url}/api/chat", json=body) as r:
            r.raise_for_status()
            return self._parse_ndjson_stream(r)

    def _try_non_stream(self, body: dict) -> str:
        """非流式请求，直接返回 message.content"""
        r = self._client.post(f"{self._url}/api/chat", json=body)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

    @staticmethod
    def _build_messages(prompt: str, system: str) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _parse_ndjson_stream(response) -> str:
        """解析 Ollama NDJSON 流式响应（每行一个 JSON 对象）"""
        parts: list[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                obj = _json_loads(line)
                content = obj.get("message", {}).get("content", "")
                if content:
                    parts.append(content)
                if obj.get("done"):
                    break
            except _JSONDecodeError:
                continue
        result = "".join(parts)
        if not result:
            logger.warning("Ollama NDJSON 流式响应为空")
        return result


# ── 注册到全局服务注册表 ──

def _factory(config): return OllamaLLM(config)


registry.register(BackendMeta(
    name="ollama", service_type="llm", factory=_factory,
    description="Ollama LLM", priority=10, tags=["api"],
))
