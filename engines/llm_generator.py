"""LLM 内容生成引擎 — 从大纲生成分镜、角色、场景"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from engines.shot_utils import postprocess_shots as _postprocess_shots
from engines.prompt_compiler import tpl


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
           "expand_outline"]


# ══════════════════════════════════════════════════════════
#  分镜表生成
# ══════════════════════════════════════════════════════════


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
            traits = (c.get("bible") or {}).get("core_traits", "未指定")
            details.append(f"- {cid}（{cname}，{traits}{oi}）: {c.get('appearance', '')[:60]}")
        parts.append("\n=== 角色名映射 ===\n" + "\n".join(mapping))
        parts.append("\n=== 角色详情 ===\n" + "\n".join(details))

    if scenes:
        info = "\n".join(f"- {s.get('id', '?')}（{s.get('name', '?')}）: {s.get('description', '')[:60]}" for s in scenes)
        parts.append(f"\n=== 已有场景 ===\n{info}")

    parts.append(f"\n目标总时长约 {target_duration} 秒，每镜头 2-8 秒。")

    from infra.json_parse import llm_call_with_retry
    raw_shots = llm_call_with_retry(llm, "\n".join(parts), tpl("storyboard_system"), "分镜", max_tokens=4096)
    if not raw_shots or not isinstance(raw_shots, list):
        return []

    shots = _postprocess_shots(raw_shots, episode)

    # 镜头数合理性校验
    total_dur = sum(int(s.get("duration", 4)) for s in shots)
    expected_min = max(3, target_duration // 10)  # 每镜头最多 10 秒
    expected_max = target_duration // 2 + 5        # 每镜头最少 2 秒，留余量
    if len(shots) < expected_min:
        logger.warning(f"镜头数过少: {len(shots)}（预期 ≥{expected_min}），总时长可能不足 {target_duration}s")
    elif len(shots) > expected_max:
        logger.warning(f"镜头数过多: {len(shots)}（预期 ≤{expected_max}），可能超出目标时长")

    logger.info(f"生成 {len(shots)} 个镜头, 预计 {total_dur} 秒")
    return shots


# ══════════════════════════════════════════════════════════
#  角色 / 场景生成（共享逻辑）
# ══════════════════════════════════════════════════════════


def generate_characters(llm: object, descriptions: list[str], expected_ids: list[str] | None = None,
                        existing_characters: list[dict] | None = None) -> list[dict]:
    """从描述生成角色配置 — 全部成功或抛异常

    appearance_prompt_en 和 body_features 由准备阶段翻译生成，此处不处理。
    """
    from infra.models import normalize_character
    results = _generate_entities(llm, descriptions, expected_ids, tpl("character_system"), "角色",
                                 existing_entities=existing_characters, max_tokens=1024)
    for char in results:
        normalize_character(char)
    return results


def generate_scenes(llm: object, descriptions: list[str], expected_ids: list[str] | None = None,
                    existing_scenes: list[dict] | None = None) -> list[dict]:
    """从描述生成场景配置 — 全部成功或抛异常"""
    return _generate_entities(llm, descriptions, expected_ids, tpl("scene_system"), "场景",
                              existing_entities=existing_scenes, max_tokens=1024)


def _generate_entities(llm: object, descriptions: list[str], expected_ids: list[str] | None,
                       system: str, label: str, *, existing_entities: list[dict] | None = None,
                       max_tokens: int = 1024) -> list[dict]:
    """通用实体生成 — AdaptiveBatchProcessor 自适应分批 + 容错隔离"""
    from infra.batch_processor import AdaptiveBatchProcessor, estimate_tokens
    from infra.json_parse import parse_llm_json

    processor = AdaptiveBatchProcessor(llm)

    # 构建已有实体上下文（注入 LLM prompt 让其避撞）
    existing_ctx = ""
    if existing_entities:
        lines = [f"  - {e['id']}（{e['name']}）" for e in existing_entities]
        existing_ctx = f"=== 已有{label}（id 和 name 不可重复）===\n" + "\n".join(lines) + "\n\n"

    def build_prompts(batch):
        parts = []
        if existing_ctx:
            parts.append(existing_ctx)
        for i, desc in enumerate(batch):
            parts.append(f"[{label}{i+1}] {desc}")
        return {"system": system, "user": "\n\n".join(parts)}

    def parse_result(raw, batch):
        result = parse_llm_json(raw)
        # 模板已改为输出 JSON 数组，直接返回列表
        if isinstance(result, list):
            return result

        return None

    batch_result = processor.process(
        items=descriptions,
        build_prompts=build_prompts,
        parse_result=parse_result,
        estimate_item_tokens=lambda d: estimate_tokens(d) + 200,
        estimate_item_output_tokens=lambda _: max_tokens,
    )

    # 按 batch_sizes 精确展平，失败批次填 None 保持对齐
    entities: list[dict | None] = []
    for batch_data, batch_size in zip(batch_result["results"], batch_result["batch_sizes"]):
        if batch_data and isinstance(batch_data, list):
            entities.extend(batch_data)
        else:
            entities.extend([None] * batch_size)

    failed_count = sum(1 for e in entities if not isinstance(e, dict) or not e)
    if failed_count:
        raise RuntimeError(f"{label}生成失败（{failed_count}/{len(descriptions)}）: 请检查 LLM 服务。")

    # 校验 LLM 返回数量与请求数一致（防止 LLM 合并/丢失实体）
    if len(entities) != len(descriptions):
        raise RuntimeError(
            f"{label}生成数量不匹配：请求 {len(descriptions)} 个，实际返回 {len(entities)} 个。"
            f"LLM 可能合并了多个{label}为一个，请重试或减少单批数量。")

    # ID 注入 + 名称去重（包含已有实体名称，防止 LLM 生成重复名）
    used_names: set[str] = {e["name"] for e in (existing_entities or []) if e.get("name")}
    used_ids: set[str] = {e["id"] for e in (existing_entities or []) if e.get("id")}
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            continue
        if expected_ids and i < len(expected_ids):
            entity["id"] = expected_ids[i]
        # LLM 未返回 id 时生成默认 ID
        if not entity.get("id"):
            entity["id"] = f"{label}_{i+1}"
        # ID 去重：与已有实体 ID 冲突时生成新 ID
        eid = entity["id"]
        if eid in used_ids:
            n, orig = 2, eid
            while f"{eid}_{n}" in used_ids:
                n += 1
            entity["id"] = f"{eid}_{n}"
            logger.warning(f"  ⚠ {label}ID 冲突: {orig} → {entity['id']}")
        used_ids.add(entity["id"])
        # 名称去重
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


def expand_outline(llm: object, outline: str) -> str:
    """扩写简短大纲为详细版本"""
    if not outline.strip():
        return outline
    try:
        return llm.chat(outline, system=tpl("expand_outline_system"), max_tokens=2048)
    except Exception as e:
        logger.error(f"大纲扩写失败: {e}", exc_info=True)
        return outline


# ══════════════════════════════════════════════════════════
#  内部工具
# ══════════════════════════════════════════════════════════