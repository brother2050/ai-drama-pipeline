"""多平台分发 — 注册表驱动，平台参数从 config/platforms.yaml 加载"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from infra.constants import STATUS_DONE, STATUS_ERROR

logger = logging.getLogger(__name__)

__all__ = ["get_platform_presets", "check_platform_compat", "get_adapt_params", "distribute"]

_PLATFORMS_PATH = Path(__file__).resolve().parent.parent / "config" / "platforms.yaml"


def _load_platforms() -> dict:
    """从 config/platforms.yaml 加载平台预设"""
    if not _PLATFORMS_PATH.exists():
        logger.warning(f"平台配置不存在: {_PLATFORMS_PATH}")
        return {}
    with open(_PLATFORMS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_platform_presets() -> dict:
    """获取所有平台预设（带缓存）"""
    if not hasattr(get_platform_presets, "_cache"):
        get_platform_presets._cache = _load_platforms()
    return get_platform_presets._cache


def get_video_info(video: str) -> dict:
    """获取视频基本信息"""
    try:
        from infra.ffmpeg import probe as ffprobe
        info = ffprobe(video)
        fmt = info.get("format", {})
        stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        return {
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "duration": float(fmt.get("duration", 0)),
            "size_mb": round(int(fmt.get("size", 0)) / 1024 / 1024, 2),
            "codec": stream.get("codec_name", ""),
        }
    except Exception as e:
        logger.warning(f"获取视频信息失败: {e}")
        return {}


def check_platform_compat(video: str, platform: str) -> dict:
    """检查视频是否符合平台要求"""
    presets = get_platform_presets()
    preset = presets.get(platform)
    if not preset:
        return {"compatible": False, "issues": [f"未知平台: {platform}"], "preset": {}}

    info = get_video_info(video)
    if not info or info.get("duration", 0) <= 0:
        return {"compatible": False, "issues": ["无法获取视频信息"], "preset": preset}

    issues = []
    pw, ph = preset["resolution"]
    vw, vh = info.get("width", 0), info.get("height", 0)
    if vw > 0 and vh > 0:
        if abs(vw / vh - pw / ph) > 0.1:
            issues.append(f"宽高比不匹配: 视频 {vw}x{vh}，平台要求 {pw}x{ph}")

    max_mb = preset.get("max_size_mb", 9999)
    if info.get("size_mb", 0) > max_mb:
        issues.append(f"文件过大: {info['size_mb']}MB > {max_mb}MB")

    max_dur = preset.get("max_duration_sec", 9999)
    if info.get("duration", 0) > max_dur:
        issues.append(f"时长过长: {info['duration']:.0f}s > {max_dur}s")

    return {"compatible": not issues, "issues": issues, "preset": preset, "video_info": info}


def get_adapt_params(video: str, platform: str) -> dict:
    """获取平台适配参数（用于 ffmpeg 转码）"""
    presets = get_platform_presets()
    preset = presets.get(platform, {})
    if not preset:
        return {"ffmpeg_args": [], "preset": {}, "needs_transcode": False}

    if check_platform_compat(video, platform)["compatible"]:
        return {"ffmpeg_args": [], "preset": preset, "needs_transcode": False}

    pw, ph = preset["resolution"]
    args = [
        "-vf", f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
    ]
    return {"ffmpeg_args": args, "preset": preset, "needs_transcode": True}


def distribute(video: str, platforms: list[str] | None = None) -> dict[str, dict]:
    """分发到指定平台"""
    presets = get_platform_presets()
    platforms = platforms or list(presets.keys())
    results = {}

    for p in platforms:
        preset = presets.get(p, {})
        if not preset:
            results[p] = {"status": STATUS_ERROR, "reason": f"未知平台: {p}"}
            continue

        compat = check_platform_compat(video, p)
        adapt = get_adapt_params(video, p)
        results[p] = {
            "status": STATUS_DONE if compat["compatible"] else "needs_adapt",
            "preset": preset,
            "compatibility": compat,
            "adapt_params": adapt,
        }

    return results
