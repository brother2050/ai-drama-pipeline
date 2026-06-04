"""横转竖适配

支持两种模式：
- center_crop: 居中裁剪，简单高效
- face_track: 背景模糊 + 人物居中（当前为 blur_bg 实现，
  如需真正人脸追踪请安装 face_recognition）
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["to_vertical"]


def _find_face_center(video: str, max_samples: int = 5) -> tuple[int, int] | None:
    """尝试检测视频中的人脸中心位置（多帧采样）

    Args:
        video: 视频路径
        max_samples: 最多采样帧数

    Returns:
        (x, y) 人脸中心坐标，或 None
    """
    try:
        import face_recognition
        import cv2
    except ImportError:
        return None
    try:
        cap = cv2.VideoCapture(video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return None
        # 均匀采样 max_samples 帧
        step = max(1, total // max_samples)
        positions = []
        for i in range(0, total, step):
            if len(positions) >= max_samples:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue
            rgb = frame[:, :, ::-1]
            locations = face_recognition.face_locations(rgb)
            if locations:
                top, right, bottom, left = locations[0]
                positions.append(((left + right) // 2, (top + bottom) // 2))
        cap.release()
        if not positions:
            return None
        # 取所有采样帧的平均人脸位置
        avg_x = sum(p[0] for p in positions) // len(positions)
        avg_y = sum(p[1] for p in positions) // len(positions)
        return (avg_x, avg_y)
    except Exception:
        return None


def to_vertical(video: str, output: str, mode: str = "face_track") -> str:
    """横转竖（9:16）

    Args:
        video: 输入视频路径
        output: 输出视频路径
        mode: "center_crop" 或 "face_track"

    Returns:
        输出文件路径
    """
    from infra.ffmpeg import probe as ffprobe, _FFMPEG as ffmpeg

    Path(output).parent.mkdir(parents=True, exist_ok=True)

    # 获取原始尺寸
    info = ffprobe(video)
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    w = int(stream.get("width", 1280))
    h = int(stream.get("height", 720))

    # 已经是竖屏
    if h > w:
        shutil.copy2(video, output)
        return output

    target_w, target_h = 1080, 1920

    if mode == "center_crop":
        vf = f"crop={w}:{w*target_h//target_w},scale={target_w}:{target_h}"
    else:
        # face_track 模式：尝试检测人脸中心，回退到 blur_bg
        face_pos = _find_face_center(video)
        if face_pos:
            cx, _cy = face_pos
            logger.info(f"检测到人脸中心: ({cx}, {_cy})")
            # 以目标 9:16 比例计算裁剪区域
            crop_h = h  # 保持原始高度
            crop_w = int(crop_h * target_w / target_h)  # 对应的裁剪宽度
            crop_w = min(crop_w, w)  # 不超过源宽度
            crop_x = max(0, min(cx - crop_w // 2, w - crop_w))
            vf = (f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={target_w}:{target_h}")
        else:
            logger.info("未检测到人脸，使用模糊背景模式")
            vf = (f"split[original][blur];[blur]scale={target_w}:{target_h},boxblur=20[bg];"
                  f"[original]scale=-2:{target_h}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

    cmd = [ffmpeg, "-y", "-i", video, "-vf", vf, "-c:a", "copy", output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"横转竖失败: {r.stderr[-300:]}")
    return output
