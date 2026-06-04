"""CosyVoice TTS — HTTP API 多语言语音合成"""
from __future__ import annotations
import logging
from pathlib import Path
from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)

class CosyVoice:
    """CosyVoice TTS 后端"""
    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("CosyVoice api_url 未配置，请在 system.yaml 的 models.cosyvoice.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str: return "cosyvoice"

    def synthesize(self, text: str, output: str, *, voice_config: dict | None = None,
                   emotion: str = "neutral", language: str = "zh") -> str:
        voice_config = voice_config or {}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        r = self._client.post(f"{self._url}/api/tts", json={
            "text": text, "language": language,
            "speaker": voice_config.get("speaker", "default"),
            "emotion": emotion,
        })
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        from api.backends import http_health_check
        return http_health_check(self._url, self._fast_client, "CosyVoice")

    def shutdown(self):
        pass  # 共享连接池，无需关闭

def _f(config): return CosyVoice(config)
registry.register(BackendMeta(name="cosyvoice", service_type="tts", factory=_f,
    description="CosyVoice 多语言 TTS", priority=60, tags=["api"]))
