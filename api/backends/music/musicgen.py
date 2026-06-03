"""MusicGen 配乐 — RunPod Serverless API"""
from __future__ import annotations

import logging
import struct
from pathlib import Path

from api.registry import BackendMeta, registry
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)

# mood → 英文 prompt 映射
_MOOD_PROMPTS = {
    "happy": "happy upbeat cheerful background music, light and joyful",
    "sad": "sad melancholic piano, gentle and emotional background music",
    "angry": "intense dramatic aggressive background music, powerful and dark",
    "romantic": "romantic gentle love theme, soft piano and strings",
    "worried": "tense anxious suspenseful background music, uneasy atmosphere",
    "surprised": "surprising magical whimsical background music, wonder and discovery",
    "calm": "calm peaceful serene ambient music, relaxing and tranquil",
    "determined": "motivational determined uplifting background music, building momentum",
    "neutral": "neutral background music, moderate tempo, balanced and pleasant",
    "fearful": "dark eerie horror background music, creepy and unsettling",
    "action": "action energetic fast-paced background music, exciting and dynamic",
    "serious": "serious dramatic cinematic background music, grand and impactful",
}


class MusicGenRunPod:
    """通过 RunPod Serverless 调用 MusicGen 生成配乐"""

    def __init__(self, config: dict):
        music_cfg = config.get("music", {})
        self._api_url = (music_cfg.get("api_url") or "").rstrip("/")
        self._api_key = music_cfg.get("api_key") or config.get("runpod", {}).get("api_key", "")
        self._timeout = config.get("timeouts", {}).get("music", 120)
        self._client = get_client(timeout=self._timeout)
        self._headers = auth_headers(self._api_key)

    @property
    def name(self) -> str:
        return "musicgen"

    def generate(self, duration: float, output: str, *,
                 mood: str = "neutral", prompt: str = "") -> str:
        """生成配乐并保存到文件

        Args:
            duration: 生成时长（秒）
            output: 输出 WAV 文件路径
            mood: 情绪（自动转为 prompt）
            prompt: 自定义 prompt（优先级高于 mood）

        Returns:
            输出文件路径
        """
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        duration = max(5, min(120, int(duration)))

        if not prompt:
            prompt = _MOOD_PROMPTS.get(mood, _MOOD_PROMPTS["neutral"])

        logger.info(f"MusicGen 生成: '{prompt}' ({duration}s) → {output}")

        # RunPod Serverless API (同步模式)
        resp = self._client.post(
            self._api_url,
            json={"input": {"prompt": prompt, "duration": duration}},
            headers=self._headers,
        )
        resp.raise_for_status()
        data = resp.json()

        # 解析响应
        status = data.get("status", "")
        if status != "COMPLETED":
            error = data.get("error", data.get("output", "未知错误"))
            raise RuntimeError(f"MusicGen 任务失败 (status={status}): {error}")

        output_data = data.get("output", {})
        audio_url = output_data.get("audio_url", "")
        audio_base64 = output_data.get("audio_base64", "")

        if audio_url:
            self._download(audio_url, output)
        elif audio_base64:
            self._decode_base64(audio_base64, output)
        else:
            raise RuntimeError(f"MusicGen 响应中无音频数据: {data}")

        logger.info(f"MusicGen 完成: {output}")
        return output

    def _download(self, url: str, output: str) -> None:
        """下载远程音频文件"""
        r = self._client.get(url)
        r.raise_for_status()
        Path(output).write_bytes(r.content)

    def _decode_base64(self, b64: str, output: str) -> None:
        """解码 base64 音频数据"""
        import base64
        Path(output).write_bytes(base64.b64decode(b64))

    def health_check(self) -> tuple[bool, str]:
        if not self._api_url:
            return False, "music.api_url 未配置"
        if not self._api_key:
            return False, "music.api_key 未配置（RUNPOD_API_TOKEN）"
        return True, f"MusicGen (RunPod) configured → {self._api_url[:50]}"


def _f(config: dict) -> MusicGenRunPod:
    return MusicGenRunPod(config)


registry.register(BackendMeta(
    name="musicgen",
    service_type="music",
    factory=_f,
    description="MusicGen (RunPod Serverless) — AI 配乐生成",
    priority=20,
    requires_api_key=True,
    api_key_env="RUNPOD_API_TOKEN",
    tags=["api", "cloud"],
    health_check={"type": "api_key_env", "env": "RUNPOD_API_TOKEN"},
))
