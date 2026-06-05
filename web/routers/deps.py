"""API 路由共享依赖 — 配置访问、校验工具、任务提交"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)

from infra.config import get_root as _get_root, load_yaml_full

ROOT = _get_root()

# ── 配置访问（单例 Config，mtime 变化时自动重载）──

_cfg_path_cache: str | None = None
_cfg_instance = None


def _get_config():
    """获取缓存的 Config 实例（mtime 变化时自动重载）"""
    global _cfg_instance
    from infra.config import Config
    path = _cfg_path()
    if _cfg_instance is None or _cfg_instance.path != path:
        _cfg_instance = Config(path)
    else:
        _cfg_instance._check_reload()
    return _cfg_instance


def _merged_cfg() -> dict:
    """获取合并后的完整配置（system.yaml + project.yaml + 注册表默认值）"""
    return _get_config().data


def _merged_cfg_public() -> dict:
    """获取合并配置的公开版本（移除 _project_dir 等内部字段）"""
    return {k: v for k, v in _merged_cfg().items() if not k.startswith("_")}


def _cfg_path() -> str:
    """获取当前活动项目的 project.yaml 绝对路径。"""
    global _cfg_path_cache
    p = _proj()
    candidate = str(p / "config" / "project.yaml")
    if _cfg_path_cache != candidate:
        _cfg_path_cache = candidate
    return _cfg_path_cache


def _paths():
    """获取统一路径管理对象（复用 Config 缓存）"""
    return _get_config().paths


def _proj() -> Path:
    """返回当前活动项目目录"""
    from infra.config import get_active_project_dir
    return get_active_project_dir(ROOT)


# ── 校验工具 ──

_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$")
_UUID_RE = re.compile(r"^[a-f0-9-]{36}$")
_FILE_RE = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$")


def _check_id(v: str, label: str = "ID") -> None:
    if not _ID_RE.match(v):
        raise HTTPException(400, f"无效的 {label}")


def _check_uuid(v: str) -> None:
    if not _UUID_RE.match(v):
        raise HTTPException(400, "无效的任务 ID")


def _check_filename(v: str) -> None:
    if not _FILE_RE.match(v):
        raise HTTPException(400, "无效的文件名")


def _check_entity_type(v: str) -> None:
    if v not in ("characters", "scenes"):
        raise HTTPException(400, "entity_type 必须是 characters 或 scenes")


def _check_episode(ep: int) -> None:
    if ep < 1:
        raise HTTPException(400, "episode 必须 >= 1")


def _safe_path(base: Path, *parts: str) -> Path:
    """安全路径拼接 — resolve() + is_relative_to() 双重校验"""
    from urllib.parse import unquote
    parts = [unquote(p, errors="ignore") for p in parts if p]
    joined = "/".join(parts)
    if not joined:
        return base.resolve()
    resolved = (base / joined).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise HTTPException(400, "非法路径")
    return resolved


def _check_tool(name: str, cfg: dict) -> dict:
    """检测工具可用性（委托给 infra.toolcheck）"""
    from infra.toolcheck import check_tool
    return check_tool(name, cfg)


def require_tool(name: str, cfg: dict | None = None) -> dict:
    """检测工具可用性，不可用时抛 HTTPException"""
    if cfg is None:
        cfg = _merged_cfg()
    result = _check_tool(name, cfg)
    if not result.get("available"):
        raise HTTPException(503, f"{name} 不可用: {result.get('reason', '未知')}")
    return result


def _reset_proj_cache():
    """重置项目目录缓存（项目切换/删除后调用）"""
    global _cfg_path_cache, _cfg_instance
    _cfg_path_cache = None
    _cfg_instance = None
    from infra.database._db import _reset_project_cache
    _reset_project_cache()
    from infra.config import invalidate_config_cache
    invalidate_config_cache()
    try:
        from pipeline.tasks.helpers import invalidate_ctx_cache
        invalidate_ctx_cache()
    except Exception as e:
        logger.debug(f"上下文缓存重置失败: {e}")


def _submit_task(task, *args, **kwargs) -> dict:
    try:
        result = task.delay(*args, **kwargs)
        return {"status": "submitted", "task_id": result.id,
                "poll_url": f"/api/tasks/{result.id}"}
    except Exception as e:
        logger.error(f"任务提交失败: {e}", exc_info=True)
        raise HTTPException(500, f"任务提交失败: {e}")


# ── 通用 YAML CRUD ──

def yaml_list(yaml_dir: str, entity_key: str) -> list[dict]:
    """通用 YAML 实体列表读取"""
    from infra.config import load_yaml_entities
    d = _paths().config_entity_dir(yaml_dir)
    return load_yaml_entities(d, entity_key)


def yaml_save(yaml_dir: str, entity_key: str, entity_id: str, data: dict) -> None:
    """通用 YAML 实体保存（YAML 为唯一数据源）"""
    d = _paths().config_entity_dir(yaml_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{entity_id}.yaml"
    file_data: dict = {}
    existing: dict = {}
    if path.exists():
        try:
            file_data = load_yaml_full(path) or {}
            if not isinstance(file_data, dict):
                file_data = {}
            existing = file_data.get(entity_key, {})
            if not isinstance(existing, dict):
                existing = {}
            if entity_key in existing:
                logger.warning(f"YAML {path.name} 中 {entity_key} 段内有嵌套的 '{entity_key}' key，已剔除")
                existing.pop(entity_key, None)
        except Exception:
            file_data = {}
            existing = {}
    merged = {**existing, **data, "id": entity_id}
    if entity_key == "character":
        from infra.models import normalize_character
        merged = normalize_character(merged)
    out = {k: v for k, v in file_data.items() if k != entity_key}
    out[entity_key] = merged
    from infra.config import save_yaml
    save_yaml(path, out)


def parse_entity(req) -> tuple[str, dict]:
    """Pydantic 模型 → (entity_id, data)"""
    data = req.model_dump(exclude_none=True)
    return data.pop("id"), data


def yaml_delete(yaml_dir: str, entity_id: str, label: str) -> None:
    """通用 YAML 实体删除（文件 → 资产目录）"""
    import shutil
    p = _paths()
    path = p.config_entity_yaml(yaml_dir, entity_id)
    if not path.exists():
        raise HTTPException(404, f"{label} {entity_id} 不存在")
    path.unlink()
    asset_dir = p.assets_entity_dir(yaml_dir) / entity_id
    if asset_dir.exists():
        shutil.rmtree(asset_dir, ignore_errors=True)


def yaml_batch_delete(yaml_dir: str, entity_ids: list[str], label: str) -> dict:
    """通用 YAML 批量删除"""
    deleted, errors = [], []
    for eid in entity_ids:
        try:
            yaml_delete(yaml_dir, eid, label)
            deleted.append(eid)
        except HTTPException as e:
            errors.append({"id": eid, "error": e.detail})
        except Exception as e:
            errors.append({"id": eid, "error": str(e)})
    return {"status": "ok", "deleted": deleted, "errors": errors}
