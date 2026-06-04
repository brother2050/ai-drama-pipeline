"""Celery 任务定义 — 工具函数"""
from __future__ import annotations

from infra.constants import STATUS_RUNNING, STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED
import hashlib
import logging
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _ensure_path():
    from infra.config import get_root
    root = get_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _project_scope_from_config(config_path: str):
    """从 config_path 推导项目名，返回 project_scope 上下文管理器

    用法:
        with _project_scope_from_config(config_path):
            # 所有 DB 操作绑定到正确项目
    """
    from infra.database._db import project_scope
    project_name = Path(config_path).resolve().parent.parent.name
    return project_scope(project_name)


def _safe_int(val, default=0) -> int:
    """安全的 int 转换，处理空字符串和非数字值"""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _load_shots(config_path: str, episode: int) -> list[dict]:
    """从 DB 加载指定集的镜头列表"""
    from engines.storyboard import load_storyboard
    return load_storyboard(episode=episode)


def _find_shot(config_path: str, episode: int, shot_id: str) -> dict | None:
    """查找单个镜头（DB 查询）"""
    for s in _load_shots(config_path, episode):
        if s.get("shot_id") == shot_id:
            return s
    return None


def _shot_dir(config_path: str, episode: int, shot_id: str) -> Path:
    from infra.config import Config
    return Config(config_path).paths.shot_dir(episode, shot_id)


def _check_available(tool_name: str, config_path: str) -> tuple[bool, str]:
    """检测工具可用性。Config 内部有 mtime 缓存，重复调用开销很小。"""
    from infra.config import Config
    from infra.toolcheck import check_tool
    result = check_tool(tool_name, Config(config_path).data)
    return result["available"], result.get("reason", "")


def _db_record_step(episode: int, shot_id: str, step: str, result: dict) -> None:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import upsert_status
        upsert_status(get_pool(), episode, shot_id, step,
                      status=result.get("status", "unknown"), path=result.get("path", ""),
                      error=result.get("reason", "") if result.get("status") in ("skipped", "error") else "",
                      elapsed=result.get("elapsed", 0.0))
    except Exception as e:
        logger.debug(f"DB 写入跳过: {e}")


def _db_mark_running(episode: int, shot_id: str, step: str) -> None:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import upsert_status
        upsert_status(get_pool(), episode, shot_id, step, status=STATUS_RUNNING)
    except Exception as e:
        logger.debug(f"DB mark_running 跳过: {e}")


def _try_mark_running_atomic(episode: int, shot_id: str, step: str) -> bool:
    """原子标记步骤为 running。返回 True 表示成功，False 表示已在运行中。

    逻辑：upsert 'running' 状态，仅当无记录或已有记录非 running/stale 时成功。
    DB 不可用时静默降级（返回 True，允许执行）。
    """
    try:
        from infra.database.pool import get_pool, placeholder
        from infra.database._db import _get_project
        pool = get_pool()
        project = _get_project()
        with pool.connection() as conn:
            cur = conn.cursor()
            try:
                # 尝试插入；已存在则检查是否可抢占（非 running 或已 stale >10min）
                cur.execute(f"""
                    INSERT INTO generation_status (project, episode, shot_id, stage, status, updated_at)
                    VALUES ({placeholder()}, {placeholder()}, {placeholder()}, {placeholder()}, 'running', CURRENT_TIMESTAMP)
                    ON CONFLICT (project, episode, shot_id, stage) DO UPDATE
                    SET status = 'running', updated_at = CURRENT_TIMESTAMP
                    WHERE generation_status.status != 'running'
                       OR EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - generation_status.updated_at)) > 600
                    RETURNING 1
                """, (project, episode, shot_id, step))
                result = cur.fetchone()
                conn.commit()
                if result:
                    return True
                # 无 RETURNING 行 → 记录存在且正在运行
                return False
            finally:
                cur.close()
    except Exception as e:
        logger.debug(f"DB mark_running 降级: {e}")
        return True  # DB 不可用时放行


# ══════════════════════════════════════════════════════════
#  公共前置检查
# ══════════════════════════════════════════════════════════

_PROJECTS_DIR = None  # 延迟初始化，从 infra.config.get_root() 推导
_ctx_cache: tuple[str, object, object] | None = None  # (config_path, Config, Container)
_ctx_lock = threading.Lock()


def _get_projects_dir() -> Path:
    global _PROJECTS_DIR
    if _PROJECTS_DIR is None:
        from infra.config import projects_dir
        _PROJECTS_DIR = projects_dir()
    return _PROJECTS_DIR


def _validate_config_path(config_path: str) -> str | None:
    """校验 config_path 在 projects/ 目录下。返回错误信息或 None。"""
    resolved = Path(config_path).resolve()
    if not str(resolved).startswith(str(_get_projects_dir().resolve())):
        return f"config_path 必须在 projects/ 目录下: {config_path}"
    return None


def _build_ctx(config_path: str):
    """构建 Config + Container 上下文（带路径安全校验 + 进程内缓存）

    Config 有 mtime 热重载，检测到重载时重建 Container。
    锁粒度：仅保护缓存读写，Config/Container 构建在锁外执行。
    使用双重检查锁：慢路径完成后再次检查缓存，避免重复创建。
    """
    global _ctx_cache

    # 快速路径：缓存命中且未重载（锁内只做读+比较）
    with _ctx_lock:
        if _ctx_cache and _ctx_cache[0] == config_path:
            cfg, cont = _ctx_cache[1], _ctx_cache[2]
            if not cfg._check_reload():
                return cfg, cont
            logger.info("Config 热重载，重建 Container")

    # 慢路径：首次创建 或 热重载后重建（锁外执行，不阻塞其他 worker）
    _ensure_path()
    err = _validate_config_path(config_path)
    if err:
        raise ValueError(err)
    from infra.config import Config
    from api.registry import Container
    cfg = Config(config_path)
    cont = Container(cfg.data)

    # 双重检查：另一个线程可能已经更新了缓存
    with _ctx_lock:
        if _ctx_cache and _ctx_cache[0] == config_path:
            old_cfg = _ctx_cache[1]
            # 如果其他线程已更新到同一 mtime，直接复用，丢弃当前创建的实例
            if old_cfg._mtimes == cfg._mtimes:
                if hasattr(cont, 'shutdown_all'):
                    cont.shutdown_all()
                return _ctx_cache[1], _ctx_cache[2]
        _ctx_cache = (config_path, cfg, cont)
    return cfg, cont


@dataclass
class PrepareParams:
    """_prepare 函数参数 — 消除 10 个参数"""
    config_path: str
    episode: int
    shot_id: str
    step: str
    tool: str
    need_shot: bool = True
    force: bool = False
    cfg: object = None
    cont: object = None
    shot: dict | None = None


def _prepare(params: PrepareParams):
    """防重复 → 工具可用 → 查镜头 → 标记运行 → 返回 (cfg, cont, shot, err)

    传入 cfg/cont/shot 时跳过对应创建/读取，复用已有对象。
    """
    # 1. 并发控制
    if not params.force and not _try_mark_running_atomic(params.episode, params.shot_id, params.step):
        return None, None, None, _skip(params.shot_id, params.step, "该步骤正在执行中")
    if params.force:
        _db_mark_running(params.episode, params.shot_id, params.step)

    # 2. 工具可用性
    ok, reason = _check_available(params.tool, params.config_path)
    if not ok:
        _db_record_step(params.episode, params.shot_id, params.step, {"status": STATUS_SKIPPED, "reason": reason})
        return None, None, None, _skip(params.shot_id, params.step, f"{params.tool} 不可用: {reason}")

    # 3. 查镜头
    shot = params.shot
    if params.need_shot and shot is None:
        shot = _find_shot(params.config_path, params.episode, params.shot_id)
    if params.need_shot and not shot:
        _db_record_step(params.episode, params.shot_id, params.step, {"status": STATUS_ERROR, "reason": "镜头不存在"})
        return None, None, None, _err(params.shot_id, params.step, "镜头不存在")

    # 4. 构建上下文（复用或新建）
    cfg, cont = params.cfg, params.cont
    if cfg is None or cont is None:
        try:
            cfg, cont = _build_ctx(params.config_path)
        except ValueError as e:
            return None, None, None, _err(params.shot_id, params.step, str(e))

    return cfg, cont, shot, None


def _is_default_storyboard(config_path: str, shots: list[dict]) -> bool:
    """检测是否为默认示例分镜表（从 config/default_storyboard.py 动态读取 ID）

    检查所有镜头中引用的角色/场景与默认数据的交集比例，
    避免仅检查前 5 个镜头导致的误判或漏判。
    """
    from config.default_storyboard import DEFAULT_CHARACTERS, DEFAULT_SCENES
    default_chars = {c["id"] for c in DEFAULT_CHARACTERS}
    default_scenes = {s["id"] for s in DEFAULT_SCENES}
    if not default_chars:
        return False
    shot_chars, shot_scenes = set(), set()
    for s in shots:
        for c in (s.get("characters") or "").split("+"):
            c = c.strip()
            if c:
                shot_chars.add(c)
        scene = (s.get("scene_id") or "").strip()
        if scene:
            shot_scenes.add(scene)
    # 所有引用的角色和场景都在默认数据中，且覆盖了全部默认角色
    return (default_chars <= shot_chars and
            default_scenes <= shot_scenes)


def _skip(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": STATUS_SKIPPED, "reason": reason}
def _err(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": reason}
def _done(shot_id, step, path, **kw): return {"shot_id": shot_id, "step": step, "status": STATUS_DONE, "path": path, **kw}


def _init_ctx(config_path: str):
    """初始化通用上下文: Config + Container（用于非 _prepare 的任务）"""
    return _build_ctx(config_path)


def _validate_output(path: str, step: str, *, min_size: int = 0) -> str | None:
    """轻量质量校验 — 检查文件是否存在且有效。返回错误信息或 None。"""
    p = Path(path)
    if not p.exists():
        return f"{step} 输出文件不存在: {p.name}"
    size = p.stat().st_size
    if size < min_size:
        return f"{step} 输出文件过小 ({size} bytes): {p.name}"
    if p.suffix == ".wav" and size < 1000:
        return f"{step} 音频文件异常 (仅 {size} bytes)"
    if p.suffix == ".png" and size < 500:
        return f"{step} 图片文件异常 (仅 {size} bytes)"
    if p.suffix == ".mp4" and size < 10000:
        return f"{step} 视频文件异常 (仅 {size} bytes)"
    return None


def _paths(config_path: str) -> "ProjectPaths":
    """获取统一路径管理对象"""
    from infra.config import Config
    return Config(config_path).paths


def _unique_hash_id(prefix: str, name: str, existing: dict) -> str:
    """基于名字生成确定性短 hash ID，碰撞时自动追加后缀

    Args:
        prefix: ID 前缀（如 "ch"、"sc"）
        name: 角色/场景名（任意语言）
        existing: 已有的 id_remap，用于检测碰撞

    Returns:
        唯一的 hash ID，如 ch_8a3f2b1c 或 ch_8a3f2b1c_2
    """
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    base = f"{prefix}_{h}"
    candidate = base
    counter = 2
    # 检查碰撞：id_remap 中值已存在 且 不是自己
    while candidate in existing.values():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate
