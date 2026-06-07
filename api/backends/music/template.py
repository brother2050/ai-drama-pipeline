"""模板配乐 — ffmpeg 生成简单 BGM（开箱即用）"""
from __future__ import annotations
import logging
import subprocess
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
        # 用 ffmpeg 生成简单音调（每种情绪对应不同频率）
        freq = {
            "happy": 440, "sad": 330, "angry": 520, "romantic": 392,
            "worried": 370, "surprised": 480, "smug": 460, "serious": 350,
            "calm": 400, "determined": 450, "fearful": 310, "action": 500,
        }.get(mood, 400)
        from infra.ffmpeg import ffmpeg_path
        ffmpeg = ffmpeg_path()
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"sine=frequency={freq}:duration={duration}",
               "-af", "volume=0.15,tremolo=f=4:d=0.3", output]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 模板配乐失败: {r.stderr[-500:]}")
        return output

    def shutdown(self):
        """释放资源（模板后端无外部依赖）"""

    def health_check(self) -> tuple[bool, str]: return True, "template music (ffmpeg)"
def _f(config): return TemplateMusic(config)
registry.register(BackendMeta(name="template", service_type="music", factory=_f,
    description="ffmpeg 模板配乐（开箱即用）", priority=10, tags=["local", "free"]))
