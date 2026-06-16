"""配置加载函数"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from infra.config.paths import ProjectPaths

logger = logging.getLogger(__name__)


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
    """加载项目的角色和场景数据"""
    if hasattr(paths_or_dir, 'characters_dir'):
        paths = paths_or_dir
    else:
        paths = ProjectPaths(paths_or_dir)
    characters = {c["name"]: c for c in load_yaml_entities(paths.characters_dir, "character") if c.get("name")}
    scenes = {s["name"]: s for s in load_yaml_entities(paths.scenes_dir, "scene") if s.get("name")}
    return characters, scenes
