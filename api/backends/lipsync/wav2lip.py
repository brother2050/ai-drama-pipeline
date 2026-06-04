"""Wav2Lip 口型同步 — HTTP API"""
from __future__ import annotations
import logging
from pathlib import Path
from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)

class Wav2Lip:
    """Wav2Lip 口型同步后端"""
    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("Wav2Lip api_url 未配置，请在 system.yaml 的 models.wav2lip.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("lipsync", 120)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str: return "wav2lip"

    def sync(self, video: str, audio: str, output: str) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(video, "rb") as vf, open(audio, "rb") as af:
            r = self._client.post(f"{self._url}/process",
                       files={"face": vf, "audio": af})
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        from api.backends import http_health_check
        return http_health_check(self._url, self._fast_client, "Wav2Lip")

def _f(config): return Wav2Lip(config)
registry.register(BackendMeta(name="wav2lip", service_type="lipsync", factory=_f,
    description="Wav2Lip 口型同步", priority=80, tags=["api"]))
