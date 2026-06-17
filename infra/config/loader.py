"""配置加载函数"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from infra.config.paths import ProjectPaths

logger = logging.getLogger(__name__)

# 角色名约束：括号外不允许含逗号，括号内逗号不受限
CHARACTER_NAME_PATTERN = r"^([^,(]|\([^)]*\))*$"
_CHAR_NAME_PARENS = re.compile(r"\([^)]*\)")


def validate_character_name(name: str) -> str | None:
    """校验角色名，括号外的逗号非法。返回错误信息，合法则返回 None。"""
    if "," in _CHAR_NAME_PARENS.sub("", name):
        return f"角色名括号外不得含逗号: '{name}'"
    return None


def cfg_get(cfg: dict[str, Any], dotted_key: str, default: Any = "") -> Any:
    """从嵌套 dict 中按点分路径取值"""
    parts = dotted_key.split(".")
    cur = cfg
    for p in parts:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


def load_yaml_full(path: Path) -> dict[str, Any]:
    """加载单个 YAML 文件，返回完整 dict"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        if data is not None:
            logger.warning(f"YAML 文件顶层非 dict，返回空: {path}")
        return {}
    return data


def load_character(paths_or_dir: ProjectPaths | str | Path, char_id: str) -> dict[str, Any]:
    """加载角色配置"""
    if hasattr(paths_or_dir, 'character_yaml'):
        fpath = paths_or_dir.character_yaml(char_id)
    else:
        fpath = Path(paths_or_dir) / f"{char_id}.yaml"
    if not fpath.exists():
        return {"id": char_id}
    data = load_yaml_full(fpath)
    char = data.get("character", {})
    return char if isinstance(char, dict) else {"id": char_id}


def load_scene(paths_or_dir: ProjectPaths | str | Path, scene_id_or_name: str) -> dict[str, Any]:
    """加载场景配置"""
    if hasattr(paths_or_dir, 'scene_yaml'):
        fpath = paths_or_dir.scene_yaml(scene_id_or_name)
        scenes_dir = paths_or_dir.scenes_dir
    else:
        fpath = Path(paths_or_dir) / f"{scene_id_or_name}.yaml"
        scenes_dir = Path(paths_or_dir)

    if fpath.exists():
        data = load_yaml_full(fpath)
        scene = data.get("scene", {})
        return scene if isinstance(scene, dict) else {"id": scene_id_or_name}

    if scenes_dir.exists():
        for f in scenes_dir.glob("*.yaml"):
            if f.stem.endswith(".example"):
                continue
            try:
                data = load_yaml_full(f)
                entity = data.get("scene", {})
                if isinstance(entity, dict) and entity.get("name") == scene_id_or_name:
                    return entity
            except Exception:
                continue

    return {"id": scene_id_or_name}


def load_yaml_entities(directory: Path, entity_key: str, *, with_paths: bool = False) -> list[dict[str, Any]] | list[tuple[Path, dict[str, Any]]]:
    """统一加载目录下所有 YAML 实体"""
    if not directory.exists():
        return []
    result = []
    for f in directory.glob("*.yaml"):
        if f.stem.endswith(".example"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                continue
            entity = data.get(entity_key, {})
            if not isinstance(entity, dict):
                continue
            if entity.get("id"):
                result.append((f, entity) if with_paths else entity)
        except Exception as e:
            logger.warning(f"跳过损坏的 YAML {f.name}: {e}")
    return result


def load_existing_entities(entities_dir: Path, entity_key: str) -> list[dict[str, str]]:
    """加载已有实体的 (id, name) 摘要"""
    if not entities_dir.exists():
        return []
    return [{"id": e["id"], "name": e.get("name", e["id"])}
            for e in load_yaml_entities(entities_dir, entity_key)]


def load_project_entities(paths_or_dir: ProjectPaths | str | Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """加载项目的角色和场景数据

    角色 dict 以 name 为 key。角色名约束：括号外不得包含逗号（括号内逗号不受限）。
    多角色需各自独立 YAML，不允许合并（如 "李飞, 叶凝" 应拆为两个文件）。
    """
    if hasattr(paths_or_dir, 'characters_dir'):
        paths = paths_or_dir
    else:
        paths = ProjectPaths(paths_or_dir)
    characters: dict[str, dict[str, Any]] = {}
    for c in load_yaml_entities(paths.characters_dir, "character"):
        name = c.get("name", "")
        if not name:
            continue
        if err := validate_character_name(name):
            cid = c.get("id", "?")
            logger.error(f"角色名非法: {paths.character_yaml(cid)} → {err}，请修正或删除该文件后重试。")
            continue
        characters[name] = c
    scenes = {s["name"]: s for s in load_yaml_entities(paths.scenes_dir, "scene") if s.get("name")}
    return characters, scenes


def load_char_name_to_id(paths_or_dir: ProjectPaths | str | Path) -> dict[str, str]:
    """从角色 YAML 中提取 name→id 映射（单一数据源，避免 3 处重复构造）

    返回 {name: id} dict，过滤掉 name 或 id 为空的条目。
    所有需要 char_name_to_id 的地方统一调用此函数。
    """
    characters, _ = load_project_entities(paths_or_dir)
    return {name: c.get("id", "") for name, c in characters.items() if name and c.get("id")}


def load_scene_name_to_id(paths_or_dir: ProjectPaths | str | Path) -> dict[str, str]:
    """从场景 YAML 中提取 name→id 映射（与 load_char_name_to_id 对称）

    返回 {name: id} dict，过滤掉 name 或 id 为空的条目。
    所有需要 scene_name_to_id 的地方统一调用此函数。
    """
    _, scenes = load_project_entities(paths_or_dir)
    return {name: s.get("id", "") for name, s in scenes.items() if name and s.get("id")}
