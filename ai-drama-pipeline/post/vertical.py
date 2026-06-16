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
    """尝试检测视频中的人脸中心位置（多帧采样，取最大人脸）

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
        logger.warning("face_recognition 未安装，使用模糊背景模式（如需人脸追踪请 pip install face_recognition）")
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
                # 取面积最大的人脸（多人场景取主角，避免取到路人）
                best = max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
                top, right, bottom, left = best
                positions.append(((left + right) // 2, (top + bottom) // 2))
        cap.release()
        if not positions:
            return None
        # 取中位数位置（比平均值更鲁棒，不受人物移动偏移影响）
        positions.sort()
        mid = len(positions) // 2
        return (positions[mid][0], positions[mid][1])
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
    from infra.compute.ffmpeg import probe as ffprobe, ffmpeg_path
    ffmpeg = ffmpeg_path()

    Path(output).parent.mkdir(parents=True, exist_ok=True)

    # 获取原始尺寸
    info = ffprobe(video)
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    try:
        w = int(stream.get("width", 1280))
    except (ValueError, TypeError):
        w = 1280
    try:
        h = int(stream.get("height", 720))
    except (ValueError, TypeError):
        h = 720

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
            cx, cy = face_pos
            logger.info(f"检测到人脸中心: ({cx}, {cy})")
            # 以目标 9:16 比例计算裁剪区域
            crop_w = min(int(h * target_w / target_h), w)
            crop_h = min(int(w * target_h / target_w), h)
            crop_x = max(0, min(cx - crop_w // 2, w - crop_w))
            crop_y = max(0, min(cy - crop_h // 2, h - crop_h))
            vf = (f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}")
        else:
            logger.info("未检测到人脸，使用模糊背景模式")
            # 背景: 铺满 9:16 + 模糊；前景: 等比缩放适配 9:16 框，居中叠加
            vf = (f"split[main][blur_in];"
                  f"[blur_in]scale={target_w}:{target_h},boxblur=20[bg];"
                  f"[main]scale={target_w}:{target_h}"
                  f":force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2")

    cmd = [ffmpeg, "-y", "-i", video, "-vf", vf, "-c:a", "copy", output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"横转竖失败: {r.stderr[-300:]}")
    return output
