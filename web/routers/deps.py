"""API 路由共享依赖 — 配置访问、校验工具、任务提交"""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


def verify_token(x_api_token: str = Header(None)):
    """简单 Token 鉴权（本地部署场景）"""
    expected = os.environ.get("AI_DRAMA_API_TOKEN", "")
    if not expected:
        return
    if x_api_token != expected:
        raise HTTPException(status_code=401, detail="未授权")


from infra.config import get_root as _get_root, load_yaml_full  # noqa: E402

ROOT = _get_root()

# ── 配置访问（单例 Config，mtime 变化时自动重载）──

_cfg_path_cache: str | None = None
_cfg_instance = None
_cfg_lock = threading.Lock()


def _get_config():
    """获取缓存的 Config 实例（mtime 变化时自动重载，线程安全）"""
    global _cfg_instance
    from infra.config import Config
    path = _cfg_path()
    # 快速路径：已缓存且未变化（锁外检查 mtime，避免 I/O 阻塞其他线程）
    if _cfg_instance is not None and _cfg_instance.path == path:
        _cfg_instance._check_reload()
        return _cfg_instance
    with _cfg_lock:
        if _cfg_instance is None or _cfg_instance.path != path:
            _cfg_instance = Config(path)
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
    from infra.config.paths import ProjectPaths
    p = _proj()
    candidate = str(ProjectPaths(p).project_yaml)
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

_UUID_RE = re.compile(r"^[a-f0-9-]{36}$")
_FILE_RE = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$")


def _check_id(v: str, label: str = "ID") -> None:
    from infra.models import validate_id
    try:
        validate_id(v, allow_chinese=True)
    except ValueError:
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
    decoded = []
    for p in parts:
        if p:
            # 仅在看起来像 URL 编码时才解码（含 %XX 模式）
            if '%' in p and re.search(r'%[0-9a-fA-F]{2}', p):
                decoded.append(unquote(p, errors="strict"))
            else:
                decoded.append(p)
    joined = "/".join(decoded)
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
    with _cfg_lock:
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
        logger.warning(f"上下文缓存重置失败: {e}")


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
    _yaml_save_inner(path, entity_key, entity_id, data)


def _yaml_save_inner(path: Path, entity_key: str, entity_id: str, data: dict) -> None:
    """yaml_save 的实际逻辑（按文件路径加锁，防止并发写入丢失数据）"""
    lock = _get_yaml_lock(str(path))
    with lock:
        return _yaml_save_inner_unsafe(path, entity_key, entity_id, data)


_yaml_locks: dict[str, threading.Lock] = {}
_yaml_locks_guard = threading.Lock()

def _get_yaml_lock(path: str) -> threading.Lock:
    with _yaml_locks_guard:
        if path not in _yaml_locks:
            _yaml_locks[path] = threading.Lock()
        return _yaml_locks[path]

def _yaml_save_inner_unsafe(path: Path, entity_key: str, entity_id: str, data: dict) -> None:
    """yaml_save 的实际逻辑（无锁内部实现）"""
    file_data: dict = {}
    existing: dict = {}
    if path.exists():
        try:
            file_data = load_yaml_full(path)
            if not isinstance(file_data, dict):
                file_data = {}
            existing = file_data.get(entity_key, {})
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            pass

    merged = {**existing, **data, "id": entity_id}
    # 嵌套字段深合并（前端可能只发送部分字段）
    _NESTED_KEYS = ("bible", "bible_en", "voice", "outfits")
    for nested_key in _NESTED_KEYS:
        if nested_key in existing and nested_key in data:
            if isinstance(existing.get(nested_key), dict) and isinstance(data[nested_key], dict):
                merged[nested_key] = {**existing[nested_key], **data[nested_key]}

    # 规范化实体数据
    _NORMALIZERS = {
        "character": "normalize_character",
        "scene": "normalize_scene",
    }
    normalizer_name = _NORMALIZERS.get(entity_key)
    if normalizer_name:
        from infra import models
        merged = getattr(models, normalizer_name)(merged)

    out = {k: v for k, v in file_data.items() if k != entity_key}
    out[entity_key] = merged
    from infra.config import save_yaml
    save_yaml(path, out)


def parse_entity(req, *, clear_fields: set[str] | None = None) -> tuple[str, dict]:
    """Pydantic 模型 → (entity_id, data)

    exclude_none: 前端未发送的可选字段（None）不覆盖已有值。
    额外排除空字符串：前端默认空串字段不应清空 AI 生成的已有值。
    clear_fields: 用户显式要求清空的字段（允许空串覆盖）。
    """
    data = req.model_dump(exclude_none=True)
    preserve = clear_fields or set()
    data = {k: v for k, v in data.items() if v != "" or k in preserve}
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
        try:
            shutil.rmtree(asset_dir)
        except OSError as e:
            logger.warning(f"资产目录删除失败 {asset_dir}: {e}")


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


def _check_entity_exists(yaml_dir: str, entity_id: str, label: str) -> None:
    """检查实体 YAML 是否存在，不存在则抛 404"""
    path = _paths().config_entity_yaml(yaml_dir, entity_id)
    if not path.exists():
        raise_not_found(label, entity_id)


def raise_not_found(entity_type: str, entity_id: str = "") -> None:
    """统一的 404 错误消息格式"""
    msg = f"{entity_type} {entity_id} 不存在" if entity_id else f"{entity_type} 不存在"
    raise HTTPException(404, msg)


def _submit_entity_task(yaml_dir: str, entity_id: str, label: str,
                         task_fn, *args, require_comfyui: bool = False, **kwargs) -> dict:
    """通用实体生成任务提交：检查存在 → 可选检查 ComfyUI → 提交任务"""
    _check_id(entity_id, f"{label} ID")
    _check_entity_exists(yaml_dir, entity_id, label)
    if require_comfyui:
        require_tool("comfyui")
    return _submit_task(task_fn, _cfg_path(), entity_id, *args, **kwargs)
