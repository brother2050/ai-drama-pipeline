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
        """模型上下文长度（优先配置值 → API 探测 → 注册表 → 默认值）"""
        if self._ctx > 0:
            return self._ctx
        try:
            self._fast_client = _ensure_client(self._fast_client, 5)
            r = self._fast_client.get(f"{self._url}/models", headers=self._headers)
            if r.status_code == 200:
                data = r.json()
                models = data.get("data", [])
                if models:
                    model = models[0]
                    # 标准 OpenAI 格式：顶层直接返回上下文窗口字段
                    for key in ("context_length", "context_window",
                                "max_context_length", "max_context_window", "max_model_len"):
                        val = model.get(key, 0)
                        if isinstance(val, int) and val > 0:
                            self._ctx = val
                            logger.info(f"从 /models.{key} 检测到上下文窗口: {val}")
                            return val
                    # llama.cpp 格式：嵌套在 meta.n_ctx 中
                    n_ctx = model.get("meta", {}).get("n_ctx", 0)
                    if isinstance(n_ctx, int) and n_ctx > 0:
                        self._ctx = n_ctx
                        logger.info(f"从 /models.meta.n_ctx 检测到上下文窗口: {n_ctx}")
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
            logger.warning(f"无法检测 {self._model} 上下文窗口，使用默认 8192")
            self._ctx = 8192
            return 8192

    def _parse_api_error(self, resp: dict) -> None:
        """检测 API 返回的 error 对象，有则抛出异常"""
        if "error" not in resp:
            return
        err = resp["error"]
        if isinstance(err, dict):
            msg = err.get("message", str(err))
            code = err.get("code") or err.get("type") or ""
        else:
            msg = str(err)
            code = ""
        raise ValueError(f"API 错误 [{code}]: {msg}")

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
        temp = kwargs.get("temperature", self._temperature)
        if temp is not None:
            body["temperature"] = temp
        top_p = kwargs.get("top_p", self._top_p)
        if top_p is not None:
            body["top_p"] = top_p
        self._client = _ensure_client(self._client, self._timeout)
        use_stream = kwargs.get("stream", self._stream)
        # 思考模型（Kimi k2 / Qwen3 / DeepSeek-R1 等）跳过流式：
        # 思考阶段只输出 reasoning_content，content 迟迟不出现，SSE 连接容易超时截断
        is_thinking = self._is_thinking_model()
        if use_stream and is_thinking:
            logger.info(f"LLM [{self._model}] 为思考模型，跳过流式，直接使用非流式请求")
            use_stream = False
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
            resp = r.json()
            self._parse_api_error(resp)
            choices = resp.get("choices", [])
            if not choices:
                raise ValueError(f"LLM 返回空 choices（无生成结果）: {resp}")
            msg = choices[0].get("message", {})
            # thinking 模型：只取 content（最终输出），reasoning_content 为思考过程应忽略
            result = msg.get("content") or ""
            if not result:
                logger.warning(f"LLM 非流式返回空内容，message keys={list(msg.keys())}, resp keys={list(resp.keys())}")
            elapsed = time.time() - t0
            logger.info(f"LLM 响应 [{self._model}] {elapsed:.1f}s len={len(result)} preview={result[:200]!r}")
            return result
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM 失败 [{self._model}] {elapsed:.1f}s {type(e).__name__}: {e}")
            _try_learn_limits(self._model, e)
            raise

    def _is_thinking_model(self) -> bool:
        """检测当前模型是否为思考模型（需要 inference 阶段，不适合流式）"""
        try:
            from infra.config.registry import ModelRegistry
            return ModelRegistry().is_thinking_model(self._model)
        except Exception:
            return False

    @staticmethod
    def _parse_sse_stream(response) -> str:
        """解析 OpenAI 兼容 SSE 流式响应（data: {...} 行）

        使用 iter_bytes() 手动分行，比 iter_lines() 对大模型长连接更可靠。
        兼容 thinking 模型：只取 delta.content，忽略 delta.reasoning_content（思考过程）。
        """
        import json as _json
        parts: list[str] = []
        raw_lines_sample: list[str] = []
        buffer = b""
        for chunk in response.iter_bytes():
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    # 收到结束标记，返回已收集的 content
                    result = "".join(parts)
                    if not result:
                        logger.warning(f"OpenAI SSE 流式响应为空（收到 [DONE]），原始行样例: {raw_lines_sample}")
                    return result
                if not data:
                    continue
                try:
                    obj = _json.loads(data)
                except _json.JSONDecodeError:
                    logger.debug(f"SSE 非 JSON 行: {data[:200]}")
                    continue
                # 检测 API 流式错误（Kimi 等平台在 SSE 流中返回 error 对象）
                if "error" in obj:
                    err = obj["error"]
                    if isinstance(err, dict):
                        msg = err.get("message", str(err))
                        err_type = err.get("type", "")
                    else:
                        msg = str(err)
                        err_type = ""
                    raise ValueError(f"API 流式错误 [{err_type}]: {msg}")
                choices = obj.get("choices", [])
                if not choices:
                    # 某些 API（如 Kimi）可能在 model 级返回 usage 等元数据
                    if "usage" in obj or "model" in obj:
                        continue
                    continue
                delta = choices[0].get("delta", {})
                # thinking 模型：只取 content（最终输出），忽略 reasoning_content（思考过程）
                content = delta.get("content")
                if content:
                    parts.append(content)
                # 调试：采集前 5 行原始数据
                if len(raw_lines_sample) < 5:
                    raw_lines_sample.append(data[:300])
        # 流结束但未收到 [DONE]（连接异常断开或超时）
        result = "".join(parts)
        if not result:
            logger.warning(f"OpenAI SSE 流式响应为空（连接提前关闭），原始行样例: {raw_lines_sample}")
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
