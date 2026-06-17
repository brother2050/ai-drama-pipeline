"""共享常量 — 情绪/景别/运镜/后端状态的单一数据源

校验脚本和运行时引擎共用此模块，消除值域不一致问题。

EMOTION_MAP / SHOT_TYPE_MAP / CAMERA_MAP 从 config/system.yaml 的
presets.emotion_prompts / presets.shot_type_prompts / presets.camera_prompts
加载，不在此硬编码。
"""
from __future__ import annotations

__all__ = [
    "VALID_EMOTIONS", "EMOTION_MAP",
    "SHOT_TYPE_MAP", "VALID_SHOT_TYPES",
    "CAMERA_MAP", "VALID_CAMERAS",
    "IMAGE_EXTENSIONS", "IMAGE_GLOB_PATTERNS",
    "STATUS_PENDING", "STATUS_RUNNING", "STATUS_DONE", "STATUS_ERROR", "STATUS_SKIPPED",
    "STEP_TTS", "STEP_FIRST_FRAME", "STEP_VIDEO", "STEP_LIPSYNC",
    "clip_duration",
    "_BIBLE_STR_FIELDS", "_BIBLE_DICT_FIELDS", "_BIBLE_LIST_FIELDS",
]

# ══════════════════════════════════════════════════════════
#  Bible 字段分类（角色一致性数据）
# ══════════════════════════════════════════════════════════

_BIBLE_STR_FIELDS = ("core_traits", "speech_patterns", "voice_description")
_BIBLE_DICT_FIELDS = ("relationships", "emotional_range", "body_language")
_BIBLE_LIST_FIELDS = ("habits", "taboos")

# ══════════════════════════════════════════════════════════
#  管线步骤名（消除散落的字符串字面量）
# ══════════════════════════════════════════════════════════

STEP_TTS = "tts"
STEP_FIRST_FRAME = "first_frame"
STEP_VIDEO = "video"
STEP_LIPSYNC = "lipsync"

# ══════════════════════════════════════════════════════════
#  情绪 / 景别 / 运镜（从 config/system.yaml presets 加载）
# ══════════════════════════════════════════════════════════

def _load_prompt_maps():
    """从 system.yaml presets 加载生图 prompt 映射（唯一数据源）"""
    try:
        from infra.config.core import SYSTEM_CONFIG_PATH
        import os as _os
        if not _os.path.isfile(SYSTEM_CONFIG_PATH):
            return {}, {}, {}
        from infra.config import load_config
        cfg = load_config(SYSTEM_CONFIG_PATH)
        presets = cfg.get("presets", {})
        return (
            presets.get("emotion_prompts", {}),
            presets.get("shot_type_prompts", {}),
            presets.get("camera_prompts", {}),
        )
    except Exception:
        return {}, {}, {}

_em, _st, _ca = _load_prompt_maps()
EMOTION_MAP: dict[str, str] = _em
SHOT_TYPE_MAP: dict[str, str] = _st
CAMERA_MAP: dict[str, str] = _ca

VALID_EMOTIONS = frozenset(EMOTION_MAP.keys())
VALID_SHOT_TYPES = frozenset(SHOT_TYPE_MAP.keys())
VALID_CAMERAS = frozenset(CAMERA_MAP.keys())

# 图片文件扩展名（唯一数据源）
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
IMAGE_GLOB_PATTERNS = ("*.png", "*.jpg", "*.jpeg", "*.webp")


def check_emotion_sync() -> list[str]:
    """检查 TTS/配乐 emotion 映射是否与 system.yaml 同步，返回漂移警告列表"""
    warnings: list[str] = []
    if not VALID_EMOTIONS:
        return warnings
    try:
        from api.backends.tts._mimo_common import EMOTION_STYLE, EMOTION_STYLE_V2
        tts_missing = VALID_EMOTIONS - set(EMOTION_STYLE.keys())
        if tts_missing:
            warnings.append(f"TTS EMOTION_STYLE 缺少: {', '.join(sorted(tts_missing))}")
        v2_missing = VALID_EMOTIONS - set(EMOTION_STYLE_V2.keys())
        if v2_missing:
            warnings.append(f"TTS EMOTION_STYLE_V2 缺少: {', '.join(sorted(v2_missing))}")
    except Exception:
        pass
    try:
        from api.backends.music.musicgen import _MOOD_PROMPTS
        music_missing = VALID_EMOTIONS - set(_MOOD_PROMPTS.keys())
        if music_missing:
            warnings.append(f"MusicGen _MOOD_PROMPTS 缺少: {', '.join(sorted(music_missing))}")
    except Exception:
        pass
    return warnings

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

ERR_NOT_PREPARED = "请先在 Web 工作台执行「🔧 准备阶段」（批量翻译）"


# ══════════════════════════════════════════════════════════
#  Duration 工具
# ══════════════════════════════════════════════════════════

MIN_DURATION = 2
MAX_DURATION = 8

def clip_duration(raw: float | int | str | None, default: float = 4.0) -> float:
    """将 duration 裁剪到合法范围 [MIN_DURATION, MAX_DURATION]

    统一的 duration 处理逻辑，消除 pipeline/workflow_builder/shot_utils/seko 中的重复代码。
    返回 float 保留精度（如 3.5 秒不会被截断为 3）。
    """
    try:
        d = float(raw) if raw is not None else float(default)
    except (ValueError, TypeError):
        d = float(default)
    return max(float(MIN_DURATION), min(float(MAX_DURATION), d))
