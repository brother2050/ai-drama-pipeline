"""数据校验 — 导入计划的引用完整性 + 翻译状态检测

从 infra/models.py 中提取，保持模块职责单一。

注意：使用 TYPE_CHECKING 避免与 infra.models 的循环导入。
infra.models 重新导出此模块的符号，在模块顶层导入 ImportPlan 会导致循环依赖。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infra.models import ImportPlan

logger = logging.getLogger(__name__)

__all__ = ["ImportValidator", "get_translation_status", "validate_id"]


# ── 共享校验函数 ────────────────────────────────────────

def validate_id(v: str, *, allow_chinese: bool = False) -> str:
    """校验实体 ID — 字母、数字、下划线、连字符，可选允许中文"""
    if allow_chinese:
        pattern = r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$"
        label = "字母、数字、中文、下划线、连字符"
    else:
        pattern = r"^[a-zA-Z0-9_-]+$"
        label = "字母、数字、下划线、连字符"
    if not re.match(pattern, v):
        raise ValueError(f"ID 只允许{label}")
    return v


# ── 翻译状态检测 ──────────────────────────────────────

def get_translation_status(plan: ImportPlan) -> dict:
    """检测导入计划的翻译完整度

    Returns:
        {
            "complete": bool,
            "missing": {"characters": [...], "scenes": [...], "shots": [...]},
            "summary": str,
        }
    """
    missing_chars = [c.id for c in plan.characters if not c.appearance_prompt_en]
    missing_scenes = [s.id for s in plan.scenes if not s.description_en]
    missing_shots = [sh.shot_id for sh in plan.shots if not sh.action_en]

    all_complete = not missing_chars and not missing_scenes and not missing_shots
    parts = []
    if missing_chars:
        parts.append(f"{len(missing_chars)} 角色缺外貌 prompt")
    if missing_scenes:
        parts.append(f"{len(missing_scenes)} 场景缺英文描述")
    if missing_shots:
        parts.append(f"{len(missing_shots)} 镜头缺英文 action")

    return {
        "complete": all_complete,
        "missing": {
            "characters": missing_chars,
            "scenes": missing_scenes,
            "shots": missing_shots,
        },
        "summary": "翻译完整" if all_complete else "缺翻译: " + "、".join(parts),
    }


# ── 引用校验 ──────────────────────────────────────────

def _resolve_existing_names(plan: ImportPlan, project_dir: Path | None,
                            existing_char_names: set[str] | None,
                            existing_scene_names: set[str] | None,
                            existing_shots: set[tuple[int, str]] | None = None) -> tuple[set[str], set[str], set[tuple[int, str]]]:
    """收集所有已知的角色/场景名称 + 已有镜头 (episode, shot_id) 对

    分镜的 characters/scene_name 字段存储的是名称（非 hash ID），
    校验时需要用名称匹配。
    existing_shots 由调用方传入（避免模型层直接依赖数据库层）。
    """
    from infra.config import ProjectPaths, load_yaml_entities

    char_names = {c.name for c in plan.characters}
    scene_names = {s.name for s in plan.scenes}
    if existing_char_names:
        char_names |= existing_char_names
    if existing_scene_names:
        scene_names |= existing_scene_names

    shots = existing_shots or set()
    if project_dir and project_dir.exists():
        paths = ProjectPaths(project_dir)
        char_names |= {e["name"] for e in load_yaml_entities(paths.characters_dir, "character") if e.get("name")}
        scene_names |= {e["name"] for e in load_yaml_entities(paths.scenes_dir, "scene") if e.get("name")}

    return char_names, scene_names, shots


def _check_outfit_reference(shot, i: int, plan: ImportPlan, char_names: set[str],
                            project_dir: Path | None) -> list[str]:
    """检查镜头中 outfit 引用是否有效"""
    if not (shot.outfit and shot.characters):
        return []
    primary_char = shot.characters.split("+")[0].strip()
    char = next((c for c in plan.characters if c.name == primary_char), None)
    char_outfits = char.outfits if char else None
    if not char_outfits and project_dir and project_dir.exists():
        try:
            from infra.config import ProjectPaths, load_yaml_entities
            for e in load_yaml_entities(ProjectPaths(project_dir).characters_dir, "character"):
                if e.get("name") == primary_char:
                    char_outfits = e.get("outfits", {})
                    break
        except Exception as e:
            logger.debug(f"查找角色 outfit 跳过: {e}")
    if char_outfits and shot.outfit and shot.outfit not in char_outfits:
        return [f"shots[{i}].outfit: 角色 '{primary_char}' 没有名为 '{shot.outfit}' 的服装，可用: {list(char_outfits.keys())}"]
    return []


class ImportValidator:
    """引用一致性校验 — 合并 plan 内定义 + 已有项目数据"""

    @staticmethod
    def validate_references(
        plan: ImportPlan,
        project_dir: Path | None = None,
        existing_char_names: set[str] | None = None,
        existing_scene_names: set[str] | None = None,
        existing_shots: set[tuple[int, str]] | None = None,
    ) -> list[str]:
        errors = []

        # plan 内部 characters/scenes 名称重复检测
        seen_char_names: set[str] = set()
        for c in plan.characters:
            if c.name in seen_char_names:
                errors.append(f"characters: 名称 '{c.name}' 重复定义")
            seen_char_names.add(c.name)
        seen_scene_names: set[str] = set()
        for s in plan.scenes:
            if s.name in seen_scene_names:
                errors.append(f"scenes: 名称 '{s.name}' 重复定义")
            seen_scene_names.add(s.name)

        char_names, scene_names, existing_shots = _resolve_existing_names(
            plan, project_dir, existing_char_names, existing_scene_names, existing_shots)

        # 已有镜头重复检查（按 episode+shot_id，DB 约束是 (project, episode, shot_id)）
        for shot in plan.shots:
            try:
                ep = int(shot.episode)
            except (ValueError, TypeError):
                continue
            if (ep, shot.shot_id) in existing_shots:
                errors.append(f"shots: 第{ep}集镜头 ID '{shot.shot_id}' 与已有项目重复")

        # shot_id 唯一性（按 episode 分组检查，DB 约束是 (project, episode, shot_id)）
        seen_ids: dict[tuple[int, str], int] = {}
        for i, shot in enumerate(plan.shots):
            try:
                ep = int(shot.episode)
            except (ValueError, TypeError):
                continue  # episode 校验已在上方处理
            key = (ep, shot.shot_id)
            if key in seen_ids:
                errors.append(f"shots[{i}].shot_id: 第{ep}集镜头 ID '{shot.shot_id}' 与 shots[{seen_ids[key]}] 重复")
            else:
                seen_ids[key] = i

        # episode 范围校验
        max_episode = plan.episodes if plan.episodes > 0 else 1
        for i, shot in enumerate(plan.shots):
            try:
                ep = int(shot.episode)
                if ep < 1 or ep > max_episode:
                    errors.append(f"shots[{i}].episode: 集数 '{shot.episode}' 超出范围 [1, {max_episode}]")
            except (ValueError, TypeError):
                errors.append(f"shots[{i}].episode: 无效的集数 '{shot.episode}'")

        # 引用完整性（按名称匹配 — 分镜存名称，不存 hash ID）
        for i, shot in enumerate(plan.shots):
            if shot.scene_name and shot.scene_name not in scene_names:
                errors.append(f"shots[{i}].scene_name: 引用的场景 '{shot.scene_name}' 不存在")
            if shot.characters:
                for cname in shot.characters.split("+"):
                    cname = cname.strip()
                    if cname and cname not in char_names:
                        errors.append(f"shots[{i}].characters: 引用的角色 '{cname}' 不存在")
            errors.extend(_check_outfit_reference(shot, i, plan, char_names, project_dir))

        return errors
