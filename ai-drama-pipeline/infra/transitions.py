"""转场效果 — ffmpeg concat + xfade 滤镜构建

改进: 多段视频 xfade offset 精确计算，音频/视频时间轴同步
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["TRANSITIONS", "get_xfade_filter", "build_concat_filter"]

# 转场类型 → ffmpeg xfade 过滤器
TRANSITIONS = {
    "crossfade": "fade",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "glitch": "fadeblack",
    "zoom_blur": "smoothleft",
    "circle_open": "circleopen",
    "circle_close": "circleclose",
}


def get_xfade_filter(transition: str, offset: float, duration: float) -> str:
    """生成 ffmpeg xfade 过滤器字符串"""
    xfade = TRANSITIONS.get(transition, "fade")
    return f"xfade=transition={xfade}:duration={duration}:offset={offset}"


def _build_audio_filter(audio_inputs: list[int], duration: float) -> list[str]:
    """构建音频 acrossfade 滤镜链"""
    if not audio_inputs or len(audio_inputs) < 2:
        return []
    if len(audio_inputs) == 2:
        return [f"[{audio_inputs[0]}:a][{audio_inputs[1]}:a]acrossfade=d={duration}:c1=tri:c2=tri[a]"]
    parts = []
    prev_label = f"{audio_inputs[0]}:a"
    for i in range(1, len(audio_inputs)):
        out_label = "a" if i == len(audio_inputs) - 1 else f"a{i}"
        parts.append(f"[{prev_label}][{audio_inputs[i]}:a]acrossfade=d={duration}:c1=tri:c2=tri[{out_label}]")
        prev_label = out_label
    return parts


def _build_xfade_filter(inputs: list[str], durations: list[float], transition: str, duration: float) -> list[str]:
    """构建视频 xfade 滤镜链"""
    xfade = TRANSITIONS.get(transition, "fade")
    if len(inputs) == 2:
        offset = max(0, durations[0] - duration)
        return [f"[0:v][1:v]xfade=transition={xfade}:duration={duration}:offset={offset}[v]"]
    parts = []
    prev_label = "0:v"
    for i in range(1, len(inputs)):
        offset = round(max(0, sum(durations[:i]) - duration * i), 3)
        out_label = f"v{i}" if i < len(inputs) - 1 else "v"
        parts.append(f"[{prev_label}][{i}:v]xfade=transition={xfade}:duration={duration}:offset={offset}[{out_label}]")
        prev_label = out_label
    return parts


def build_concat_filter(inputs: list[str], output: str, transition: str = "crossfade",
                        duration: float = 0.5, timeout: int = 1200) -> str:
    """带转场的视频拼接

    Args:
        inputs: 输入视频路径列表
        output: 输出路径
        transition: 转场类型
        duration: 转场时长（秒）
        timeout: 超时时间

    Returns:
        输出文件路径
    """
    if not inputs:
        return ""
    if len(inputs) == 1:
        shutil.copy2(inputs[0], output)
        return output

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    from infra.compute.ffmpeg import ffmpeg_path, probe
    ffmpeg = ffmpeg_path()
    probe_cache = [probe(p) for p in inputs]

    def _safe_duration(info: dict) -> float:
        try:
            val = info.get("format", {}).get("duration", 0)
            if val in (None, "N/A", ""):
                return 4.0
            return float(val)
        except (ValueError, TypeError):
            return 4.0

    durations = [_safe_duration(info) for info in probe_cache]
    logger.debug(f"视频时长: {durations}")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]
    for p in inputs:
        cmd.extend(["-i", p])

    # 视频滤镜
    filter_parts = _build_xfade_filter(inputs, durations, transition, duration)

    # 音频滤镜
    audio_inputs = [i for i, info in enumerate(probe_cache)
                    if any(s.get("codec_type") == "audio" for s in info.get("streams", []))]
    # 混合有/无音频视频时，跨淡入淡出会因缺少音频流而失败
    # 只有全部输入都有音频时才做音频转场
    if len(audio_inputs) == len(inputs):
        audio_parts = _build_audio_filter(audio_inputs, duration)
    else:
        if audio_inputs:
            logger.warning(f"转场: {len(inputs)} 个视频中仅 {len(audio_inputs)} 个有音频，跳过音频转场")
        audio_parts = []

    all_filters = filter_parts + audio_parts
    if all_filters:
        cmd.extend(["-filter_complex", ";".join(all_filters)])
        cmd.extend(["-map", "[v]"])
        if audio_parts:  # 仅当音频滤镜实际生成了 [a] 标签时才映射
            cmd.extend(["-map", "[a]"])

    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", output])

    logger.debug(f"ffmpeg concat: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"转场拼接失败 (exit {r.returncode}): {r.stderr[-500:]}")
    return output
