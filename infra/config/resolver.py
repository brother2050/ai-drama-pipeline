"""项目路径解析 — 活动项目发现、声线库定位、路径常量

从 core.py 中提取路径解析逻辑，与 Config 类解耦。
CLI 入口、Celery Worker 启动等不需要 Config 实例的场景可独立使用。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from infra.config.cache import load_config
from infra.config.loader import cfg_get

logger = logging.getLogger(__name__)

__all__ = ["resolve_project_config", "get_active_project_dir", "get_voices_dir",
           "projects_dir", "get_root"]

_ROOT = Path(__file__).resolve().parent.parent.parent  # infra/config/resolver.py → project root


def get_root() -> Path:
    """获取项目根目录（公开 API，替代直接导入 _ROOT）"""
    return _ROOT


def projects_dir(root: Path | None = None) -> Path:
    """所有项目的父目录（仓库根目录/projects/）

    与 ProjectPaths.projects_dir 相同逻辑，但不需要实例化 ProjectPaths。
    适用于尚未持有项目目录引用的调用方（如 CLI 入口、Celery Worker 启动）。
    """
    if root is None:
        root = _ROOT
    return root / "projects"


def _validate_active_path(d: str, root: Path) -> Path | None:
    """校验 .active 文件内容路径安全性（防路径遍历）"""
    p = Path(d).resolve()
    proj_dir = projects_dir(root).resolve()
    if not p.is_relative_to(proj_dir):
        logger.warning(f".active 指向项目目录外的路径，已忽略: {d}")
        return None
    return p


def resolve_project_config(root: Path | None = None) -> str:
    """统一的项目配置路径解析（CLI 和 Web 共用）

    查找顺序：
    1. .active 文件指向的项目
    2. projects/default/ 回退

    Returns:
        配置文件绝对路径
    """
    if root is None:
        root = _ROOT

    # 1. 检查 .active 指向的项目
    active_file = projects_dir(root) / ".active"
    if active_file.exists():
        try:
            d = active_file.read_text().strip()
            if d:
                p = _validate_active_path(d, root)
                if p:
                    cfg = p / "config" / "project.yaml"
                    if cfg.exists():
                        return str(cfg)
        except (OSError, ValueError) as e:
            logger.debug(f"{type(e).__name__}: {e}")

    # 2. 回退到默认项目
    cfg = projects_dir(root) / "default" / "config" / "project.yaml"
    if cfg.exists():
        return str(cfg)

    raise FileNotFoundError("未找到 config/project.yaml，请先初始化默认项目")


def get_active_project_dir(root: Path | None = None) -> Path:
    """获取当前活动项目目录"""
    if root is None:
        root = _ROOT

    active_file = projects_dir(root) / ".active"
    if active_file.exists():
        try:
            d = active_file.read_text().strip()
            if d:
                p = _validate_active_path(d, root)
                if p and p.exists():
                    return p
        except (OSError, ValueError) as e:
            logger.debug(f"{type(e).__name__}: {e}")

    return projects_dir(root) / "default"


def get_voices_dir(root: Path | None = None) -> Path:
    """获取声线库目录（voices.dir 配置覆盖 → 默认 shared_assets/voices/）

    统一入口：CLI、Web、脚本共用，消除 3 处重复的路径构建逻辑。
    """
    cfg_path = str((root or _ROOT) / "config" / "system.yaml")
    if os.path.isfile(cfg_path):
        try:
            cfg = load_config(cfg_path, readonly=True)
            custom = cfg_get(cfg, "voices.dir", "")
            if custom:
                return Path(custom).expanduser()
        except Exception:
            pass
    return (root or _ROOT) / "shared_assets" / "voices"
