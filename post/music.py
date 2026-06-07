"""配乐生成 — 通过 Container 获取音乐后端"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["MusicGenerator"]


class MusicGenerator:
    """配乐生成器 — 优先使用注册的音乐后端，回退到 ffmpeg 模板"""
    def __init__(self, backend: str = "", config: dict | None = None, timeouts: dict | None = None,
                 container: object = None):
        self._backend = backend
        self._config = config or {}
        self._timeouts = timeouts or {}
        self._container = container

    def generate(self, duration: float, output: str, *, mood: str = "neutral") -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        # 尝试通过 Container 获取注册的音乐后端
        try:
            if self._container is None:
                from api.registry import Container
                self._container = Container(self._config)
            music_backend = self._container.get("music")
            return music_backend.generate(duration, output, mood=mood)
        except Exception as e:
            logger.warning(f"音乐后端不可用 ({e})，回退到 ffmpeg 模板（建议安装 MusicGen 获得更好音质）")
            return self._template(duration, output, mood)

    def _template(self, duration: float, output: str, mood: str) -> str:
        """ffmpeg 模板配乐（最终回退）— 复用 TemplateMusic 后端"""
        from api.backends.music.template import TemplateMusic
        backend = TemplateMusic(self._config)
        return backend.generate(duration, output, mood=mood)
