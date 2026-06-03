"""Ollama / OpenAI 兼容 LLM — HTTP API（含错误驱动模型限制发现）"""
from __future__ import annotations
import logging
from api.registry import BackendMeta, registry
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)


def _try_learn_limits(model: str, error: Exception) -> None:
    """从 API 错误中学习模型限制（静默，不影响正常错误处理）"""
    try:
        from flow.model_registry import ModelRegistry
        limits = ModelRegistry.parse_limits_from_error(str(error))
        if limits:
            ModelRegistry.cache_discovered_limits(model, limits)
            logger.info(f"从错误中学习到 {model} 限制: {limits}")
    except Exception:
        logger.debug(f"学习模型限制跳过: {model}")


class OllamaLLM:
    def __init__(self, config: dict):
        self._url = config.get("base_url", "")
        if not self._url:
            raise ValueError("Ollama base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        self._model = config.get("model", "qwen3:8b")
        self._timeout = config.get("timeouts", {}).get("llm", 300)
        self._ctx = config.get("context_length", 0)
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
            r = self._fast_client.post(f"{self._url}/api/show", json={"name": self._model})
            if r.status_code == 200:
                params = r.json().get("model_info", {})
                for key, val in params.items():
                    if key.endswith(".context_length") and isinstance(val, int) and val > 0:
                        self._ctx = val
                        return val
        except Exception as e:
            logger.debug(f"{type(e).__name__}: {e}")
        return 8192

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            r = self._client.post(f"{self._url}/api/chat", json={
                "model": self._model, "messages": messages, "stream": False,
                "options": {"num_predict": kwargs.get("max_tokens", 2048)},
            })
            r.raise_for_status()
            return r.json()["message"]["content"]
        except Exception as e:
            _try_learn_limits(self._model, e)
            raise

    def health_check(self) -> tuple[bool, str]:
        try:
            r = self._fast_client.get(f"{self._url}/api/tags")
            return True, f"Ollama reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"

def _f(config): return OllamaLLM(config)
registry.register(BackendMeta(name="ollama", service_type="llm", factory=_f,
    description="Ollama LLM", priority=10, tags=["api"]))


class OpenAICompatLLM:
    _MODEL_CTX_MAP = {
        "qwen3": 131072, "qwen2.5": 32768, "qwen2": 32768, "qwen": 32768,
        "deepseek-v3": 65536, "deepseek-r1": 65536, "deepseek": 32768,
        "gpt-4o": 128000, "gpt-4-turbo": 128000, "gpt-4": 8192,
        "gpt-3.5": 16384,
        "claude-3": 200000, "claude-2": 100000,
        "glm-4": 128000, "glm-3": 8192,
        "yi-1.5": 32768, "yi-34b": 200000, "yi": 4096,
        "llama-3": 8192, "llama3": 8192, "llama-2": 4096,
        "mistral": 32768, "mixtral": 32768,
        "phi-3": 128000, "phi3": 128000,
        "internlm2": 32768, "internlm": 8192,
        "chatglm3": 8192, "chatglm4": 128000,
        "gemini": 1000000,
    }

    def __init__(self, config: dict):
        self._url = (config.get("base_url") or "").rstrip("/")
        if not self._url:
            raise ValueError("OpenAI 兼容 LLM base_url 未配置，请在 system.yaml 的 llm.base_url 中设置")
        self._model = config.get("model", "qwen2.5-7b")
        self._api_key = config.get("api_key", "")
        self._timeout = config.get("timeouts", {}).get("llm", 300)
        self._ctx = config.get("context_length", 0)
        self._headers = auth_headers(self._api_key)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=5)

    @property
    def name(self): return "openai"

    @property
    def context_length(self) -> int:
        """模型上下文长度（优先配置值，否则按模型名猜）"""
        if self._ctx > 0:
            return self._ctx
        model_lower = self._model.lower()
        for keyword, ctx in self._MODEL_CTX_MAP.items():
            if keyword in model_lower:
                return ctx
        return 8192

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            r = self._client.post(f"{self._url}/v1/chat/completions", json={
                "model": self._model, "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 2048),
            }, headers=self._headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            _try_learn_limits(self._model, e)
            raise

    def health_check(self) -> tuple[bool, str]:
        try:
            r = self._fast_client.get(f"{self._url}/v1/models", headers=self._headers)
            return True, f"OpenAI-compat reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"OpenAI-compat unreachable: {e}"

def _f2(config): return OpenAICompatLLM(config)
registry.register(BackendMeta(name="openai", service_type="llm", factory=_f2,
    description="OpenAI 兼容 API", priority=50, tags=["api"], deployment="cloud"))
