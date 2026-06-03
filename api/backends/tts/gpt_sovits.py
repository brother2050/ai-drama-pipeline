"""GPT-SoVITS TTS — HTTP API 语音克隆"""

from __future__ import annotations
import logging
from pathlib import Path
from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)


class GptSovits:
    """GPT-SoVITS TTS 后端"""
    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("GPT-SoVITS api_url 未配置，请在 system.yaml 的 models.gpt_sovits.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str:
        return "gpt-sovits"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        r = self._client.post(f"{self._url}/tts", json={
            "text": text, "text_language": language,
            "refer_audio_path": ref_audio,
            "prompt_text": voice_config.get("prompt_text", ""),
        })
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        try:
            r = self._fast_client.get(f"{self._url}/docs")
            return True, f"GPT-SoVITS reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"GPT-SoVITS unreachable: {e}"

    def shutdown(self) -> None:
        pass  # 共享连接池，无需关闭


def _factory(config: dict) -> GptSovits:
    return GptSovits(config)

registry.register(BackendMeta(
    name="gpt-sovits", service_type="tts", factory=_factory,
    description="GPT-SoVITS 语音克隆", priority=50, tags=["api"],
))
