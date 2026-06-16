"""实体生成公共工具 — 统一角色/场景的生成+保存逻辑

CLI、Web、Celery 三条路径共用此模块，消除重复代码和职责不清。

用法:
    from engines.utils.entity import generate_and_save, save_entities
"""
from __future__ import annotations

import logging
from pathlib import Path

from infra.constants import STATUS_DONE, STATUS_ERROR
from infra.config import save_yaml, load_existing_entities

logger = logging.getLogger(__name__)


def generate_and_save(
    llm: object,
    descriptions: list[str],
    entity_key: str,
    out_dir: Path,
) -> dict:
    """统一的实体生成+保存入口

    流程：LLM 生成 name+详情 → 代码 name_to_id 自动生成唯一 id → 保存 YAML

    每批生成后立即增量保存（防止中途崩溃丢失已生成内容），
    不再依赖全批次完成后再统一保存。

    Args:
        llm: LLM 后端实例
        descriptions: 描述列表
        entity_key: "character" 或 "scene"
        out_dir: YAML 输出目录

    Returns:
        {"status": STATUS_DONE, "count": N, "entities": [...], "id_remap": {name: id}, "warnings": [...]}
        或 {"status": STATUS_ERROR, "reason": "..."}
    """
    from engines.content.generator import generate_characters, generate_scenes

    out_dir.mkdir(parents=True, exist_ok=True)
    existing = load_existing_entities(out_dir, entity_key)
    existing_ids = {e["id"] for e in existing if e.get("id")}

    # 收集增量保存的所有实体（用于最终返回）
    all_saved: list[dict] = []
    save_warnings: list[str] = []
    id_remap: dict[str, str] = {}

    def _incremental_save(entities: list[dict]):
        """每批生成后立即保存实体到 YAML（增量持久化）"""
        result = save_entities(entities, out_dir, entity_key, existing_ids=existing_ids)
        all_saved.extend(result["generated"])
        id_remap.update(result["id_remap"])
        save_warnings.extend(result["warnings"])
        # 更新 existing_ids 防止后续批次重复（跨批次去重）
        for entity in entities:
            eid = entity.get("id", "")
            if eid:
                existing_ids.add(eid)

    try:
        if entity_key == "character":
            entities = generate_characters(llm, descriptions, existing_characters=existing,
                                           save_callback=_incremental_save)
        else:
            entities = generate_scenes(llm, descriptions, existing_scenes=existing,
                                       save_callback=_incremental_save)
    except RuntimeError as e:
        return {"status": STATUS_ERROR, "reason": str(e)}
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"{entity_key}生成异常: {e}"}

    if not entities:
        return {"status": STATUS_ERROR, "reason": f"LLM 未能生成有效{entity_key}"}

    # 最终结果（已在批次循环中增量保存，此处汇总返回）
    saved = len(all_saved)
    warnings = list(save_warnings)
    if saved < len(descriptions):
        warnings.append(f"部分{entity_key}生成失败：请求 {len(descriptions)} 个，成功保存 {saved} 个")

    return {
        "status": STATUS_DONE,
        "count": saved,
        "entities": entities,
        "id_remap": id_remap,
        "warnings": warnings,
    }


def save_entities(
    entities: list[dict],
    out_dir: Path,
    entity_key: str,
    *,
    existing_ids: set[str] | None = None,
) -> dict:
    """保存实体到 YAML — id 由 name hash 自动生成

    实体有 id → 保留（导入流）；无 id → name_to_id(name) 自动生成。

    Args:
        entities: 实体列表
        out_dir: YAML 输出目录
        entity_key: "character" 或 "scene"
        existing_ids: 已有实体的 id 集合（防碰撞）

    Returns:
        {"id_remap": {name: id}, "generated": [id, ...], "warnings": [...]}
    """
    from infra.models import normalize_character, normalize_scene, name_to_id

    out_dir.mkdir(parents=True, exist_ok=True)

    # id 去重
    seen_ids: set[str] = set(existing_ids or [])
    duplicates: list[str] = []

    id_remap: dict[str, str] = {}
    generated: list[str] = []
    warnings: list[str] = []

    for entity in entities:
        if entity is None:
            continue
        name = entity.get("name", "").strip()
        if not name:
            continue

        # ID: 有则保留（导入流），无则从 name hash 自动生成
        new_id = entity.get("id", "").strip()
        if not new_id:
            new_id = name_to_id(name)

        # id 碰撞检测（hash 6 位 hex，概率极低但防御）
        if new_id in seen_ids:
            base = new_id
            for i in range(2, 100):
                candidate = f"{base}{i}"
                if candidate not in seen_ids:
                    new_id = candidate
                    break
            else:
                duplicates.append(name)
                logger.warning(f"  ⚠ {entity_key} id 碰撞无法解决: '{name}' ({base})")
                continue
            logger.info(f"  ⚠ {entity_key} id 碰撞: '{name}' → {base} → {new_id}")

        seen_ids.add(new_id)
        entity["id"] = new_id
        entity["name"] = name
        id_remap[name] = new_id

        # 实体规范化
        if entity_key == "character":
            entity = normalize_character(entity)
        elif entity_key == "scene":
            entity = normalize_scene(entity)

        path = out_dir / f"{new_id}.yaml"
        save_yaml(path, {entity_key: entity})
        generated.append(new_id)
        logger.info(f"  ✅ {entity_key}: {name} → {new_id}")

    warnings = [f"重复{entity_key} id「{d}」已跳过" for d in duplicates]
    return {"id_remap": id_remap, "generated": generated, "warnings": warnings}


def build_entity_descriptions(
    shots: list[dict],
    sorted_ids: list[str],
    outline: str,
    style: str,
    genre: str,
    entity_key: str,
    entities: dict[str, dict] | None = None,
) -> list[str]:
    """从分镜数据构建角色/场景描述列表

    统一的描述构建逻辑，CLI 全量生成和 Web 分镜生成共用。

    Args:
        shots: 分镜列表
        sorted_ids: 排序后的实体 ID 列表（可能是 hash ID 或中文名）
        outline: 剧情大纲
        style: 视觉风格
        genre: 题材类型
        entity_key: "character" 或 "scene"
        entities: 已有实体 dict（key=id），用于从 hash ID 反查 name

    Returns:
        描述字符串列表（与 sorted_ids 一一对应）
    """
    from engines.utils.shot import parse_char_names

    descriptions = []
    for eid in sorted_ids:
        # 从已有实体反查 name（eid 可能是 hash ID）
        entity_name = eid
        if entities and eid in entities:
            entity_name = entities[eid].get("name", eid)

        if entity_key == "character":
            entity_shots = [s for s in shots if eid in parse_char_names(s)]
        else:
            entity_shots = [s for s in shots if (s.get("scene_name") or "").strip() == eid]

        actions = [s.get("action", "") for s in entity_shots[:5]]
        dialogues = [s.get("dialogue", "") for s in entity_shots[:5]
                     if s.get("dialogue") and s.get("dialogue") != "......"]

        label = "角色" if entity_key == "character" else "场景"
        parts = [f"根据以下信息生成{label}「{eid}」的配置。"]
        if outline:
            parts.append(f"剧情大纲: {outline}")
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
            parts.append(f"\n【重要】name 必须为「{entity_name}」（与分镜引用一致），不能与其他角色重名。")
        else:
            parts.append("该场景在分镜中的画面:")
            if actions:
                for idx, a in enumerate(actions, 1):
                    parts.append(f"  镜头{idx}: {a}")
            parts.append(f"\n【重要】name 必须为「{entity_name}」（与分镜 scene_name 引用一致），不能与其他场景重名。")

        descriptions.append("\n".join(parts))
    return descriptions
