"""实体生成公共工具 — 统一角色/场景的生成+保存逻辑

CLI、Web、Celery 三条路径共用此模块，消除重复代码和职责不清。

用法:
    from engines.entity_utils import generate_and_save, save_entities, remap_shot_ids
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from infra.config import save_yaml, load_existing_entities

logger = logging.getLogger(__name__)

__all__ = ["generate_and_save", "save_entities", "remap_shot_ids", "unique_hash_id",
           "build_entity_descriptions"]


def unique_hash_id(prefix: str, name: str, existing: dict) -> str:
    """基于名字生成确定性短 hash ID，碰撞时自动追加后缀

    Args:
        prefix: ID 前缀（如 "ch"、"sc"）
        name: 角色/场景名（任意语言）
        existing: 已有的 id_remap，用于检测碰撞

    Returns:
        唯一的 hash ID，如 ch_8a3f2b1c 或 ch_8a3f2b1c_2
    """
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    base = f"{prefix}_{h}"
    candidate = base
    counter = 2
    while candidate in existing.values():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def generate_and_save(
    llm: object,
    descriptions: list[str],
    entity_key: str,
    out_dir: Path,
    prefix: str,
    *,
    expected_ids: list[str] | None = None,
) -> dict:
    """统一的实体生成+保存入口

    Args:
        llm: LLM 后端实例
        descriptions: 描述列表
        entity_key: "character" 或 "scene"
        out_dir: YAML 输出目录
        prefix: ID 前缀（"ch" 或 "sc"）
        expected_ids: 预期 ID 列表（分镜引用时传入，确保 ID 对齐）

    Returns:
        {"status": "done", "count": N, "entities": [...], "id_remap": {...}}
        或 {"status": "error", "reason": "..."}
    """
    from engines.llm_generator import generate_characters, generate_scenes

    out_dir.mkdir(parents=True, exist_ok=True)
    existing = load_existing_entities(out_dir, entity_key)

    try:
        if entity_key == "character":
            entities = generate_characters(
                llm, descriptions, expected_ids=expected_ids, existing_characters=existing)
        else:
            entities = generate_scenes(
                llm, descriptions, expected_ids=expected_ids, existing_scenes=existing)
    except RuntimeError as e:
        return {"status": "error", "reason": str(e)}
    except Exception as e:
        return {"status": "error", "reason": f"{entity_key}生成异常: {e}"}

    if not entities:
        return {"status": "error", "reason": f"LLM 未能生成有效{entity_key}"}

    result = save_entities(entities, prefix, out_dir, entity_key)
    return {
        "status": "done",
        "count": len(result["generated"]),
        "entities": entities,
        "id_remap": result["id_remap"],
        "warnings": result["warnings"],
    }


def save_entities(
    entities: list[dict],
    prefix: str,
    out_dir: Path,
    entity_key: str,
) -> dict:
    """保存实体到 YAML — 去重同名 + hash ID + 角色规范化

    统一保存逻辑，消除 CLI/pipeline 各自的 _save_entities。

    Args:
        entities: LLM 生成的实体列表
        prefix: ID 前缀（"ch" 或 "sc"）
        out_dir: YAML 输出目录
        entity_key: "character" 或 "scene"

    Returns:
        {"id_remap": {old_id: new_id}, "generated": [new_id, ...], "warnings": [...]}
    """
    from infra.models import normalize_character

    out_dir.mkdir(parents=True, exist_ok=True)

    # 第一遍：去重同名（保留第一个）
    name_to_first: dict[str, str] = {}
    duplicates: list[str] = []
    for entity in entities:
        if entity is None:
            continue
        old_id = entity.get("id", "")
        name = entity.get("name", "").strip() or old_id
        if name in name_to_first:
            duplicates.append(name)
            logger.warning(f"  ⚠ {entity_key}名重复: '{name}'（{old_id} 与 {name_to_first[name]}），合并")
            continue
        name_to_first[name] = old_id

    # 第二遍：保存
    id_remap: dict[str, str] = {}
    generated: list[str] = []
    warnings: list[str] = [f"同名{entity_key}「{n}」已合并（保留首个）" for n in duplicates]

    for entity in entities:
        if entity is None:
            continue
        old_id = entity.get("id", "")
        name = entity.get("name", "").strip() or old_id

        # 同名实体只保留第一个
        if name_to_first.get(name) != old_id:
            first_old_id = name_to_first[name]
            if first_old_id in id_remap:
                id_remap[old_id] = id_remap[first_old_id]
                logger.info(f"  🔗 合并: {old_id} → {id_remap[first_old_id]}（同名 '{name}'）")
            continue

        new_id = unique_hash_id(prefix, name, id_remap)
        entity["id"] = new_id
        entity["name"] = name
        id_remap[old_id] = new_id

        # 角色数据规范化
        if entity_key == "character":
            entity = normalize_character(entity)

        path = out_dir / f"{new_id}.yaml"
        save_yaml(path, {entity_key: entity})
        generated.append(new_id)
        logger.info(f"  ✅ {entity_key}: {name} ({old_id} → {new_id})")

    return {"id_remap": id_remap, "generated": generated, "warnings": warnings}


def build_entity_descriptions(
    shots: list[dict],
    sorted_ids: list[str],
    outline: str,
    style: str,
    genre: str,
    entity_key: str,
) -> list[str]:
    """从分镜数据构建角色/场景描述列表

    统一的描述构建逻辑，CLI 全量生成和 Web 分镜生成共用。

    Args:
        shots: 分镜列表
        sorted_ids: 排序后的实体 ID 列表
        outline: 剧情大纲
        style: 视觉风格
        genre: 题材类型
        entity_key: "character" 或 "scene"

    Returns:
        描述字符串列表（与 sorted_ids 一一对应）
    """
    from engines.shot_utils import parse_char_ids

    descriptions = []
    for eid in sorted_ids:
        if entity_key == "character":
            entity_shots = [s for s in shots if eid in parse_char_ids(s)]
        else:
            entity_shots = [s for s in shots if (s.get("scene_id") or "").strip() == eid]

        actions = [s.get("action", "") for s in entity_shots[:5]]
        dialogues = [s.get("dialogue", "") for s in entity_shots[:5]
                     if s.get("dialogue") and s.get("dialogue") != "......"]

        label = "角色" if entity_key == "character" else "场景"
        parts = [
            f"根据以下信息生成{label}「{eid}」的配置。",
            f"{'角色' if entity_key == 'character' else '场景'}ID: {eid}（必须原样填入 id 字段，不可修改）",
            f"剧情大纲: {outline}",
        ]
        if style or genre:
            ctx = []
            if style:
                ctx.append(f"视觉风格: {style}")
            if genre:
                ctx.append(f"题材类型: {genre}")
            parts.append(f"创作方向: {'，'.join(ctx)}")

        if entity_key == "character":
            parts.append("该角色在分镜中的表现:")
            if actions:
                for idx, a in enumerate(actions, 1):
                    parts.append(f"  镜头{idx}: {a}")
            if dialogues:
                parts.append(f"台词: {' / '.join(dialogues)}")
            parts.append(f"\n【重要】此角色的 id 必须为「{eid}」，且 name 必须是与其他角色不同的独立名字，不能与其他角色重名。")
        else:
            parts.append("该场景在分镜中的画面:")
            if actions:
                for idx, a in enumerate(actions, 1):
                    parts.append(f"  镜头{idx}: {a}")

        descriptions.append("\n".join(parts))
    return descriptions


def remap_shot_ids(shots: list[dict], id_remap: dict) -> None:
    """回写分镜中的旧 ID 为新 hash ID"""
    for shot in shots:
        chars = shot.get("characters", "")
        if chars:
            parts = [c.strip() for c in chars.split("+")]
            parts = [id_remap.get(c, c) for c in parts]
            shot["characters"] = "+".join(parts)
        scene_id = shot.get("scene_id", "")
        if scene_id in id_remap:
            shot["scene_id"] = id_remap[scene_id]
