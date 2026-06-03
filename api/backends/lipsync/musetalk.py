"""MuseTalk 口型同步 — HTTP API"""
from __future__ import annotations

import logging
from pathlib import Path

from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)


class MuseTalk:
    """MuseTalk 口型同步后端"""
    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("MuseTalk api_url 未配置，请在 system.yaml 的 models.musetalk.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("lipsync", 120)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str:
        return "musetalk"

    def sync(self, video: str, audio: str, output: str) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(video, "rb") as vf, open(audio, "rb") as af:
            r = self._client.post(f"{self._url}/process",
                                  files={"video": (Path(video).name, vf), "audio": (Path(audio).name, af)},
                                  data={"result_type": "video"})
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        try:
            r = self._fast_client.get(self._url)
            return True, f"MuseTalk reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"MuseTalk unreachable: {e}"


def _factory(config):
    return MuseTalk(config)


registry.register(BackendMeta(
    name="musetalk", service_type="lipsync", factory=_factory,
    description="MuseTalk 口型同步", priority=10, tags=["api"],
))
