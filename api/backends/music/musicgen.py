"""MusicGen 配乐 — 通用 HTTP API（兼容 RunPod / 自部署 / 任意 MusicGen 服务）"""
from __future__ import annotations

import logging
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


class MusicGenAPI:
    """通过 HTTP API 调用 MusicGen 生成配乐

    兼容以下响应格式:
    1. RunPod Serverless: {"status": "COMPLETED", "output": {"audio_url": "..."}}
    2. 通用 JSON: {"audio_url": "..."} 或 {"audio_base64": "..."}
    3. 直接返回音频二进制（WAV/MP3）
    """

    def __init__(self, config: dict):
        # 兼容两种 config 格式：
        # 1. Container 扁平化后：api_url 在顶层
        # 2. 原始嵌套格式：music.api_url
        music_cfg = config.get("music", {})
        self._api_url = (config.get("api_url")
                         or music_cfg.get("api_url") or "").rstrip("/")
        self._api_key = (config.get("api_key")
                         or music_cfg.get("api_key") or "")
        self._timeout = config.get("timeouts", {}).get("music", 300)
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

        resp = self._client.post(
            self._api_url,
            json={"prompt": prompt, "duration": duration},
            headers=self._headers,
        )
        resp.raise_for_status()

        # 根据 Content-Type 分发处理
        content_type = resp.headers.get("content-type", "")
        if "audio" in content_type or "octet-stream" in content_type:
            # 直接返回音频二进制
            Path(output).write_bytes(resp.content)
        else:
            # JSON 响应 → 提取音频
            self._extract_audio(resp.json(), output)

        logger.info(f"MusicGen 完成: {output}")
        return output

    def _extract_audio(self, data: dict, output: str) -> None:
        """从 JSON 响应中提取音频（兼容多种格式）"""
        import base64

        # RunPod 格式: {"status": "COMPLETED", "output": {...}}
        if "output" in data and isinstance(data["output"], dict):
            status = data.get("status", "")
            if status and status != "COMPLETED":
                raise RuntimeError(f"MusicGen 任务失败 (status={status}): {data.get('error', data['output'])}")
            data = data["output"]

        # 提取音频
        audio_url = data.get("audio_url", "")
        audio_base64 = data.get("audio_base64", "")
        audio_data = data.get("audio", "")  # 有些 API 直接返回 base64 在 audio 字段

        if audio_url:
            r = self._client.get(audio_url)
            r.raise_for_status()
            Path(output).write_bytes(r.content)
        elif audio_base64:
            Path(output).write_bytes(base64.b64decode(audio_base64))
        elif audio_data and isinstance(audio_data, str):
            try:
                Path(output).write_bytes(base64.b64decode(audio_data))
            except Exception:
                raise RuntimeError(f"MusicGen 响应中 audio 字段不是有效 base64")
        else:
            raise RuntimeError(f"MusicGen 响应中无音频数据: {data}")

    def health_check(self) -> tuple[bool, str]:
        if not self._api_url:
            return False, "music.api_url 未配置"
        return True, f"MusicGen API → {self._api_url[:50]}"


def _f(config: dict) -> MusicGenAPI:
    return MusicGenAPI(config)


registry.register(BackendMeta(
    name="musicgen",
    service_type="music",
    factory=_f,
    description="MusicGen API — AI 配乐生成（通用 HTTP，兼容 RunPod / 自部署）",
    priority=20,
    requires_api_key=False,
    tags=["api"],
))
