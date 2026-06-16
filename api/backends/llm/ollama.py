"""Ollama / OpenAI 兼容 LLM — HTTP API（含错误驱动模型限制发现）"""
from __future__ import annotations
import logging
import os
import time
from api.registry import BackendMeta, registry
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)


def _ensure_client(client, timeout: float):
    """检查 httpx.Client 是否可用，已关闭则从连接池获取新实例"""
    if client.is_closed:
        logger.warning("HTTP 客户端已关闭，自动重建")
        return get_client(timeout=timeout)
    return client


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


class OllamaLLM:
    """Ollama LLM 后端（本地部署，支持 num_predict/temperature/top_p/top_k 等参数）"""
    def __init__(self, config: dict):
        self._url = config.get("base_url", "")
        if not self._url:
            raise ValueError("Ollama base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        self._model = config.get("model", "qwen3:8b")
        self._timeout = config.get("timeouts", {}).get("llm", 300)
        self._ctx = config.get("context_length", 0)
        self._temperature = config.get("temperature")
        self._top_p = config.get("top_p")
        self._top_k = config.get("top_k")
        self._stream = config.get("stream", False)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=5)

    @property
    def name(self): return "ollama"

    @property
    def context_length(self) -> int:
        """模型上下文长度（优先配置值，否则查询 Ollama API）"""
        if self._ctx > 0:
            return self._ctx
        try:
            self._fast_client = _ensure_client(self._fast_client, 5)
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
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        logger.info(f"LLM 请求 [{self._model}] system={system[:80]!r} prompt={prompt[:200]!r}")
        # Ollama options：配置文件默认值 < 调用方 kwargs 显式传入
        options: dict = {"num_predict": kwargs.get("max_tokens", 2048)}
        temp = kwargs.get("temperature", self._temperature)
        if temp is not None:
            options["temperature"] = temp
        top_p = kwargs.get("top_p", self._top_p)
        if top_p is not None:
            options["top_p"] = top_p
        top_k = kwargs.get("top_k", self._top_k)
        if top_k is not None:
            options["top_k"] = top_k
        self._client = _ensure_client(self._client, self._timeout)
        use_stream = kwargs.get("stream", self._stream)
        body: dict = {"model": self._model, "messages": messages, "stream": use_stream, "options": options}
        t0 = time.time()
        try:
            if use_stream:
                with self._client.stream("POST", f"{self._url}/api/chat", json=body) as r:
                    r.raise_for_status()
                    result = self._parse_ndjson_stream(r)
                if result:
                    elapsed = time.time() - t0
                    logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s 流式 len={len(result)} preview={result[:200]!r}")
                    return result
                logger.warning("Ollama 流式返回空内容，降级为非流式重试")
            body["stream"] = False
            r = self._client.post(f"{self._url}/api/chat", json=body)
            r.raise_for_status()
            result = r.json().get("message", {}).get("content", "")
            elapsed = time.time() - t0
            logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s len={len(result)} preview={result[:200]!r}")
            return result
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM 失败 [{self._model}] {elapsed:.1f}s {type(e).__name__}: {e}")
            _try_learn_limits(self._model, e)
            raise

    @staticmethod
    def _parse_ndjson_stream(response) -> str:
        """解析 Ollama NDJSON 流式响应（每行一个 JSON 对象）"""
        import json as _json
        parts: list[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                obj = _json.loads(line)
                content = obj.get("message", {}).get("content", "")
                if content:
                    parts.append(content)
                if obj.get("done"):
                    break
            except _json.JSONDecodeError:
                continue
        result = "".join(parts)
        if not result:
            logger.warning("Ollama NDJSON 流式响应为空")
        return result

    def shutdown(self):
        """释放资源（共享连接池由 Container.shutdown_all 统一清理）"""

    def health_check(self) -> tuple[bool, str]:
        self._fast_client = _ensure_client(self._fast_client, 5)
        try:
            r = self._fast_client.get(f"{self._url}/api/tags")
            return True, f"Ollama reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"

def _f(config): return OllamaLLM(config)
registry.register(BackendMeta(name="ollama", service_type="llm", factory=_f,
    description="Ollama LLM", priority=10, tags=["api"]))


class OpenAICompatLLM:
    """OpenAI 兼容 LLM 后端（支持智谱/百炼/火山/混元/Kimi/DeepSeek/硅基/讯飞等）"""

    def __init__(self, config: dict):
        self._url = (config.get("base_url") or "").rstrip("/")
        if not self._url:
            raise ValueError("OpenAI 兼容 LLM base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        self._model = config.get("model", "qwen2.5-7b")
        self._api_key = config.get("api_key") or os.environ.get("LLM_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("llm", 300)
        self._ctx = config.get("context_length", 0)
        self._temperature = config.get("temperature")
        self._top_p = config.get("top_p")
        self._stream = config.get("stream", False)
        self._headers = auth_headers(self._api_key)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=5)

    @property
    def name(self): return "openai"

    @property
    def context_length(self) -> int:
        """模型上下文长度（优先配置值，否则查询 API，最后回退注册表）"""
        if self._ctx > 0:
            return self._ctx
        # 尝试从 API 获取实际 context window（llama.cpp /v1/models 返回 n_ctx）
        try:
            self._fast_client = _ensure_client(self._fast_client, 5)
            r = self._fast_client.get(f"{self._url}/models", headers=self._headers)
            if r.status_code == 200:
                data = r.json()
                models = data.get("data", data.get("models", []))
                if models:
                    meta = models[0].get("meta", {})
                    n_ctx = meta.get("n_ctx", 0)
                    if n_ctx > 0:
                        self._ctx = n_ctx
                        logger.info(f"从 API 检测到模型上下文窗口: {n_ctx} tokens")
                        return n_ctx
        except Exception as e:
            logger.debug(f"从 API 检测上下文窗口失败: {e}")
        # 回退到注册表
        try:
            from infra.config.registry import ModelRegistry
            limits = ModelRegistry().get_model_limits(self._model)
            self._ctx = limits["context_window"]
            return self._ctx
        except Exception:
            self._ctx = 8192
            return 8192

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        # 生成参数：配置文件默认值 < 调用方 kwargs 显式传入
        temp = kwargs.get("temperature", self._temperature)
        if temp is not None:
            body["temperature"] = temp
        top_p = kwargs.get("top_p", self._top_p)
        if top_p is not None:
            body["top_p"] = top_p
        self._client = _ensure_client(self._client, self._timeout)
        use_stream = kwargs.get("stream", self._stream)
        body["stream"] = use_stream
        logger.info(f"LLM 请求 [{self._model}] system={system[:80]!r} prompt={prompt[:200]!r}")
        t0 = time.time()
        try:
            if use_stream:
                with self._client.stream("POST", f"{self._url}/chat/completions",
                                         json=body, headers=self._headers) as r:
                    r.raise_for_status()
                    result = self._parse_sse_stream(r)
                if result:
                    elapsed = time.time() - t0
                    logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s 流式 len={len(result)} preview={result[:200]!r}")
                    return result
                logger.warning("OpenAI SSE 流式返回空内容，降级为非流式重试")
            body["stream"] = False
            r = self._client.post(f"{self._url}/chat/completions",
                                  json=body, headers=self._headers)
            r.raise_for_status()
            choices = r.json().get("choices", [])
            if not choices:
                raise ValueError("LLM 返回空 choices（无生成结果）")
            result = choices[0].get("message", {}).get("content", "")
            elapsed = time.time() - t0
            logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s len={len(result)} preview={result[:200]!r}")
            return result
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM 失败 [{self._model}] {elapsed:.1f}s {type(e).__name__}: {e}")
            _try_learn_limits(self._model, e)
            raise

    @staticmethod
    def _parse_sse_stream(response) -> str:
        """解析 OpenAI 兼容 SSE 流式响应（data: {...} 行）"""
        import json as _json
        parts: list[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            # SSE 格式: "data: {...}" 或 "data:{...}"（部分提供商无空格）或 "data: [DONE]"
            if line.startswith("data:"):
                data = line[5:].lstrip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    obj = _json.loads(data)
                    choices = obj.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        parts.append(content)
                except _json.JSONDecodeError:
                    continue
        result = "".join(parts)
        if not result:
            logger.warning("OpenAI SSE 流式响应为空")
        return result

    def health_check(self) -> tuple[bool, str]:
        self._fast_client = _ensure_client(self._fast_client, 5)
        try:
            r = self._fast_client.get(f"{self._url}/models", headers=self._headers)
            return True, f"OpenAI-compat reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"OpenAI-compat unreachable: {e}"

def _f2(config): return OpenAICompatLLM(config)
registry.register(BackendMeta(name="openai", service_type="llm", factory=_f2,
    description="OpenAI 兼容 API", priority=50, tags=["api"], deployment="cloud"))
