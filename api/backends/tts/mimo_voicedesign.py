"""MiMo VoiceDesign TTS — 云 API，免费，自然语言描述生成声音

使用 MiMo TTS API（chat completions 端点）。
支持模型: mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2-tts

风格控制方式（根据模型不同）:
- mimo-v2.5-tts / voicedesign: 自然语言描述放在 user 消息（导演模式）
- mimo-v2-tts: <style>标签</style> 放在 assistant 消息开头

官方文档:
- V2.5: https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis-v2.5
- V2: https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis
"""
from __future__ import annotations

import base64
import logging
import os

from api.registry import BackendMeta, registry
from api.backends.tts._mimo_common import (
    write_wav_or_pcm, EMOTION_STYLE, EMOTION_STYLE_V2,
)
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)

__all__ = ["MimoVoiceDesign"]

# V2.5 语速修饰（VoiceDesign 独有，比通用描述多语速信息）
_EMOTION_STYLE_V25 = {
    **{k: v + "，语速稍快" for k, v in EMOTION_STYLE.items() if k in ("happy", "angry")},
    **{k: v + "，语速缓慢" for k, v in EMOTION_STYLE.items() if k == "sad"},
    **{k: v + "，声音沉稳有力" for k, v in EMOTION_STYLE.items() if k == "serious"},
    **{k: v + "，声音温和自然" for k, v in EMOTION_STYLE.items() if k == "calm"},
    **{k: v + "，声音有力" for k, v in EMOTION_STYLE.items() if k == "determined"},
    **{k: v + "，声音颤抖紧张" for k, v in EMOTION_STYLE.items() if k == "fearful"},
    **{k: v + "，声音柔和细腻" for k, v in EMOTION_STYLE.items() if k == "romantic"},
    **{k: v + "，声音充满张力" for k, v in EMOTION_STYLE.items() if k == "action"},
    **{k: v + "，带着自信" for k, v in EMOTION_STYLE.items() if k == "smug"},
    "neutral": "",
}


def _build_messages(text: str, voice_desc: str, emotion: str, is_v25: bool, is_voicedesign: bool) -> list:
    """构建 TTS API 消息列表"""
    messages = []
    if is_v25:
        emotion_desc = _EMOTION_STYLE_V25.get(emotion, "")
        style_parts = [p for p in (voice_desc, emotion_desc) if p]
        combined_style = "，".join(style_parts) if style_parts else ""
        if combined_style:
            messages.append({"role": "user", "content": combined_style})
        elif is_voicedesign:
            messages.append({"role": "user", "content": "自然流畅的语音"})
        messages.append({"role": "assistant", "content": text})
    else:
        emotion_tag = EMOTION_STYLE_V2.get(emotion, "")
        synthesis_text = f"<style>{emotion_tag}</style>{text}" if emotion_tag else text
        if voice_desc:
            messages.append({"role": "user", "content": voice_desc})
        messages.append({"role": "assistant", "content": synthesis_text})
    return messages


class MimoVoiceDesign:
    """MiMo VoiceDesign TTS 后端（云 API，免费）"""

    _DEFAULT_API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
    _DEFAULT_MODEL = "mimo-v2.5-tts"

    def __init__(self, config: dict):
        self._api_url = config.get("api_url") or os.environ.get("MIMO_API_ENDPOINT", self._DEFAULT_API_URL)
        self._model = config.get("model") or os.environ.get("MIMO_TTS_MODEL", self._DEFAULT_MODEL)
        self._api_key = config.get("api_key") or os.environ.get("MIMO_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)

    @property
    def name(self) -> str:
        return "mimo-voicedesign"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置。获取: https://api.xiaomimimo.com")

        voice_config = voice_config or {}
        voice_desc = voice_config.get("core_traits", "") or voice_config.get("voice_description", "")
        voice_id = voice_config.get("voice_id", "")
        is_v25 = "v2.5" in self._model or "voicedesign" in self._model
        is_voicedesign = "voicedesign" in self._model

        messages = _build_messages(text, voice_desc, emotion, is_v25, is_voicedesign)
        audio_params: dict = {"format": "wav"}
        if not is_voicedesign:
            audio_params["voice"] = voice_id or "mimo_default"

        r = self._client.post(
            self._api_url,
            headers=auth_headers(self._api_key, api_key_header="api-key"),
            json={"model": self._model, "audio": audio_params, "messages": messages})
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


def _factory(config: dict) -> MimoVoiceDesign:
    return MimoVoiceDesign(config)


registry.register(BackendMeta(
    name="mimo-voicedesign", service_type="tts", factory=_factory,
    requires_api_key=True, api_key_env="MIMO_API_KEY",
    description="MiMo VoiceDesign 云 API（免费）", priority=10, tags=["cloud", "free"],
    deployment="cloud",
))
