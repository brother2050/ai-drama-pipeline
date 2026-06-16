"""ChatTTS TTS — HTTP API 语音合成"""
from __future__ import annotations

import logging
from pathlib import Path

from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)


class ChatTTS:
    """ChatTTS TTS 后端（ChatTTS-ui HTTP API）

    声音一致性通过 seed 实现：同一 seed 值产生相同音色。
    voice_config.custom_voice（或 clone_seed）指定种子值，大于 0 时生效。
    """

    def __init__(self, config: dict):
        self._url = config.get("api_url", "")
        if not self._url:
            raise ValueError("ChatTTS api_url 未配置，请在 system.yaml 的 models.chattts.api_url 中设置")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str:
        return "chattts"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        voice_config = voice_config or {}
        Path(output).parent.mkdir(parents=True, exist_ok=True)

        # custom_voice: 种子值，>0 时覆盖 voice 参数（同一 seed = 同一音色）
        custom_voice = int(voice_config.get("custom_voice") or voice_config.get("clone_seed") or 0)

        params = {
            "text": text,
            "voice": str(voice_config.get("voice", 2222)),
            "prompt": voice_config.get("prompt", ""),
            "temperature": float(voice_config.get("temperature", 0.3)),
            "top_p": float(voice_config.get("top_p", 0.7)),
            "top_k": int(voice_config.get("top_k", 20)),
            "skip_refine": int(voice_config.get("skip_refine", 0)),
            "custom_voice": custom_voice,
        }

        resp = self._client.post(f"{self._url}/tts", data=params)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise RuntimeError(f"ChatTTS 合成失败: {result.get('msg', '未知错误')}")

        audio_files = result.get("audio_files", [])
        if not audio_files:
            raise RuntimeError("ChatTTS 未返回音频文件")

        audio_url = audio_files[0].get("url", "")
        if not audio_url:
            raise RuntimeError("ChatTTS 返回的音频 URL 为空")

        # 下载音频：先试原始 URL，失败则交换 http/https 重试
        from infra.config import atomic_write_bytes
        audio_data = self._download_audio(audio_url)
        atomic_write_bytes(output, audio_data)
        return output

    def _download_audio(self, url: str) -> bytes:
        """下载音频文件，自动处理 http/https scheme 差异"""
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("audio") or len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass

        # scheme 交换重试
        swapped = url.replace("https://", "http://", 1) if url.startswith("https://") else url.replace("http://", "https://", 1)
        if swapped != url:
            resp = self._client.get(swapped)
            resp.raise_for_status()
            return resp.content

        raise RuntimeError(f"ChatTTS 音频下载失败: {url}")

    def health_check(self) -> tuple[bool, str]:
        from api.backends import http_health_check
        return http_health_check(self._url, self._fast_client, "ChatTTS")

    def shutdown(self) -> None:
        pass


def _factory(config: dict) -> ChatTTS:
    return ChatTTS(config)


registry.register(BackendMeta(
    name="chattts", service_type="tts", factory=_factory,
    description="ChatTTS 语音合成（本地部署，seed 音色一致性）", priority=60, tags=["api"],
))
