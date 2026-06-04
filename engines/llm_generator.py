"""LLM 内容生成引擎 — 从大纲生成分镜、角色、场景"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from engines.shot_utils import postprocess_shots as _postprocess_shots
from engines.prompt_compiler import get_compiler


def _tpl(key: str) -> str:
    """从 prompt_templates.yaml 加载模板"""
    return get_compiler().get(key)


@dataclass
class StoryboardGenParams:
    """分镜生成参数 — 统一参数对象，消除多参数函数"""
    outline: str = ""
    characters: list[dict] = field(default_factory=list)
    scenes: list[dict] = field(default_factory=list)
    episode: int = 1
    target_duration: int = 90
    style: str = ""
    genre: str = ""
    on_stage_progress: object = None  # (stage, total, name) 回调

logger = logging.getLogger(__name__)

__all__ = ["StoryboardGenParams", "generate_storyboard", "generate_characters", "generate_scenes",
           "expand_outline", "generate_storyboard_multistage"]


# ══════════════════════════════════════════════════════════
#  分镜表生成
# ══════════════════════════════════════════════════════════

STORYBOARD_SYSTEM = _tpl("storyboard_system")


def generate_storyboard(llm: object, params: StoryboardGenParams) -> list[dict]:
    """从剧情大纲生成分镜表"""
    outline, characters, scenes = params.outline, params.characters, params.scenes
    episode, target_duration = params.episode, params.target_duration
    style, genre = params.style, params.genre
    # 构建上下文
    parts = [f"=== 第{episode}集 剧情大纲 ===\n{outline}"]

    if style or genre:
        info = []
        if style:
            info.append(f"视觉风格: {style}")
        if genre:
            info.append(f"题材类型: {genre}")
        parts.append(f"\n=== 创作方向 ===\n" + "，".join(info))

    if characters:
        mapping = []
        details = []
        for c in characters:
            cid, cname = c.get("id", "?"), c.get("name", cid)
            mapping.append(f"  {cid} → {cname}")
            outfits = c.get("outfits", {})
            keys = list(outfits.keys()) if isinstance(outfits, dict) else []
            oi = f"，可选服装：{'/'.join(keys)}" if keys else ""
            traits = (c.get("bible") or {}).get("core_traits", "未指定")
            details.append(f"- {cid}（{cname}，{traits}{oi}）: {c.get('appearance', '')[:60]}")
        parts.append(f"\n=== 角色名映射 ===\n" + "\n".join(mapping))
        parts.append(f"\n=== 角色详情 ===\n" + "\n".join(details))

    if scenes:
        info = "\n".join(f"- {s.get('id', '?')}（{s.get('name', '?')}）: {s.get('description', '')[:60]}" for s in scenes)
        parts.append(f"\n=== 已有场景 ===\n{info}")

    parts.append(f"\n目标总时长约 {target_duration} 秒，每镜头 2-8 秒。")

    from infra.json_parse import llm_call_with_retry
    raw_shots = llm_call_with_retry(llm, "\n".join(parts), STORYBOARD_SYSTEM, "分镜", max_tokens=4096)
    if not raw_shots or not isinstance(raw_shots, list):
        return []

    shots = _postprocess_shots(raw_shots, episode)
    logger.info(f"生成 {len(shots)} 个镜头, 预计 {sum(int(s.get('duration', 4)) for s in shots)} 秒")
    return shots


# ══════════════════════════════════════════════════════════
#  角色 / 场景生成（共享逻辑）
# ══════════════════════════════════════════════════════════

CHARACTER_SYSTEM = _tpl("character_system")

SCENE_SYSTEM = _tpl("scene_system")


def generate_characters(llm: object, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成角色配置 — 全部成功或抛异常"""
    results = _generate_entities(llm, descriptions, expected_ids, CHARACTER_SYSTEM, "角色", max_tokens=1024)
    for char in results:
        from infra.models import normalize_character
        normalize_character(char)
    return results


def generate_scenes(llm: object, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成场景配置 — 全部成功或抛异常"""
    return _generate_entities(llm, descriptions, expected_ids, SCENE_SYSTEM, "场景", max_tokens=1024)


def _generate_entities(llm: object, descriptions: list[str], expected_ids: list[str] | None,
                       system: str, label: str, max_tokens: int = 1024) -> list[dict]:
    """通用实体生成 — AdaptiveBatchProcessor 自适应分批 + 容错隔离"""
    from infra.batch_processor import AdaptiveBatchProcessor, estimate_tokens
    from infra.json_parse import parse_llm_json

    processor = AdaptiveBatchProcessor(llm)

    def build_prompts(batch):
        parts = [f"[{label}{i+1}] {desc}" for i, desc in enumerate(batch)]
        return {"system": system, "user": "\n\n".join(parts)}

    def parse_result(raw, batch):
        result = parse_llm_json(raw)
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else None

    batch_result = processor.process(
        items=descriptions,
        build_prompts=build_prompts,
        parse_result=parse_result,
        estimate_item_tokens=lambda d: estimate_tokens(d) + 200,
        estimate_item_output_tokens=lambda _: max_tokens,
    )

    entities = []
    for batch_data in batch_result["results"]:
        if batch_data:
            entities.extend(batch_data)

    failed_count = sum(1 for d, e in zip(descriptions, entities) if e is None or not isinstance(e, dict))
    if failed_count:
        raise RuntimeError(f"{label}生成失败（{failed_count}/{len(descriptions)}）: 请检查 LLM 服务。")

    # ID 注入 + 名称去重
    used_names: set[str] = set()
    for i, entity in enumerate(entities):
        if expected_ids and i < len(expected_ids):
            entity["id"] = expected_ids[i]
        name = entity.get("name", "").strip()
        if name in used_names:
            n, orig = 2, name
            while f"{name}{n}" in used_names:
                n += 1
            entity["name"] = f"{name}{n}"
            logger.warning(f"  ⚠ {label}名重复: {orig} → {entity['name']}")
        used_names.add(entity["name"])
        logger.info(f"  ✅ 生成{label}: {entity.get('name', '?')} ({entity.get('id', '?')})")

    return entities


# ══════════════════════════════════════════════════════════
#  大纲扩写
# ══════════════════════════════════════════════════════════

EXPAND_SYSTEM = _tpl("expand_outline_system")


def expand_outline(llm: object, outline: str) -> str:
    """扩写简短大纲为详细版本"""
    if not outline.strip():
        return outline
    try:
        return llm.chat(outline, system=EXPAND_SYSTEM, max_tokens=2048)
    except Exception as e:
        logger.error(f"大纲扩写失败: {e}", exc_info=True)
        return outline


# ══════════════════════════════════════════════════════════
#  多阶段分镜生成
# ══════════════════════════════════════════════════════════

def generate_storyboard_multistage(llm: object, params: StoryboardGenParams) -> list[dict]:
    """多阶段分镜生成（推荐）

    将一次 LLM 调用拆分为 3 个聚焦阶段，每阶段独立重试，
    降低 token 压力，提升输出质量。
    如果多阶段失败，自动回退到单次生成。
    """
    try:
        from engines.shot_calibrator import calibrate_storyboard
        return calibrate_storyboard(llm, params=params)
    except Exception as e:
        logger.warning(f"多阶段生成失败，回退到单次生成: {e}")
        return generate_storyboard(llm, params=params)


# ══════════════════════════════════════════════════════════
#  内部工具
# ══════════════════════════════════════════════════════════
