"""配置管理包 — 统一入口

从 core.py, cache.py, resolver.py, paths.py, loader.py, registry.py 重新导出所有公共 API。
"""
from infra.config.core import (
    Config,
    SYSTEM_CONFIG_PATH, REGISTRY_PATH, PROMPT_TEMPLATES_PATH, REPO_LOGS_DIR,
)
from infra.config.cache import (
    load_config, save_config, save_yaml, deep_merge,
    atomic_write_bytes, invalidate_config_cache,
)
from infra.config.resolver import (
    resolve_project_config, get_active_project_dir, get_voices_dir,
    projects_dir, get_root,
)
from infra.config.paths import ProjectPaths
from infra.config.loader import (
    cfg_get, load_yaml_full, load_character, load_scene,
    load_yaml_entities, load_existing_entities, load_project_entities,
    load_char_name_to_id, load_scene_name_to_id,
    validate_character_name, CHARACTER_NAME_PATTERN,
)
from infra.config.registry import ModelRegistry

__all__ = [
    "Config", "ProjectPaths", "load_config", "save_config", "save_yaml",
    "load_yaml_full", "load_character", "load_scene", "load_existing_entities", "cfg_get",
    "SYSTEM_CONFIG_PATH", "REGISTRY_PATH", "PROMPT_TEMPLATES_PATH", "REPO_LOGS_DIR",
    "deep_merge", "resolve_project_config",
    "get_active_project_dir", "projects_dir", "get_root", "get_voices_dir",
    "load_project_entities", "load_yaml_entities",
    "load_char_name_to_id", "load_scene_name_to_id",
    "validate_character_name", "CHARACTER_NAME_PATTERN",
    "atomic_write_bytes", "invalidate_config_cache",
    "ModelRegistry",
]
