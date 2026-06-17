"""LLM 内容生成引擎 — 分镜表生成"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from engines.utils.shot import postprocess_shots as _postprocess_shots
from engines.prompt.compiler import tpl

logger = logging.getLogger(__name__)

__all__ = ["StoryboardGenParams", "generate_storyboard"]


@dataclass
class StoryboardGenParams:
    """分镜生成参数"""
    outline: str = ""
    characters: list[dict] = field(default_factory=list)
    scenes: list[dict] = field(default_factory=list)
    episode: int = 1
    target_duration: int = 90
    style: str = ""
    genre: str = ""
    on_stage_progress: object = None


def _load_storyboard_presets(style: str = "", genre: str = "") -> dict:
    """从 system.yaml 加载预设枚举值"""
    from infra.config import SYSTEM_CONFIG_PATH, load_yaml_full
    from pathlib import Path

    presets = {"shot_types": "", "cameras": "", "emotions": "",
               "style": style, "style_desc": "", "genre": genre, "genre_desc": ""}
    sys_path = Path(SYSTEM_CONFIG_PATH)
    if not sys_path.exists():
        return presets
    try:
        sys_cfg = load_yaml_full(sys_path)
    except Exception:
        return presets
    p = sys_cfg.get("presets", {})
    presets["shot_types"] = "、".join(f"{k}: {v}" for k, v in p.get("shot_types", {}).items()) or ""
    presets["cameras"] = "、".join(f"{k}: {v}" for k, v in p.get("cameras", {}).items()) or ""
    presets["emotions"] = "、".join(f"{k}: {v}" for k, v in p.get("emotions", {}).items()) or ""
    if style:
        presets["style_desc"] = p.get("styles", {}).get(style, "")
    if genre:
        presets["genre_desc"] = p.get("genres", {}).get(genre, "")
    return presets


def _compute_storyboard_max_tokens(llm: object, target_duration: int, character_count: int = 0) -> int:
    """根据目标时长动态计算 max_tokens，确保 LLM 有足够输出空间"""
    # 估算镜头数：目标时长 / 4 秒（保守估计每个镜头 4s）
    estimated_shots = max(10, target_duration // 4)
    # 每个镜头 JSON 约 250-400 字符，中文字符约 1-1.5 token/字
    estimated_tokens = estimated_shots * 350
    # 角色/场景上下文额外开销
    context_overhead = character_count * 50
    # 读取模型限制作为上限
    from infra.json_parse import get_max_output_tokens
    model_max = get_max_output_tokens(llm, default=4096)
    # Qwen3 等 thinking 模型需要额外 50% token 用于推理
    is_thinking_model = False
    try:
        from infra.config.registry import ModelRegistry
        is_thinking_model = ModelRegistry().is_thinking_model(getattr(llm, "_model", ""))
    except Exception:
        logger.error("检查模型是否为 thinking 模型时出错")
    if is_thinking_model:
        estimated_tokens = int(estimated_tokens * 1.5)
    result = min(estimated_tokens + context_overhead, model_max)
    logger.info(f"分镜 max_tokens 估算: shots≈{estimated_shots}, tokens≈{estimated_tokens}, model_max={model_max}, final={result}")
    return max(result, 4096)


def generate_storyboard(llm: object, params: StoryboardGenParams) -> tuple[list[dict], list[str]]:
    """从剧情大纲生成分镜表"""
    outline, characters, scenes = params.outline, params.characters, params.scenes
    episode, target_duration = params.episode, params.target_duration
    style, genre = params.style, params.genre
    warnings: list[str] = []
    parts = [f"=== 第{episode}集 剧情大纲 ===\n{outline}"]

    if style or genre:
        info = []
        if style:
            info.append(f"视觉风格: {style}")
        if genre:
            info.append(f"题材类型: {genre}")
        parts.append("\n=== 创作方向 ===\n" + "，".join(info))

    if characters:
        mapping = []
        details = []
        for c in characters:
            cid = c.get("id", "?")
            cname = c.get("name", cid)
            mapping.append(f"  {cid} → {cname}")
            outfits = c.get("outfits", {})
            keys = list(outfits.keys()) if isinstance(outfits, dict) else []
            oi = f"，可选服装：{'/'.join(keys)}" if keys else ""
            bible = c.get("bible") or {}
            traits = bible.get("core_traits", "未指定")
            voice = bible.get("voice_description", "")
            voice_part = f"，声音：{voice}" if voice else ""
            # 人际关系：仅在已有数据时注入（先分镜后角色的流程中可能为空）
            rels = bible.get("relationships") or {}
            rels_part = ""
            if rels:
                rels_items = [f"与{k}{v}" for k, v in rels.items()]
                rels_part = f"，人际关系：{'，'.join(rels_items)}"
            details.append(f"- {cid}（{cname}，{traits}{voice_part}{rels_part}{oi}）: {c.get('appearance', '')[:300]}")
        parts.append("\n=== 角色名映射 ===\n" + "\n".join(mapping))
        parts.append("\n=== 角色详情 ===\n" + "\n".join(details))

    if scenes:
        info = "\n".join(f"- {s.get('id', '?')}（{s.get('name', '?')}）: {s.get('description', '')[:200]}" for s in scenes)
        parts.append(f"\n=== 已有场景 ===\n{info}")

    presets = _load_storyboard_presets(style, genre)
    parts.append(f"\n=== 可选值 ===\n景别：{presets['shot_types']}\n运镜：{presets['cameras']}\n情绪：{presets['emotions']}")

    estimated_duration = target_duration
    parts.append(f"\n=== 要求 ===\n目标时长：约 {estimated_duration} 秒\n每镜头 2-8 秒\nshot_id 从 001 开始递增")

    user_msg = "\n".join(parts)
    system = tpl("storyboard_system")
    logger.info(f"生成分镜: outline={len(outline)}字, chars={len(characters)}, scenes={len(scenes)}, target={estimated_duration}s")

    max_tokens = _compute_storyboard_max_tokens(llm, estimated_duration, len(characters))
    raw = llm.chat(user_msg, system=system, max_tokens=max_tokens)
    from infra.json_parse import parse_llm_json
    parsed = parse_llm_json(raw)
    if parsed is None:
        raise RuntimeError("分镜解析失败: LLM 输出不是有效 JSON。")

    if isinstance(parsed, dict):
        parsed = parsed.get("shots", [])
    if not isinstance(parsed, list):
        raise RuntimeError(f"分镜格式错误: 期望 list，得到 {type(parsed).__name__}")

    shots = _postprocess_shots(parsed, params.episode)
    expected_min = max(1, estimated_duration // 8)
    if len(shots) < expected_min:
        warnings.append(f"镜头数过少: {len(shots)}（预期 ≥{expected_min}），LLM 输出可能被截断")
        logger.warning(f"镜头数过少: {len(shots)}（预期 ≥{expected_min}），请检查大纲或调大目标时长")

    logger.info(f"生成 {len(shots)} 个镜头, 预计 {sum(int(s.get('duration', 4)) for s in shots)} 秒")
    return shots, warnings
