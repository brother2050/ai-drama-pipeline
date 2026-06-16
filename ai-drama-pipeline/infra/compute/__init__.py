"""计算资源包

从 gpu.py 和 ffmpeg.py 整合而来。
"""
from infra.compute.gpu import get_generation_config
from infra.compute.ffmpeg import FFmpeg, ffmpeg_path, probe

__all__ = [
    "get_generation_config",
    "FFmpeg", "ffmpeg_path", "probe",
]
