"""FFmpeg 工具 — 跨平台音视频处理"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["FFmpeg", "probe", "ffmpeg_path"]

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
_FFPROBE = shutil.which("ffprobe") or "ffprobe"


def ffmpeg_path() -> str:
    """获取 ffmpeg 可执行文件路径（公开 API）"""
    return _FFMPEG


def probe(path: str) -> dict[str, Any]:
    """获取媒体文件信息"""
    cmd = [_FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"媒体信息读取失败: {r.stderr[:200]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"媒体信息解析失败（ffprobe 输出非 JSON）: {r.stdout[:200]}")


class FFmpeg:
    """FFmpeg 封装 — 提供链式 API"""

    def __init__(self, *, timeout: int = 1200):
        self._timeout = timeout
        self._args: list[str] = [_FFMPEG, "-y", "-hide_banner", "-loglevel", "warning"]
        self._output = ""

    def input(self, path: str, **opts) -> "FFmpeg":
        for k, v in opts.items():
            self._args.extend([f"-{k}", str(v)])
        self._args.extend(["-i", path])
        return self

    def filter(self, vf: str) -> "FFmpeg":
        self._args.extend(["-vf", vf])
        return self

    def output(self, path: str, **opts) -> "FFmpeg":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        for k, v in opts.items():
            self._args.extend([f"-{k}", str(v)])
        self._args.append(path)
        self._output = path
        return self

    def run(self) -> str:
        logger.debug(f"ffmpeg: {' '.join(self._args)}")
        r = subprocess.run(self._args, capture_output=True, text=True, timeout=self._timeout)
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg 执行失败 (exit {r.returncode}): {r.stderr[-500:]}")
        return self._output

    @staticmethod
    def concat(inputs: list[str], output: str, *, transition: str = "none",
               duration: float = 0.5, timeout: int = 1200) -> str:
        """拼接多个视频（支持转场）"""
        if not inputs:
            return ""
        if len(inputs) == 1:
            shutil.copy2(inputs[0], output)
            return output

        # 简单拼接（无转场）
        if transition == "none":
            import tempfile
            fd, list_file = tempfile.mkstemp(suffix=".list.txt", dir=str(Path(output).parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for p in inputs:
                        # ffmpeg concat 协议要求: 单引号需转义为 '\''
                        escaped = os.path.abspath(p).replace("'", "'\\''")
                        f.write(f"file '{escaped}'\n")
                cmd = [_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                       "-c", "copy", output]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                if r.returncode != 0:
                    raise RuntimeError(f"视频拼接失败: {r.stderr[-300:]}")
            finally:
                if os.path.exists(list_file):
                    os.unlink(list_file)
            return output

        # 带转场拼接
        from infra.transitions import build_concat_filter
        return build_concat_filter(inputs, output, transition, duration, timeout)

    @staticmethod
    def add_subtitle(video: str, srt: str, output: str, **opts) -> str:
        """烧录字幕"""
        # 转义路径中的特殊字符（ffmpeg subtitles 滤镜需要）
        # 参考: https://ffmpeg.org/ffmpeg-filters.html#Notes-on-filtergraph-escaping
        _escape_map = {"\\": "\\\\", "'": "\\'", ":": "\\:", "[": "\\[", "]": "\\]",
                       ";": "\\;", "=": "\\=", "#": "\\#", "~": "\\~"}
        escaped_srt = srt
        for old, new in _escape_map.items():
            escaped_srt = escaped_srt.replace(old, new)
        escaped_srt = escaped_srt.replace("%", "%%")  # % 需要双转义
        sub_filter = f"subtitles='{escaped_srt}'"
        cmd = [_FFMPEG, "-y", "-i", video, "-vf", sub_filter, "-c:a", "copy", output]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            raise RuntimeError(f"字幕烧录失败: {r.stderr[-300:]}")
        return output

    @staticmethod
    def mix_audio(video: str, audio: str, output: str, *,
                  video_vol: float = 1.0, audio_vol: float = 0.15) -> str:
        """混合视频音频。视频无音频流时以 BGM 为唯一音轨。"""
        info = probe(video)
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        # 用视频时长做截断基准，避免 BGM 过短时 -shortest 截断视频
        video_dur = float(info.get("format", {}).get("duration", 0))
        if has_audio:
            filter_complex = f"[0:a]volume={video_vol}[va];[1:a]volume={audio_vol}[ba];[va][ba]amix=inputs=2:normalize=0"
        else:
            filter_complex = f"[1:a]volume={audio_vol}[ba]"
        cmd = [_FFMPEG, "-y", "-i", video, "-i", audio,
               "-filter_complex", filter_complex,
               "-c:v", "copy"]
        if not has_audio:
            cmd.extend(["-map", "0:v", "-map", "[ba]"])
        if video_dur > 0:
            cmd.extend(["-t", str(video_dur)])
        else:
            cmd.append("-shortest")
        cmd.append(output)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            raise RuntimeError(f"音频混合失败: {r.stderr[-300:]}")
        return output
