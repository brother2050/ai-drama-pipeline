"""多阶段分镜校准 — 将一次 LLM 调用拆分为多个聚焦阶段

将分镜生成拆分为 3 个独立阶段，每阶段聚焦少量字段，
降低单次调用的 token 压力，提升输出质量。

Stage 1: 叙事骨架 — shot_id/scene_id/characters/camera/shot_type/duration/emotion/outfit
Stage 2: 视觉描述 — action/dialogue/action_en/dialogue_en
Stage 3: AI 绘图 prompt — image_prompt_en（自然语言风格）
"""
from __future__ import annotations

import json
import logging
import re

from infra.json_parse import llm_call_with_retry
from engines.shot_utils import postprocess_shots as _postprocess_stage1
from engines.prompt_compiler import tpl

logger = logging.getLogger(__name__)

__all__ = ["calibrate_storyboard"]


# ══════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════

def calibrate_storyboard(llm: object, params: object) -> list[dict]:
    """多阶段分镜校准（3 阶段：叙事骨架 → 视觉描述 → AI 绘图 Prompt）"""
    outline = params.outline
    characters = params.characters or []
    scenes = params.scenes or []
    episode = params.episode
    target_duration = params.target_duration
    style, genre = params.style, params.genre
    on_stage_progress = params.on_stage_progress

    context = _build_context(outline, characters, scenes, target_duration, style, genre)

    # Stage 1: 叙事骨架
    if on_stage_progress:
        on_stage_progress(1, 3, "叙事骨架")
    logger.info("Stage 1/3: 叙事骨架...")
    skeleton = llm_call_with_retry(llm, context, tpl("shot_stage1_system"), "叙事骨架", max_tokens=4096)
    if not skeleton or not isinstance(skeleton, list):
        reason = "LLM 返回空" if not skeleton else f"LLM 返回非列表类型: {type(skeleton).__name__}"
        logger.error(f"Stage 1 失败（{reason}），回退到单次生成")
        return _fallback_generate(llm, params)

    shots = _postprocess_stage1(skeleton, episode, strict=True)
    logger.info(f"  ✅ 叙事骨架: {len(shots)} 个镜头")

    # Stage 2: 视觉描述
    if on_stage_progress:
        on_stage_progress(2, 3, "视觉描述")
    logger.info("Stage 2/3: 视觉描述...")
    enriched = _enrich_stage(llm, shots, tpl("shot_stage2_system"), "视觉描述", required_fields=["action", "dialogue"])
    if enriched:
        shots = enriched
        logger.info("  ✅ 视觉描述完成")
    else:
        logger.warning("  ⚠ 视觉描述失败，Stage 3 将使用骨架数据继续")

    # Stage 3: AI 绘图 Prompt（Stage 2 失败时仍可继续，因为 image_prompt_en 由 Stage 3 独立生成）
    if on_stage_progress:
        on_stage_progress(3, 3, "AI 绘图 Prompt")
    logger.info("Stage 3/3: AI 绘图 Prompt...")
    enriched = _enrich_stage(llm, shots, tpl("shot_stage3_system"), "AI 绘图", required_fields=["image_prompt_en"])
    if enriched:
        shots = enriched
        logger.info("  ✅ AI 绘图 Prompt 完成")
    else:
        logger.warning("  ⚠ AI 绘图 Prompt 失败（不影响生产，prepare 阶段会补充）")

    total_sec = sum(round(float(s.get("duration", 4))) for s in shots)
    logger.info(f"多阶段校准完成: {len(shots)} 镜头, {total_sec}秒")
    return shots


# ══════════════════════════════════════════════════════════
#  内部实现
# ══════════════════════════════════════════════════════════

def _build_context(outline: str, characters: list[dict], scenes: list[dict], target_duration: int, style: str, genre: str) -> str:
    """构建共享上下文（各阶段复用）"""
    parts = [f"=== 剧情大纲 ===\n{outline}"]

    if style or genre:
        info = []
        if style:
            info.append(f"视觉风格: {style}")
        if genre:
            info.append(f"题材类型: {genre}")
        parts.append("\n=== 创作方向 ===\n" + "，".join(info))

    if characters:
        mapping = []
        for c in characters:
            cid = c.get("id", "?")
            cname = c.get("name", cid)
            outfits = c.get("outfits", {})
            keys = list(outfits.keys()) if isinstance(outfits, dict) else []
            oi = f"，服装: {'/'.join(keys)}" if keys else ""
            traits = (c.get("bible") or {}).get("core_traits", "")
            mapping.append(f"  {cid} → {cname}（{traits}）{oi}")
        parts.append("\n=== 角色 ===\n" + "\n".join(mapping))

    if scenes:
        info = "\n".join(f"- {s.get('id', '?')}（{s.get('name', '?')}）: {s.get('description', '')[:60]}" for s in scenes)
        parts.append(f"\n=== 场景 ===\n{info}")

    parts.append(f"\n目标总时长约 {target_duration} 秒，每镜头 2-8 秒。")
    return "\n".join(parts)


def _enrich_stage(llm: object, shots: list[dict], system: str, label: str, required_fields: list[str] | None = None, max_missing_ratio: float = 0.2) -> list[dict] | None:
    """对已有镜头列表执行一次 LLM 补充调用

    Args:
        shots: 已有镜头列表
        system: 系统提示
        label: 日志标签
        required_fields: 必须存在的字段（缺少则视为失败）
        max_missing_ratio: 缺失字段比例阈值，超过则视为失败（默认 0.2）

    Returns:
        补充后的镜头列表，或 None（失败时）
    """
    if not shots:
        return None

    # 构建输入：只传必要字段，减少 token
    slim_shots = []
    for s in shots:
        slim = {"shot_id": s.get("shot_id", "")}
        for key in ("scene_id", "characters", "emotion", "shot_type", "camera",
                     "action", "dialogue", "action_en", "dialogue_en", "outfit", "duration"):
            if s.get(key):
                slim[key] = s[key]
        slim_shots.append(slim)

    prompt = json.dumps(slim_shots, ensure_ascii=False, indent=1)
    result = llm_call_with_retry(llm, prompt, system, label, max_tokens=4096)

    if not result or not isinstance(result, list):
        if not result:
            logger.warning(f"  {label}: LLM 返回空")
        else:
            logger.warning(f"  {label}: LLM 返回非列表类型: {type(result).__name__}")
        return None

    # 按 shot_id 合并（规范化为三位数格式，防止 LLM 返回 "1" 而原始是 "001"）
    result_map = {}
    for item in result:
        if isinstance(item, dict):
            sid = item.get("shot_id", "")
            if sid:
                # 统一为三位数格式（支持 "1" → "001"、"s001" → "001" 等变体）
                try:
                    sid = f"{int(sid):03d}"
                except (ValueError, TypeError):
                    digits = re.search(r'\d+', str(sid))
                    if digits:
                        sid = f"{int(digits.group()):03d}"
                result_map[sid] = item

    merged = []
    unmatched = []
    for i, shot in enumerate(shots):
        sid = shot.get("shot_id", "")
        update = result_map.get(sid, {})
        if not update:
            unmatched.append(sid)
        merged.append({**shot, **update})
    if unmatched:
        logger.warning(f"  {label}: {len(unmatched)}/{len(shots)} 个镜头未匹配 LLM 结果: {unmatched[:5]}{'...' if len(unmatched) > 5 else ''}")

    # 校验必填字段
    if required_fields:
        missing = 0
        for s in merged:
            for f in required_fields:
                if not s.get(f):
                    missing += 1
                    break
        threshold = int(max_missing_ratio * 100)
        if missing > len(merged) * max_missing_ratio:
            logger.warning(f"  {label}: 超过 {threshold}% 镜头缺少必填字段 {required_fields}，视为失败")
            return None

    return merged


def _fallback_generate(llm: object, params: object) -> list[dict]:
    """回退到单次生成（calibrate 不可用时）"""
    from engines.llm_generator import generate_storyboard, StoryboardGenParams
    return generate_storyboard(llm, StoryboardGenParams(
        outline=params.outline, characters=params.characters or [],
        scenes=params.scenes or [], episode=params.episode,
        target_duration=params.target_duration,
        style=params.style, genre=params.genre))
