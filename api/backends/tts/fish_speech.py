"""Fish-Speech TTS — HTTP API 轻量语音合成"""
from __future__ import annotations
import logging
from pathlib import Path
from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)

class FishSpeech:
    """Fish-Speech TTS 后端"""
    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("Fish-Speech api_url 未配置，请在 system.yaml 的 models.fish_speech.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str: return "fish-speech"

    def synthesize(self, text: str, output: str, *, voice_config: dict | None = None,
                   emotion: str = "neutral", language: str = "zh") -> str:
        voice_config = voice_config or {}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        if emotion != "neutral":
            logger.debug(f"Fish-Speech 不支持 emotion 参数，已忽略 (emotion={emotion})")
        r = self._client.post(f"{self._url}/v1/tts", json={
            "text": text, "reference_id": voice_config.get("reference_id", ""),
            "format": "wav",
        })
        r.raise_for_status()
        from infra.config import atomic_write_bytes
        atomic_write_bytes(output, r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        from api.backends import http_health_check
        return http_health_check(self._url, self._fast_client, "Fish-Speech")

    def shutdown(self):
        pass  # 共享连接池，无需关闭

def _f(config): return FishSpeech(config)
registry.register(BackendMeta(name="fish-speech", service_type="tts", factory=_f,
    description="Fish-Speech 轻量 TTS", priority=70, tags=["api"]))
