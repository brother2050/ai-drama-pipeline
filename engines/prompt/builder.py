"""Prompt 工程引擎 — 核心构建功能"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from infra.concurrency.batch import estimate_tokens as _estimate_tokens
from engines.prompt.compiler import tpl

logger = logging.getLogger(__name__)

__all__ = [
    "PromptBuildParams", "batch_generate_appearance_prompts", "build_prompt",
]


@dataclass
class PromptBuildParams:
    """Prompt 构建参数"""
    shot: dict = field(default_factory=dict)
    character_desc: str = ""
    scene_desc: str = ""
    style: str = "cinematic"
    genre: str = "urban"
    image_backend: str = ""
    registry: object = None
    character_bible: str = ""
    scene_data: dict = field(default_factory=dict)


_BODY_FEATURE_KEYWORDS = {
    "scar", "tattoo", "birthmark", "burn", "freckle", "mole",
    "bruise", "wound", "prosthetic", "amputee", "blind", "deaf",
    "bandage", "stitch", "piercing", "eyepatch", "brace", "cast",
    "splint", "prosthesis", "limp", "hunchback",
}


def _extract_body_features(prompt_en: str) -> str:
    """从英文 prompt 中提取身体特征短语"""
    parts = [p.strip() for p in prompt_en.split(",") if p.strip()]
    features = []
    for part in parts:
        lower = part.lower()
        if any(kw in lower for kw in _BODY_FEATURE_KEYWORDS):
            features.append(part)
    return ", ".join(features)


_GENDER_TAGS = {"1boy", "1girl", "boy", "girl", "man", "woman", "male", "female"}
_GENDER_INJECT = {"male": "1boy", "female": "1girl"}
_GENDER_WRONG = {"male": {"1girl", "girl", "woman"}, "female": {"1boy", "boy", "man"}}
_GENDER_RE = re.compile(r'\b(?:' + '|'.join(re.escape(t) for t in _GENDER_TAGS) + r')\b', re.IGNORECASE)


def _ensure_gender_tag(prompt_en: str, gender: str) -> str:
    """确保 prompt 包含正确的性别标签"""
    if not gender:
        return prompt_en
    g = gender.lower()
    correct_tag = _GENDER_INJECT.get(g, "")
    if not correct_tag:
        return prompt_en
    m = _GENDER_RE.search(prompt_en)
    if m:
        found = m.group(0).lower()
        wrong_tags = _GENDER_WRONG.get(g, set())
        if found in wrong_tags:
            return prompt_en[:m.start()] + correct_tag + prompt_en[m.end():]
        return prompt_en
    return f"{correct_tag}, {prompt_en}"


def batch_generate_appearance_prompts(characters: list[dict], llm: object) -> dict[str, dict]:
    """批量生成角色模型友好 prompt"""
    if not characters or not llm:
        return {}

    from infra.concurrency.batch import AdaptiveBatchProcessor, estimate_tokens
    from infra.json_parse import parse_llm_json

    processor = AdaptiveBatchProcessor(llm)
    system = tpl("appearance_prompt_system")

    id_to_uid: dict[str, str] = {}
    for idx, char in enumerate(characters):
        cid = char.get("id", f"char_{idx}")
        id_to_uid[cid] = f"c{idx:04d}"

    def build_prompts(batch):
        parts = []
        for i, char in enumerate(batch):
            cid = char.get("id", f"char_{i}")
            uid = id_to_uid.get(cid, f"c{i:04d}")
            existing_en = char.get("appearance_prompt_en", "")
            if existing_en:
                parts.append(f"[UID:{uid}] id={cid}\n已翻译的英文描述：{existing_en}\n请基于此优化为 AI 绘图 prompt，保留所有外貌细节。")
            else:
                appearance = char.get("appearance", "")
                parts.append(f"[UID:{uid}] id={cid}\n外貌描述：{appearance}")
        return {"system": system,
                "user": "请为以下每个角色生成 AI 绘图 prompt。输出 JSON 数组，每项必须包含 UID 字段。\n\n" + "\n\n".join(parts)}

    def parse_result(raw, batch) -> list[dict] | None:
        result = parse_llm_json(raw)
        if not result:
            return None
        if isinstance(result, dict):
            result = [result]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return None

    batch_result = processor.process(
        items=characters,
        build_prompts=build_prompts,
        parse_result=parse_result,
        estimate_item_tokens=lambda c: estimate_tokens(c.get("appearance", "")) + 200,
        estimate_item_output_tokens=lambda _: 800,
    )

    uid_to_cid: dict[str, str] = {v: k for k, v in id_to_uid.items()}
    all_mapping: dict[str, dict] = {}

    for batch_data in batch_result["results"]:
        if not batch_data:
            continue
        for item in batch_data:
            if not isinstance(item, dict):
                continue
            llm_uid = item.get("UID", "").strip()
            cid = uid_to_cid.get(llm_uid) if llm_uid else None
            if not cid:
                logger.warning(f"角色 prompt 结果无法匹配 UID={llm_uid!r}，跳过")
                continue
            prompt_en = item.get("prompt_en", "")
            body_features = item.get("body_features", "")
            if not body_features and prompt_en:
                body_features = _extract_body_features(prompt_en)
            all_mapping[cid] = {
                "appearance_prompt_en": prompt_en,
                "body_features": body_features,
            }

    failed = batch_result.get("failed_batches", 0)
    if failed:
        if all_mapping:
            logger.warning(f"角色 prompt 部分失败: {failed} 批失败，已成功 {len(all_mapping)}/{len(characters)} 个角色")
        else:
            raise RuntimeError(f"角色 prompt 生成全部失败（{failed} 批）。请检查 LLM 服务后重试。")

    logger.info(f"批量 prompt 生成完成: {len(all_mapping)}/{len(characters)} 个角色")
    return all_mapping


def build_prompt(params: PromptBuildParams) -> str:
    """从镜头数据构建 ComfyUI Prompt"""
    registry = params.registry

    if registry is None:
        from infra.config.registry import ModelRegistry
        registry = ModelRegistry()

    prompt_style = registry.get_prompt_style(params.image_backend) if params.image_backend else "tag"

    from infra.constants import ERR_NOT_PREPARED
    if params.scene_desc and not params.scene_desc.isascii():
        logger.warning(f"场景描述仍为中文，{ERR_NOT_PREPARED}")
    action_en = params.shot.get("action_en", "").strip()
    if not action_en:
        raw_action = params.shot.get("action", "")
        if raw_action and not raw_action.isascii():
            logger.warning(f"动作描述仍为中文（action_en 缺失），{ERR_NOT_PREPARED}")

    from engines.prompt.compiler import get_compiler as _get_compiler
    result = _get_compiler().compile_first_frame(
        shot=params.shot,
        character_desc=params.character_desc.strip() if params.character_desc else "",
        scene_desc=params.scene_desc or "",
        style=params.style,
        genre=params.genre,
        prompt_style=prompt_style,
        character_bible=params.character_bible,
        scene_data=params.scene_data or None,
    )

    if prompt_style == "tag":
        result = _truncate_tag_prompt(result, max_tokens=75)

    return result


def _truncate_tag_prompt(prompt: str, max_tokens: int = 75) -> str:
    """将逗号分隔的 tag prompt 截断到指定 token 数以内"""
    if _estimate_tokens(prompt) <= max_tokens:
        return prompt

    tags = [t.strip() for t in prompt.split(",") if t.strip()]
    result = []
    token_count = 0
    for tag in tags:
        tag_cost = _estimate_tokens(tag) + 1
        if tag_cost > max_tokens:
            truncated_tag = tag[:max_tokens * 4]
            logger.info(f"超长 tag 截断 ({tag_cost} tokens): {tag[:30]}... → {truncated_tag[:30]}...")
            tag = truncated_tag
            tag_cost = _estimate_tokens(tag) + 1
            if tag_cost > max_tokens:
                continue
        if token_count + tag_cost > max_tokens:
            break
        result.append(tag)
        token_count += tag_cost

    truncated = ", ".join(result)
    if len(truncated) < len(prompt):
        logger.info(f"SD1.5 prompt 截断: {len(prompt)} → {len(truncated)} 字符 (保留 {len(result)}/{len(tags)} 个 tag)")
    return truncated
