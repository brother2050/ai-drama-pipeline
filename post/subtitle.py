"""字幕生成 — SRT 格式（考虑转场重叠）"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["generate_srt"]


def _sanitize_dialogue(text: str) -> str:
    """清理台词中的特殊字符，防止破坏 SRT 格式"""
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def generate_srt(shots: list[dict], output: str, *,
                 transition_duration: float = 0.0,
                 bilingual: bool = False) -> str:
    """从分镜表生成 SRT 字幕"""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    lines = []
    idx = 1
    current_time = 0.0

    for i, shot in enumerate(shots):
        duration = _safe_duration(shot)
        start = current_time
        current_time += max(0.5, duration - transition_duration) if i > 0 and transition_duration > 0 else duration

        subtitle_text = _build_subtitle_text(shot, bilingual)
        if not subtitle_text:
            continue

        lines.append(f"{idx}\n{_format_srt_time(start)} --> {_format_srt_time(current_time)}\n{subtitle_text}\n")
        idx += 1

    _write_srt(output, lines)
    logger.info(f"字幕生成: {output} ({idx-1} 条{'，双语' if bilingual else ''})")
    return output


def _safe_duration(shot: dict) -> float:
    from infra.constants import clip_duration
    try:
        raw = float(shot.get("duration", 4))
    except (ValueError, TypeError):
        raw = 4.0
    return float(clip_duration(raw))


def _build_subtitle_text(shot: dict, bilingual: bool) -> str:
    """构建单条字幕文本（含可选双语）"""
    from engines.dialogue import parse_dialogue
    lines = parse_dialogue(shot.get("dialogue", ""))
    if not lines:
        return ""
    # 多人对话：每行 "角色名：台词"；单人：只输出台词
    if len(lines) == 1:
        dialogue = _sanitize_dialogue(lines[0].text)
    else:
        dialogue = _sanitize_dialogue("\n".join(f"{ln.speaker}：{ln.text}" for ln in lines))
    if not dialogue or set(dialogue) <= {".", "…"}:
        return ""
    if not bilingual:
        return dialogue
    dialogue_en = _sanitize_dialogue(shot.get("dialogue_en", ""))
    if dialogue_en and not set(dialogue_en) <= {".", "…"}:
        return f"{dialogue}\n{dialogue_en}"
    return dialogue


def _write_srt(output: str, lines: list[str]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(Path(output).parent), suffix=".srt.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(tmp, output)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _format_srt_time(seconds: float) -> str:
    seconds = max(0, round(seconds, 3))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000 + 0.5)  # +0.5 四舍五入
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
