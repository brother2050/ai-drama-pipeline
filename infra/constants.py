"""共享常量 — 情绪/景别/运镜/后端状态的单一数据源

校验脚本和运行时引擎共用此模块，消除值域不一致问题。
"""
from __future__ import annotations

__all__ = [
    "VALID_EMOTIONS", "EMOTION_MAP",
    "SHOT_TYPE_MAP", "VALID_SHOT_TYPES",
    "CAMERA_MAP", "VALID_CAMERAS",
    "STATUS_PENDING", "STATUS_RUNNING", "STATUS_DONE", "STATUS_ERROR", "STATUS_SKIPPED",
]

# ══════════════════════════════════════════════════════════
#  情绪
# ══════════════════════════════════════════════════════════

VALID_EMOTIONS = frozenset({
    "angry", "sad", "happy", "worried", "surprised", "smug",
    "serious", "calm", "determined", "fearful", "neutral", "romantic", "action",
})

EMOTION_MAP: dict[str, str] = {
    "angry": "angry, furrowed brows, clenched jaw",
    "sad": "sad, teary eyes, downturned mouth",
    "happy": "happy, bright smile, sparkling eyes",
    "worried": "worried, anxious expression, biting lip",
    "surprised": "surprised, wide eyes, open mouth",
    "smug": "smug, slight smirk, raised chin",
    "serious": "serious, focused expression, firm gaze",
    "calm": "calm, serene expression, relaxed posture",
    "determined": "determined, intense gaze, set jaw",
    "fearful": "fearful, trembling, wide eyes",
    "neutral": "neutral expression, natural pose",
    "romantic": "romantic, soft gaze, gentle smile",
    "action": "action pose, intense expression, dynamic",
}

# ══════════════════════════════════════════════════════════
#  景别
# ══════════════════════════════════════════════════════════

SHOT_TYPE_MAP: dict[str, str] = {
    "特写": "extreme close-up shot, detailed face, looking at viewer",
    "近景": "close-up shot, head and shoulders",
    "中景": "medium shot, waist up",
    "过肩": "over-the-shoulder shot",
    "全身": "full body shot",
    "全景": "wide shot, full scene",
    "远景": "extreme wide shot, establishing shot",
    "双人全景": "two-shot, both characters visible",
    "侧面特写": "side profile close-up shot, detailed side view of face, looking left, from the side",
    "背面特写": "back view close-up shot, seen from behind, back of head, facing away from viewer",
}

VALID_SHOT_TYPES = frozenset(SHOT_TYPE_MAP.keys())

# ══════════════════════════════════════════════════════════
#  运镜
# ══════════════════════════════════════════════════════════

CAMERA_MAP: dict[str, str] = {
    "固定": "static camera",
    "缓慢推近": "slow zoom in, dolly in",
    "跟随平移": "tracking shot, pan",
    "手持晃动": "handheld camera, slight shake",
    "环绕": "orbiting camera, 360 degree",
    "俯视": "top-down shot, bird's eye view",
    "仰视": "low angle shot, looking up",
}

VALID_CAMERAS = frozenset(CAMERA_MAP.keys())

# ══════════════════════════════════════════════════════════
#  管线状态
# ══════════════════════════════════════════════════════════

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# ══════════════════════════════════════════════════════════
#  通用错误消息（消除重复字符串）
# ══════════════════════════════════════════════════════════

ERR_NOT_PREPARED = "请先执行: drama prepare <集数>"
ERR_NOT_PREPARED_CN = ERR_NOT_PREPARED  # 合并为统一中文消息


# ══════════════════════════════════════════════════════════
#  文本工具
# ══════════════════════════════════════════════════════════

def contains_non_ascii(text: str) -> bool:
    """检查文本是否包含非 ASCII 字符（中文、日文、韩文等）"""
    return not text.isascii()


def is_ascii_only(text: str) -> bool:
    """检查文本是否只包含 ASCII 字符"""
    return text.isascii()
