"""配置管理 — Config 类（聚合 project.yaml + .env + 默认值，线程安全，带热重载）

缓存/IO/合并 → infra/config/cache.py
路径解析 → infra/config/resolver.py
"""
from __future__ import annotations

import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any

from infra.config.paths import ProjectPaths
from infra.config.cache import load_config, invalidate_config_cache, _deep_merge_into
from infra.config.resolver import resolve_project_config

logger = logging.getLogger(__name__)

# ── 系统全局路径常量（单一数据源，避免各处重复拼接） ────

_ROOT = Path(__file__).resolve().parent.parent.parent  # infra/config/core.py → project root

# ── 路径常量（定义在前，使用在后） ──
ENV_FILE_PATH = _ROOT / ".env"

try:
    from dotenv import load_dotenv
    if ENV_FILE_PATH.exists():
        load_dotenv(ENV_FILE_PATH, override=False)
except ImportError:
    logger.debug("dotenv 导入跳过")

SYSTEM_CONFIG_PATH = str(_ROOT / "config" / "system.yaml")
REGISTRY_PATH = str(_ROOT / "config" / "models_registry.yaml")
PROMPT_TEMPLATES_PATH = str(_ROOT / "config" / "prompt_templates.yaml")
REPO_WORKFLOWS_DIR = _ROOT / "workflows"
REPO_LOGS_DIR = _ROOT / "logs"

__all__ = ["Config", "ENV_FILE_PATH", "SYSTEM_CONFIG_PATH", "REGISTRY_PATH",
           "PROMPT_TEMPLATES_PATH", "REPO_WORKFLOWS_DIR", "REPO_LOGS_DIR"]


# ══════════════════════════════════════════════════════════
#  Config 类
# ══════════════════════════════════════════════════════════

class Config:
    """统一配置对象 — 聚合 project.yaml + .env + 默认值"""

    # 系统全局配置路径（使用模块级常量，避免类变量在实例间共享修改）
    SYSTEM_CONFIG = SYSTEM_CONFIG_PATH

    # 仅保留项目级默认值。其他配置（comfyui/llm/server/timeouts/post_production）
    # 来自 system.yaml + project.yaml，不在此硬编码。
    DEFAULTS: dict[str, Any] = {
        "project": {"episodes": 1, "fps": 24,
                     "style": "cinematic", "genre": "urban"},
        "models": {},
        "portraits": {"auto_outfit": True},
    }

    # 必填字段校验规则
    REQUIRED_FIELDS: list[tuple[str, str]] = [
        ("project.name", "项目名称"),
    ]

    # 合法值范围
    VALID_RANGES: dict[str, tuple[int, int]] = {
        "project.episodes": (1, 500),
        "project.fps": (1, 120),
        "server.port": (1, 65535),
        "post_production.transition_duration": (0, 10),
        "post_production.bgm_volume": (0, 1),
        "timeouts.comfyui": (1, 7200),
        "timeouts.tts": (1, 600),
        "timeouts.lipsync": (1, 600),
        "timeouts.llm": (1, 3600),
        "timeouts.music": (1, 600),
    }

    def __init__(self, path: str | None = None):
        self._mtimes: dict[str, float] = {}
        self._reloading = False
        self._reload_lock = threading.Lock()
        self._path = path or self._find_config()
        self._data = self._merge(self._path)
        self._project_dir = str(Path(self._path).resolve().parent.parent) if self._path else os.getcwd()
        # 注入 project_dir 供后端使用（Container._backend_config 依赖此键）
        self._data["_project_dir"] = self._project_dir
        self._warnings: list[str] = []
        self._validate()
        self._paths_instance: ProjectPaths | None = None
        # 记录源文件 mtime，用于热读取检测
        self._record_mtimes()

    @staticmethod
    def _find_config() -> str:
        """查找配置文件（委托给 resolve_project_config）"""
        return resolve_project_config()

    def _merge(self, path: str) -> dict:
        """合并默认配置 + 系统全局配置 + 项目配置

        后端选择由 system.yaml 的 models 段统一定义，不再从 models_registry.yaml 读取默认值。
        """
        merged = copy.deepcopy(self.DEFAULTS)
        # 1. 合并系统全局配置（包含 models.image_backend / models.video_backend 等后端选择）
        sys_path = getattr(Config, 'SYSTEM_CONFIG', None)
        if sys_path and os.path.isfile(sys_path):
            sys_data = load_config(sys_path, readonly=True)
            if isinstance(sys_data, dict):
                _deep_merge_into(merged, sys_data)
        # 2. 合并项目配置（覆盖系统配置）
        if path and os.path.isfile(path):
            file_data = load_config(path, readonly=True)
            if isinstance(file_data, dict):
                _deep_merge_into(merged, file_data)
        return merged

    @property
    def data(self) -> dict:
        self._check_reload()
        return self._data

    @property
    def project_dir(self) -> str:
        return self._project_dir

    @property
    def paths(self) -> ProjectPaths:
        """统一路径管理对象（缓存实例）"""
        if self._paths_instance is None:
            self._paths_instance = ProjectPaths(self._project_dir)
        return self._paths_instance

    @property
    def path(self) -> str:
        return self._path or ""

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持 dot notation: 'models.tts_backend'，文件变化时自动重载）"""
        self._check_reload()
        return self._dot_get(self._data, key, default)

    @staticmethod
    def _dot_get(data: dict, key: str, default: Any = None) -> Any:
        """按点分隔路径从 dict 中取值（不触发重载检查）"""
        val = data
        for k in key.split("."):
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    def _record_mtimes(self) -> None:
        """记录所有配置源文件的 mtime"""
        paths = []
        sys_path = getattr(Config, 'SYSTEM_CONFIG', None)
        if sys_path and os.path.isfile(sys_path):
            paths.append(sys_path)
        if self._path and os.path.isfile(self._path):
            paths.append(self._path)
        for p in paths:
            try:
                self._mtimes[p] = os.path.getmtime(p)
            except OSError as e:
                logger.debug(f"{type(e).__name__}: {e}")

    def _check_reload(self) -> bool:
        """检测源文件是否变化，变化则自动重载。返回是否发生了重载。

        设计：获取 _reload_lock 后立即设置 _reloading=True 并释放锁，
        耗时操作在锁外执行，不阻塞其他线程的 get()。
        其他线程在 _check_reload() 中看到 _reloading=True 会跳过，
        返回旧数据直到重载完成。
        """
        if self._reloading:
            return False
        changed = False
        for p in list(self._mtimes):
            try:
                mtime = os.path.getmtime(p)
                if mtime != self._mtimes[p]:
                    changed = True
                    break
            except OSError:
                continue
        if changed:
            with self._reload_lock:
                # 双重检查：拿到锁后再检查一次，避免重复重载
                if self._reloading:
                    return False
                self._reloading = True
            # 耗时操作在锁外执行，不阻塞其他线程的 get()
            try:
                self._do_reload()
            finally:
                self._reloading = False
            return True
        return False

    def _do_reload(self) -> None:
        # 清除 load_config 的 mtime 缓存，强制重新读取文件
        for p in (getattr(Config, 'SYSTEM_CONFIG', None), self._path):
            if p:
                abspath = str(Path(p).resolve())
                invalidate_config_cache(abspath)
        # 先合并到临时变量，校验通过后再赋值（避免 validate 失败时 _data 被覆盖为损坏数据）
        new_data = self._merge(self._path)
        new_data["_project_dir"] = self._project_dir
        old_data, old_warnings = self._data, self._warnings
        self._data = new_data
        self._warnings = []
        try:
            self._validate()
        except ValueError:
            # 校验失败，回滚到旧数据
            self._data, self._warnings = old_data, old_warnings
            logger.error(f"配置重载校验失败，保留旧配置: {self._path}")
            return
        self._record_mtimes()
        logger.info(f"配置已重载: {self._path}")

    def _get_raw(self, key: str, default=None):
        """内部用：直接读 _data，不触发热重载检查"""
        return self._dot_get(self._data, key, default)

    def _validate(self) -> None:
        """校验配置合法性 — 必填字段缺失时抛异常，范围超限仅警告"""
        # 必填字段（直接访问 _data，避免触发 _check_reload 递归）
        missing = []
        for field, desc in self.REQUIRED_FIELDS:
            val = self._get_raw(field)
            if val is None or val == "":
                missing.append(f"{desc} ({field})")

        if missing:
            raise ValueError(f"缺少必填配置: {', '.join(missing)}")

        # 数值范围（不阻断，仅警告）
        for field, (lo, hi) in self.VALID_RANGES.items():
            val = self._get_raw(field)
            if val is not None:
                try:
                    v = float(val)
                    if v < lo or v > hi:
                        self._warnings.append(
                            f"配置 {field}={v} 超出建议范围 [{lo}, {hi}]"
                        )
                except (ValueError, TypeError):
                    self._warnings.append(f"配置 {field} 不是有效数值: {val}")

        if self._warnings:
            for w in self._warnings:
                logger.warning(f"⚠ 配置校验: {w}")

    @property
    def warnings(self) -> list[str]:
        """返回配置校验警告列表"""
        return list(self._warnings)

    def __repr__(self) -> str:
        return f"Config({self._path})"
