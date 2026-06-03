"""配乐生成 — 通过 Container 获取音乐后端"""
from __future__ import annotations
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["MusicGenerator"]


class MusicGenerator:
    """配乐生成器 — 优先使用注册的音乐后端，回退到 ffmpeg 模板"""
    def __init__(self, backend: str = "", config: dict | None = None, timeouts: dict | None = None):
        self._backend = backend
        self._config = config or {}
        self._timeouts = timeouts or {}

    def generate(self, duration: float, output: str, *, mood: str = "neutral") -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        # 尝试通过 Container 获取注册的音乐后端
        try:
            from api.registry import Container
            cont = Container(self._config)
            music_backend = cont.get("music")
            return music_backend.generate(duration, output, mood=mood)
        except Exception as e:
            logger.debug(f"音乐后端不可用 ({e})，回退到 ffmpeg 模板")
            return self._template(duration, output, mood)

    def _template(self, duration: float, output: str, mood: str) -> str:
        """ffmpeg 模板配乐（最终回退）"""
        duration = max(1, duration)  # 至少 1 秒
        freq = {
            "happy": 440, "sad": 330, "angry": 520, "romantic": 392,
            "worried": 370, "surprised": 480, "smug": 460, "serious": 350,
            "calm": 400, "determined": 450, "fearful": 310, "action": 500,
        }.get(mood, 400)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"sine=frequency={freq}:duration={duration}",
               "-af", "volume=0.1,tremolo=f=3:d=0.4", output]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 模板配乐失败 (exit {r.returncode}): {r.stderr[-200:]}")
        return output
