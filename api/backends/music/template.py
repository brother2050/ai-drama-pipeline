"""模板配乐 — ffmpeg 生成简单 BGM（开箱即用）"""
from __future__ import annotations
import logging, subprocess, shutil
from pathlib import Path
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class TemplateMusic:
    """使用 ffmpeg 生成简单配乐"""
    def __init__(self, config: dict):
        self._config = config
    @property
    def name(self) -> str: return "template"

    def generate(self, duration: float, output: str, *,
                 mood: str = "neutral", bpm: int = 120) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        duration = max(1, min(300, duration))  # 1秒 ~ 5分钟
        # 用 ffmpeg 生成简单音调
        freq = {"happy": 440, "sad": 330, "angry": 520, "neutral": 400}.get(mood, 400)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"sine=frequency={freq}:duration={duration}",
               "-af", f"volume=0.15,tremolo=f=4:d=0.3", output]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 模板配乐失败: {r.stderr[-200:]}")
        return output

    def health_check(self) -> tuple[bool, str]: return True, "template music (ffmpeg)"
def _f(config): return TemplateMusic(config)
registry.register(BackendMeta(name="template", service_type="music", factory=_f,
    description="ffmpeg 模板配乐（开箱即用）", priority=10, tags=["local", "free"]))
