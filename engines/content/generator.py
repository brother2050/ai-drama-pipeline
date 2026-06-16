"""实体生成 — 角色/场景配置生成"""

from __future__ import annotations

import logging
import re

from engines.prompt.compiler import tpl
from engines.content.validator import validate_character, validate_scene

logger = logging.getLogger(__name__)

__all__ = ["generate_characters", "generate_scenes"]


def generate_characters(llm: object, descriptions: list[str],
                        existing_characters: list[dict] | None = None,
                        save_callback=None) -> list[dict]:
    """从描述生成角色配置"""
    return _generate_entities(llm, descriptions, tpl("character_system"), "角色",
                              existing_entities=existing_characters,
                              save_callback=save_callback,
                              validate_fn=validate_character)


def generate_scenes(llm: object, descriptions: list[str],
                    existing_scenes: list[dict] | None = None,
                    save_callback=None) -> list[dict]:
    """从描述生成场景配置"""
    return _generate_entities(llm, descriptions, tpl("scene_system"), "场景",
                              existing_entities=existing_scenes,
                              save_callback=save_callback,
                              validate_fn=validate_scene)


def _generate_entities(llm: object, descriptions: list[str],
                       system: str, label: str, *, existing_entities: list[dict] | None = None,
                       save_callback=None, validate_fn=None) -> list[dict]:
    """通用实体生成 — AdaptiveBatchProcessor 自适应分批 + 容错隔离"""
    from infra.concurrency.batch import AdaptiveBatchProcessor, estimate_tokens
    from infra.json_parse import parse_llm_json

    processor = AdaptiveBatchProcessor(llm)

    existing_ctx = ""
    if existing_entities:
        lines = [f"  - {e.get('name', e['id'])}" for e in existing_entities]
        existing_ctx = f"=== 已有{label}（name 不可重复）===\n" + "\n".join(lines) + "\n\n"

    _NAME_RE = re.compile(r'name 必须为「(.+?)」')

    def _extract_expected_name(desc: str) -> str:
        m = _NAME_RE.search(desc)
        return m.group(1) if m else ""

    expected_names = [_extract_expected_name(d) for d in descriptions]

    def build_prompts(batch):
        parts = []
        if existing_ctx:
            parts.append(existing_ctx)
        for i, desc in enumerate(batch):
            parts.append(f"[{label}{i+1}] {desc}")
        return {"system": system, "user": "\n\n".join(parts)}

    def parse_result(raw, batch):
        result = parse_llm_json(raw)
        if isinstance(result, list):
            name_map: dict[str, dict] = {}
            for item in result:
                if isinstance(item, dict) and item.get("name"):
                    name_map[item["name"].strip()] = item
            return name_map
        return None

    batch_result = processor.process(
        items=descriptions,
        build_prompts=build_prompts,
        parse_result=parse_result,
        estimate_item_tokens=lambda d: estimate_tokens(d) + 200,
        estimate_item_output_tokens=lambda _: 1024,
    )

    used_names: set[str] = {e["name"] for e in (existing_entities or []) if e.get("name")}

    entities: list[dict | None] = []
    deduped: list[dict] = []
    offset = 0
    for batch_data, batch_size in zip(batch_result["results"], batch_result["batch_sizes"]):
        batch_names = expected_names[offset:offset + batch_size]
        batch_deduped: list[dict] = []
        if batch_data and isinstance(batch_data, dict):
            fallback_entities = [v for v in batch_data.values() if isinstance(v, dict)]
            fallback_idx = 0
            for ename in batch_names:
                if ename:
                    entity = batch_data.get(ename)
                    if entity is not None:
                        fallback_idx += 1
                else:
                    entity = fallback_entities[fallback_idx] if fallback_idx < len(fallback_entities) else None
                    fallback_idx += 1
                entities.append(entity)
                if not isinstance(entity, dict) or not entity:
                    continue
                name = entity.get("name", "").strip()
                if not name or name in used_names:
                    if name in used_names:
                        logger.warning(f"  ⚠ {label}名重复，丢弃: {name}")
                    continue
                used_names.add(name)
                if validate_fn:
                    entity = validate_fn(entity)
                batch_deduped.append(entity)
                deduped.append(entity)
                logger.info(f"  ✅ 生成{label}: {name}")
        else:
            entities.extend([None] * batch_size)

        if save_callback and batch_deduped:
            try:
                save_callback(batch_deduped)
            except Exception as cb_err:
                logger.warning(f"增量保存回调异常（不影响主流程）: {cb_err}")

        offset += batch_size

    failed_count = sum(1 for e in entities if not isinstance(e, dict) or not e)
    if failed_count:
        failed_names = [expected_names[i] for i, e in enumerate(entities) if not isinstance(e, dict) or not e]
        logger.warning(f"  ⚠ {label}部分批次失败（{failed_count}/{len(descriptions)}）：{failed_names}")

    valid_entities = [e for e in entities if isinstance(e, dict) and e]
    if len(valid_entities) != len(descriptions):
        logger.warning(f"  ⚠ {label}生成数量不匹配：请求 {len(descriptions)} 个，实际返回 {len(valid_entities)} 个")

    if not deduped:
        raise RuntimeError(f"{label}生成全部失败: 请检查 LLM 服务。")

    if len(deduped) < len(descriptions):
        logger.warning(f"  ⚠ {label}部分成功：请求 {len(descriptions)} 个，成功 {len(deduped)} 个")

    return deduped
