"""配置管理 — 单一数据源，线程安全，带缓存"""

from __future__ import annotations

import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    _env = _ROOT / ".env"
    if _env.exists():
        load_dotenv(_env, override=False)
except ImportError:
    logger.debug("dotenv 导入跳过")

__all__ = ["Config", "ProjectPaths", "load_config", "save_config", "save_yaml",
           "load_yaml_full", "load_character", "load_scene", "load_existing_entities", "cfg_get",
           "SYSTEM_CONFIG_PATH", "REGISTRY_PATH", "PROMPT_TEMPLATES_PATH", "REPO_LOGS_DIR",
           "deep_merge", "resolve_project_config",
           "get_active_project_dir", "projects_dir", "get_root"]

# 系统全局配置路径（单一数据源，避免各处重复拼接）
SYSTEM_CONFIG_PATH = str(_ROOT / "config" / "system.yaml")
REGISTRY_PATH = str(_ROOT / "config" / "models_registry.yaml")
PROMPT_TEMPLATES_PATH = str(_ROOT / "config" / "prompt_templates.yaml")
REPO_LOGS_DIR = _ROOT / "logs"


def get_root() -> Path:
    """获取项目根目录（公开 API，替代直接导入 _ROOT）"""
    return _ROOT


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并 override 到 base 中（返回新 dict，不修改原对象）"""
    result = copy.deepcopy(base)
    Config._deep_merge_inplace(result, override)
    return result


class ProjectPaths:
    """统一路径管理 — 所有项目路径的单一数据源

    两个核心目录:
      - root: 项目根目录（如 projects/default/）
      - episode_dir(n): 某集的输出目录（如 projects/default/output/e01/）

    用法:
      paths = ProjectPaths("/path/to/projects/default")
      paths.characters_dir          # .../config/characters/
      paths.character_yaml("guchen")# .../config/characters/guchen.yaml
      paths.episode_dir(1)          # .../output/e01/
      paths.shot_dir(1, "001")      # .../output/e01/s001/
      paths.shot_frame(1, "001")    # .../output/e01/s001/frame.png
      paths.episode_srt(1)          # .../output/e01/episode_01.srt
      paths.episode_final(1)        # .../output/e01/episode_01_final.mp4
    """

    def __init__(self, project_dir: str | Path):
        self._root = Path(project_dir).resolve()

    @property
    def root(self) -> Path:
        """项目根目录"""
        return self._root

    # ── 配置 ──────────────────────────────────────────

    @property
    def config_dir(self) -> Path:
        """项目配置目录"""
        return self._root / "config"

    @property
    def project_yaml(self) -> Path:
        """项目配置文件"""
        return self._root / "config" / "project.yaml"

    @property
    def characters_dir(self) -> Path:
        """角色配置目录"""
        return self._root / "config" / "characters"

    @property
    def scenes_dir(self) -> Path:
        """场景配置目录"""
        return self._root / "config" / "scenes"

    def character_yaml(self, char_id: str) -> Path:
        """角色配置文件"""
        return self._root / "config" / "characters" / f"{char_id}.yaml"

    def scene_yaml(self, scene_id: str) -> Path:
        """场景配置文件"""
        return self._root / "config" / "scenes" / f"{scene_id}.yaml"

    # ── 分镜 ──────────────────────────────────────────

    # ── 资产 ──────────────────────────────────────────

    @property
    def assets_dir(self) -> Path:
        """资产根目录"""
        return self._root / "assets"

    @property
    def character_assets_dir(self) -> Path:
        """角色资产目录"""
        return self._root / "assets" / "characters"

    @property
    def scene_assets_dir(self) -> Path:
        """场景资产目录"""
        return self._root / "assets" / "scenes"

    @property
    def loras_dir(self) -> Path:
        """LoRA 模型目录"""
        return self._root / "assets" / "loras"

    def character_asset_dir(self, char_id: str) -> Path:
        """角色资产目录"""
        return self._root / "assets" / "characters" / char_id

    def character_lora_dir(self, char_id: str) -> Path:
        """角色 LoRA 子目录"""
        return self._root / "assets" / "characters" / char_id / "lora"

    def character_outfit_dir(self, char_id: str, outfit_key: str) -> Path:
        """角色服装资产目录"""
        return self._root / "assets" / "characters" / char_id / outfit_key

    def scene_asset_dir(self, scene_id: str) -> Path:
        """场景资产目录"""
        return self._root / "assets" / "scenes" / scene_id

    # ── 输出（集级） ──────────────────────────────────

    @property
    def output_dir(self) -> Path:
        """输出根目录"""
        return self._root / "output"

    def episode_dir(self, episode: int) -> Path:
        """某集的输出目录"""
        return self._root / "output" / f"e{episode:02d}"

    def episode_srt(self, episode: int) -> Path:
        """某集的 SRT 字幕文件"""
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}.srt"

    def episode_final(self, episode: int) -> Path:
        """某集的成片文件"""
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}_final.mp4"

    def shot_dir(self, episode: int, shot_id: str) -> Path:
        """镜头输出目录"""
        return self._root / "output" / f"e{episode:02d}" / f"s{shot_id}"

    def shot_audio(self, episode: int, shot_id: str) -> Path:
        """镜头音频"""
        return self.shot_dir(episode, shot_id) / "audio.wav"

    def shot_frame(self, episode: int, shot_id: str) -> Path:
        """镜头首帧"""
        return self.shot_dir(episode, shot_id) / "frame.png"

    def shot_video(self, episode: int, shot_id: str) -> Path:
        """镜头视频"""
        return self.shot_dir(episode, shot_id) / "video.mp4"

    def shot_synced(self, episode: int, shot_id: str) -> Path:
        """镜头口型同步视频"""
        return self.shot_dir(episode, shot_id) / "synced.mp4"

    # ── 工作流 ──────────────────────────────────────────

    @property
    def workflows_dir(self) -> Path:
        """工作流模板目录"""
        return self._root / "workflows"

    # ── 其他 ──────────────────────────────────────────

    @property
    def projects_dir(self) -> Path:
        """所有项目的父目录（仓库根目录级别）"""
        return self._root.parent.parent / "projects"

    @property
    def shared_assets_dir(self) -> Path:
        """全局共享资产目录（仓库根目录级别）"""
        return self._root.parent.parent / "shared_assets"

    @property
    def tts_preview_dir(self) -> Path:
        """TTS 预览目录"""
        return self._root / "output" / "tts_preview"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self._root / "logs"

    def bgm_file(self, tag: str = "") -> Path:
        """配乐文件路径（tag 用于区分不同用途，如时间戳）"""
        name = f"bgm_{tag}.wav" if tag else "bgm.wav"
        return self._root / "output" / name

    def config_entity_dir(self, entity_type: str) -> Path:
        """通用实体配置目录（characters / scenes）"""
        return self._root / "config" / entity_type

    def assets_entity_dir(self, entity_type: str) -> Path:
        """通用实体资产目录（characters / scenes）"""
        return self._root / "assets" / entity_type

    def config_entity_yaml(self, entity_type: str, entity_id: str) -> Path:
        """通用实体配置文件"""
        return self._root / "config" / entity_type / f"{entity_id}.yaml"

    def assets_entity_file(self, entity_type: str, entity_id: str, filename: str) -> Path:
        """通用实体资产文件"""
        return self._root / "assets" / entity_type / entity_id / filename

    def seko_asset_dir(self, task_id: str) -> Path:
        """Seko 策划案资产目录"""
        return self._root / "assets" / "seko" / task_id

    def ensure_dirs(self) -> None:
        """创建所有标准子目录"""
        for d in [
            self.config_dir, self.characters_dir, self.scenes_dir,
            self.assets_dir,
            self.character_assets_dir, self.scene_assets_dir, self.loras_dir,
            self.output_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


def cfg_get(cfg: dict, dotted_key: str, default=""):
    """从嵌套 dict 中按点分路径取值，如 'models.gpt_sovits.api_url'"""
    parts = dotted_key.split(".")
    cur = cfg
    for p in parts:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


def load_character(paths_or_dir, char_id: str) -> dict:
    """加载角色配置，返回角色内层 dict（消除重复的 load_yaml_full + .get("character", {}) 模式）

    Args:
        paths_or_dir: ProjectPaths 实例或 Path/str 角色目录
        char_id: 角色 ID

    Returns:
        角色 dict，不存在则返回 {"id": char_id}
    """
    if hasattr(paths_or_dir, 'character_yaml'):
        fpath = paths_or_dir.character_yaml(char_id)
    else:
        fpath = Path(paths_or_dir) / f"{char_id}.yaml"
    if not fpath.exists():
        return {"id": char_id}
    data = load_yaml_full(fpath)
    return data.get("character", {})


def load_scene(paths_or_dir, scene_id: str) -> dict:
    """加载场景配置，返回场景内层 dict

    Args:
        paths_or_dir: ProjectPaths 实例或 Path/str 场景目录
        scene_id: 场景 ID

    Returns:
        场景 dict，不存在则返回 {"id": scene_id}
    """
    if hasattr(paths_or_dir, 'scene_yaml'):
        fpath = paths_or_dir.scene_yaml(scene_id)
    else:
        fpath = Path(paths_or_dir) / f"{scene_id}.yaml"
    if not fpath.exists():
        return {"id": scene_id}
    data = load_yaml_full(fpath)
    return data.get("scene", {})


def load_yaml_entities(directory: Path, entity_key: str, *, with_paths: bool = False):
    """统一加载目录下所有 YAML 实体（角色/场景等）

    Args:
        directory: YAML 文件目录（如 characters/、scenes/）
        entity_key: 顶层 key（如 "character"、"scene"）
        with_paths: True 返回 [(path, entity), ...]，False 返回 [entity, ...]

    Returns:
        实体列表，或 (路径, 实体) 元组列表
    """
    if not directory.exists():
        return []
    result = []
    for f in directory.glob("*.yaml"):
        if f.stem.endswith(".example"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            entity = data.get(entity_key, {})
            if entity.get("id"):
                result.append((f, entity) if with_paths else entity)
        except Exception as e:
            logger.warning(f"跳过损坏的 YAML {f.name}: {e}")
    return result


def load_existing_entities(entities_dir: Path, entity_key: str) -> list[dict]:
    """加载已有实体的 (id, name) 摘要，用于注入 LLM prompt 避免 ID/名称冲突"""
    if not entities_dir.exists():
        return []
    return [{"id": e["id"], "name": e.get("name", e["id"])}
            for e in load_yaml_entities(entities_dir, entity_key)]


def load_yaml_full(path: Path) -> dict:
    """加载单个 YAML 文件，返回完整数据（含顶层 key）

    替代手动 open() + yaml.safe_load() 模式，统一异常处理。
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_cache: dict[str, tuple[dict, float]] = {}
_lock = threading.Lock()


def load_config(path: str, *, force: bool = False) -> dict[str, Any]:
    """加载 YAML 配置（带 mtime 缓存）"""
    abspath = str(Path(path).resolve())
    if not os.path.isfile(abspath):
        logger.warning(f"配置文件不存在: {abspath}")
        return {}

    if not force and abspath in _cache:
        data, mtime = _cache[abspath]
        if os.path.getmtime(abspath) == mtime:
            return copy.deepcopy(data)

    with _lock:
        if not force and abspath in _cache:
            data, mtime = _cache[abspath]
            if os.path.getmtime(abspath) == mtime:
                return copy.deepcopy(data)
        try:
            with open(abspath, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件 YAML 格式错误: {abspath}: {e}", exc_info=True)
            data = {}
        _cache[abspath] = (data, os.path.getmtime(abspath))
    return copy.deepcopy(data)


def save_yaml(path: str | Path, data: Any, *, sort_keys: bool = False) -> None:
    """原子写入 YAML 文件（temp file + rename，防崩溃损坏）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=sort_keys)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            logger.debug("临时文件清理")
            pass
        raise


def save_config(path: str, data: dict[str, Any]) -> None:
    """保存 YAML 配置（原子写入）"""
    save_yaml(path, data, sort_keys=False)
    abspath = str(Path(path).resolve())
    with _lock:
        _cache[abspath] = (copy.deepcopy(data), os.path.getmtime(abspath))


def invalidate_config_cache(path: str | None = None) -> None:
    """清除配置缓存，强制下次 load_config 重新读取文件

    Args:
        path: 指定要清除的配置文件路径。None 则清除所有缓存。
    """
    with _lock:
        if path:
            abspath = str(Path(path).resolve())
            _cache.pop(abspath, None)
        else:
            _cache.clear()
    logger.debug(f"配置缓存已清除: {path or '全部'}")


class Config:
    """统一配置对象 — 聚合 project.yaml + .env + 默认值"""

    # 默认配置（project.name 不设默认值，由 REQUIRED_FIELDS 强制要求）
    # 系统全局配置路径
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
        """合并默认配置 + 注册表默认值 + 系统全局配置 + 项目配置"""
        merged = copy.deepcopy(self.DEFAULTS)
        # 0. 从 models_registry.yaml 读取默认后端名（注册表是唯一真相来源）
        try:
            from flow.model_registry import ModelRegistry
            reg = ModelRegistry()
            reg_defaults = reg.get_defaults()
            if reg_defaults:
                # 注入 models 段的后端默认值（tts_backend, image_backend 等）
                models_defaults = {k: v for k, v in reg_defaults.items()
                                   if k.endswith("_backend") and k != "llm_backend"}
                merged.setdefault("models", {}).update(models_defaults)
                # 注入 llm.backend（llm 段独立于 models）
                if "llm_backend" in reg_defaults:
                    merged.setdefault("llm", {})["backend"] = reg_defaults["llm_backend"]
        except (ImportError, FileNotFoundError, ValueError, yaml.YAMLError) as e:
            logger.warning(f"模型注册表加载失败: {e}")
        # 1. 合并系统全局配置
        sys_path = getattr(Config, 'SYSTEM_CONFIG', None)
        if sys_path and os.path.isfile(sys_path):
            sys_data = load_config(sys_path)
            if isinstance(sys_data, dict):
                Config._deep_merge_inplace(merged, sys_data)
        # 2. 合并项目配置（覆盖系统配置）
        if path and os.path.isfile(path):
            file_data = load_config(path)
            if isinstance(file_data, dict):
                Config._deep_merge_inplace(merged, file_data)
        return merged

    @staticmethod
    def _deep_merge_inplace(base: dict, override: dict) -> None:
        """深度合并 override 到 base 中（就地修改 base，不创建完整副本）

        与模块级 deep_merge() 不同：deep_merge() 返回新 dict（不修改原对象），
        此方法就地修改 base（性能更好，避免大量 copy.deepcopy）。
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge_inplace(base[key], value)
            else:
                base[key] = value

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
        keys = key.split(".")
        val = self._data
        for k in keys:
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
        """检测源文件是否变化，变化则自动重载。返回是否发生了重载。"""
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
                _cache.pop(abspath, None)
        self._data = self._merge(self._path)
        self._data["_project_dir"] = self._project_dir
        self._warnings = []
        self._validate()
        self._record_mtimes()
        logger.info(f"配置已重载: {self._path}")

    def _get_raw(self, key: str, default=None):
        """内部用：直接读 _data，不触发热重载检查"""
        val = self._data
        for k in key.split("."):
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

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
                cfg = Path(d) / "config" / "project.yaml"
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
                p = Path(d)
                if p.exists():
                    return p
        except (OSError, ValueError) as e:
            logger.debug(f"{type(e).__name__}: {e}")

    return projects_dir(root) / "default"


def projects_dir(root: Path | None = None) -> Path:
    """所有项目的父目录（仓库根目录/projects/）

    与 ProjectPaths.projects_dir 相同逻辑，但不需要实例化 ProjectPaths。
    适用于尚未持有项目目录引用的调用方（如 CLI 入口、Celery Worker 启动）。
    """
    if root is None:
        root = _ROOT
    return root / "projects"
