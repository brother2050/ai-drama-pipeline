"""镜头工具函数 — 后处理、文本清理等共享逻辑"""
from __future__ import annotations

import logging
import re

from infra.constants import VALID_EMOTIONS, VALID_SHOT_TYPES, VALID_CAMERAS

logger = logging.getLogger(__name__)

__all__ = ["postprocess_shots", "strip_dialogue"]


def postprocess_shots(shots: list[dict], episode: int, *, strict: bool = False) -> list[dict]:
    """后处理镜头列表：去重 ID、校验字段、清理引号

    Args:
        shots: 原始镜头列表
        episode: 集数
        strict: True 时额外校验 shot_type/camera（Stage1 使用）
    """
    result = []
    used_ids: set[str] = set()

    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue

        # shot_id: 去重 + 格式校验
        sid = shot.get("shot_id", "")
        if not sid or not re.match(r"^\d{3}$", sid) or sid in used_ids:
            sid = f"{i + 1:03d}"
        shot["shot_id"] = sid
        used_ids.add(sid)

        shot["episode"] = episode

        # duration: 截断到 [2, 8]
        try:
            d = int(shot.get("duration", 4))
            shot["duration"] = max(2, min(8, d))
        except (ValueError, TypeError):
            shot["duration"] = 4

        # 清理引号
        for k in ("dialogue", "action_en", "dialogue_en"):
            val = shot.get(k, "")
            if val and len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                shot[k] = val[1:-1]

        # emotion 校验
        if shot.get("emotion", "neutral") not in VALID_EMOTIONS:
            shot["emotion"] = "neutral"

        # strict 模式：额外校验 shot_type / camera
        if strict:
            if shot.get("shot_type", "") and shot["shot_type"] not in VALID_SHOT_TYPES:
                shot["shot_type"] = "中景"
            if shot.get("camera", "") and shot["camera"] not in VALID_CAMERAS:
                shot["camera"] = "固定"

        result.append(shot)
    return result


def strip_dialogue(text: str) -> str:
    """清理 action 中的对话/台词内容，防止模型将文字渲染进画面

    只清理紧跟对话动词的引号内容（说/道/喊/问/答/叫 等），
    保留场景道具上的文字描述（如墙上"欢迎光临"、杯子上"Best Day Ever"）。
    """
    if not text:
        return text
    # 英文：动词 + 引号/冒号内容（覆盖 says/asked/replied 等常见形式）
    _SPEECH = r'(?:sa(?:ys|id)|ask(?:s|ed)|answer(?:s|ed)|repli(?:es|ed)|shout(?:s|ed)|yell(?:s|ed)|whisper(?:s|ed)|mutter(?:s|ed)|scream(?:s|ed)|exclaim(?:s|ed)|respond(?:s|ed)|call(?:s|ed)|demand(?:s|ed))'
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    # 中文：[主语][动作]对话动词[：]["内容"]
    _VERB = r'[说喊道问答呼吼叫骂叹叫嚷]'
    _PRE = r'(?:[他她我你您它們们]|\w{0,4})'
    text = re.sub(rf'(?:^|[，。,.、\s])\s*{_PRE}\s*{_VERB}{{1,3}}[着道了口气声]*\s*[：:]?\s*[""「].*?[""」]', '', text)
    text = re.sub(rf'(?:^|[，。,.、\s])\s*{_PRE}\s*{_VERB}{{1,3}}[着道了口气声]*\s*[：:]\s*[^，。,.]{{0,30}}[，。,.]?\s*', '', text)
    text = re.sub(r'[他她我你您它們们]?\s*[：:]\s*[""「].*?[""」]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
