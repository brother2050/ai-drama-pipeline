"""镜头工具函数 — 后处理、文本清理等共享逻辑"""
from __future__ import annotations

import logging
import re

from infra.constants import VALID_EMOTIONS, VALID_SHOT_TYPES, VALID_CAMERAS

logger = logging.getLogger(__name__)

__all__ = ["postprocess_shots", "strip_dialogue", "parse_char_names"]


def parse_char_names(shot: dict) -> list[str]:
    """从镜头数据中解析角色名称列表（"+" 分隔）

    Args:
        shot: 镜头数据 dict，含 "characters" 字段

    Returns:
        角色名称列表（已 strip + 去空）
    """
    raw = shot.get("characters", "")
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if c is not None and str(c).strip()]
    if not isinstance(raw, str):
        raw = str(raw) if raw is not None else ""
    return [c.strip() for c in raw.split("+") if c.strip()]


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

        # 统一归一化字符串字段（防止 YAML/LLM 返回 None/int 等非字符串值）
        for _str_key in ("shot_id", "action", "dialogue", "dialogue_en", "action_en", "emotion",
                         "shot_type", "camera", "characters", "scene_name", "outfit"):
            _v = shot.get(_str_key)
            if not isinstance(_v, str):
                shot[_str_key] = str(_v) if _v is not None else ""

        # shot_id: 格式校验 → 去重
        sid = shot.get("shot_id", "")
        if not sid or not re.match(r"^\d{3}$", sid):
            sid = f"{i + 1:03d}"
        if sid in used_ids:
            n = i + 2
            while f"{n:03d}" in used_ids:
                n += 1
            sid = f"{n:03d}"
        shot["shot_id"] = sid
        used_ids.add(sid)

        shot["episode"] = episode

        # duration: 截断到合法范围
        from infra.constants import clip_duration
        shot["duration"] = clip_duration(shot.get("duration"))

        # dialogue 归一化：空字符串 → "......"（管线约定无台词占位符）
        # 注意：只对 dialogue 中文字段做占位，dialogue_en 留空等翻译阶段补全
        if not shot.get("dialogue", "").strip():
            shot["dialogue"] = "......"

        # dialogue 归一化："角色名：......" → 移除空台词行（LLM 有时在省略号前加角色名）
        # 从 parse 结果重建，过滤掉纯省略号行
        if shot.get("dialogue") and shot["dialogue"] != "......":
            from engines.dialogue import parse_dialogue
            lines = parse_dialogue(shot["dialogue"])
            if not lines:
                shot["dialogue"] = "......"
            elif len(lines) < len(shot["dialogue"].split("\n")):
                # 部分行被过滤，重建
                shot["dialogue"] = "\n".join(f"{ln.speaker}\uff1a{ln.text}" for ln in lines)

        # 清理 dialogue/dialogue_en 中的 shot_id 前缀
        # LLM 有时误将 shot_id 混入角色名（如 "狮虎兽_001：台词" → "狮虎兽：台词"）
        for _dlg_key in ("dialogue", "dialogue_en"):
            _dlg = shot.get(_dlg_key, "")
            if _dlg and _dlg != "......":
                _dlg = re.sub(r"_\d{3}([：:])", r"\1", _dlg)   # 角色名_数字：→ 角色名：
                _dlg = re.sub(r"^\d{3}[：:]\s*", "", _dlg)       # 纯数字：→ 去除
                shot[_dlg_key] = _dlg

        # 清理引号（含中文引号）：剥离外层匹配引号对 + 残留的未闭合引号
        for k in ("dialogue", "action_en", "dialogue_en"):
            val = shot.get(k, "")
            if not val or len(val) < 2:
                continue
            pairs = [("\"", "\""), ("'", "'"), ("\u201c", "\u201d"), ("\u300c", "\u300d")]
            for open_q, close_q in pairs:
                # 剥离外层匹配引号对（可能多层嵌套，循环剥离）
                while len(val) >= 2 and val[0] == open_q and val[-1] == close_q:
                    val = val[1:-1].strip()
            # 剥离残留的未闭合引号（仅当匹配引号对不存在时）
            for open_q, close_q in pairs:
                if val and val[0] == open_q and close_q not in val[1:]:
                    val = val[1:].strip()
                if val and val[-1] == close_q and open_q not in val[:-1]:
                    val = val[:-1].strip()
            if val:
                shot[k] = val

        # emotion 校验（LLM 可能返回首字母大写如 "Happy"，统一小写后匹配）
        emotion = shot.get("emotion", "neutral").lower()
        shot["emotion"] = emotion if emotion in VALID_EMOTIONS else "neutral"

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
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    if not text:
        return text
    # 英文：动词 + 引号/冒号内容（覆盖 says/asked/replied 等常见形式）
    _SPEECH = r'(?:sa(?:ys|id)|ask(?:s|ed)|answer(?:s|ed)|repli(?:es|ed)|shout(?:s|ed)|yell(?:s|ed)|whisper(?:s|ed)|mutter(?:s|ed)|scream(?:s|ed)|exclaim(?:s|ed)|respond(?:s|ed)|call(?:s|ed)|demand(?:s|ed))'
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    # 中文：[主语][动作]对话动词[：]["内容"]
    _VERB = r'(?:嘟囔|嘀咕|唠叨|念叨|絮叨|嚷嚷|咆哮|嘶吼|低语|呢喃|自言自语|[说喊道问答呼吼叫骂叹叫嚷讲念])'
    _PRE = r'(?:[他她我你您它們们]|\w{1,4})'
    text = re.sub(rf'(?:^|[，。,.、\s])\s*{_PRE}\s*{_VERB}{{1,3}}[着道了口气声]*\s*[：:]?\s*[""「].*?[""」]', '', text)
    text = re.sub(rf'(?:^|[，。,.、\s])\s*{_PRE}\s*{_VERB}{{1,3}}[着道了口气声]*\s*[：:]\s*[^，。,.]{{0,30}}[，。,.]?\s*', '', text)
    text = re.sub(r'[他她我你您它們们]?\s*[：:]\s*[""「].*?[""」]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
