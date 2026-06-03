"""MiMo VoiceClone TTS — 云 API，参考音频克隆声音

使用 MiMo TTS API（chat completions 端点），通过参考音频克隆声音。
支持模型: mimo-v2.5-tts-voiceclone, mimo-v2-tts

不同模型的 voice 参数格式不同:
- mimo-v2.5-tts-voiceclone: audio.voice = "data:audio/wav;base64,<b64>" (DataURL)
- mimo-v2-tts: audio.voice_audio = {format: "wav", data: "<b64>"} (嵌套对象)

官方文档: https://platform.xiaomimimo.com/docs/zh-CN/api/chat/openai-api
"""
from __future__ import annotations

import base64
import logging
import os

from api.registry import BackendMeta, registry
from api.backends.tts._mimo_common import write_wav_or_pcm, EMOTION_STYLE
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)


class MimoVoiceClone:
    """MiMo VoiceClone TTS 后端（云 API）"""

    _DEFAULT_API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
    _DEFAULT_MODEL = "mimo-v2.5-tts-voiceclone"

    def __init__(self, config: dict):
        self._api_url = config.get("api_url") or os.environ.get("MIMO_API_ENDPOINT", self._DEFAULT_API_URL)
        self._model = config.get("model") or os.environ.get("MIMO_TTS_CLONE_MODEL", self._DEFAULT_MODEL)
        self._api_key = config.get("api_key") or os.environ.get("MIMO_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)

    @property
    def name(self) -> str:
        return "mimo-voiceclone"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置")

        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        if not ref_audio:
            raise RuntimeError("VoiceClone 需要 reference_audio 配置")

        if not os.path.exists(ref_audio):
            raise RuntimeError(f"参考音频不存在: {ref_audio}")

        # 读取参考音频并 base64 编码
        with open(ref_audio, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")

        # 情绪 → 自然语言风格描述
        emotion_style = EMOTION_STYLE.get(emotion, "")

        messages = []
        if emotion_style:
            messages.append({"role": "user", "content": emotion_style})
        else:
            messages.append({"role": "user", "content": ""})
        messages.append({"role": "assistant", "content": text})

        # 构建 audio 参数（根据模型选择不同格式）
        audio_params: dict = {"format": "wav"}
        if "voiceclone" in self._model:
            audio_params["voice"] = f"data:audio/wav;base64,{audio_b64}"
        else:
            audio_params["voice_audio"] = {"format": "wav", "data": audio_b64}

        payload = {
            "model": self._model,
            "audio": audio_params,
            "messages": messages,
        }

        r = self._client.post(
            self._api_url,
            headers=auth_headers(self._api_key, api_key_header="api-key"),
            json=payload,
        )
        r.raise_for_status()
        resp = r.json()

        if resp.get("error"):
            raise RuntimeError(f"MiMo TTS API 错误: {resp['error']}")

        try:
            audio_data = resp["choices"][0]["message"]["audio"]["data"]
            raw = base64.b64decode(audio_data)
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"MiMo TTS 响应格式异常: {e}") from e

        write_wav_or_pcm(raw, output)
        return output

    def health_check(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "MIMO_API_KEY 未设置"
        return True, "API key 已配置"


def _factory(config: dict) -> MimoVoiceClone:
    return MimoVoiceClone(config)


registry.register(BackendMeta(
    name="mimo-voiceclone", service_type="tts", factory=_factory,
    requires_api_key=True, api_key_env="MIMO_API_KEY",
    description="MiMo VoiceClone 云 API", priority=20, tags=["cloud"],
    deployment="cloud",
))
