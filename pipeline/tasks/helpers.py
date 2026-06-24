"""Celery 任务定义 — 工具函数"""
from __future__ import annotations

import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from infra.constants import STATUS_RUNNING, STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED

# 文件大小阈值（bytes）— 小于此值视为异常
MIN_WAV_SIZE = 1000
MIN_PNG_SIZE = 500
MIN_MP4_SIZE = 10000

logger = logging.getLogger(__name__)

# ── Config 实例缓存（避免 _shot_dir/_paths/_check_available 每次 new Config）──
_cfg_cache: dict[str, object] = {}  # config_path → Config
_cfg_cache_lock = threading.Lock()


def _get_config(config_path: str):
    """获取缓存的 Config 实例（mtime 变化时自动重载）"""
    from infra.config import Config
    # 快速路径：已缓存
    with _cfg_cache_lock:
        cfg = _cfg_cache.get(config_path)
        if cfg is not None:
            cfg._check_reload()
            return cfg
    # 慢路径：首次创建
    cfg = Config(config_path)
    with _cfg_cache_lock:
        existing = _cfg_cache.get(config_path)
        if existing is not None:
            return existing  # 另一线程已创建
        _cfg_cache[config_path] = cfg
    return cfg


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


def _load_shots(episode: int) -> list[dict]:
    """从 DB 加载指定集的镜头列表"""
    from engines.content.storyboard import load_storyboard
    return load_storyboard(episode=episode)


def _find_shot(episode: int, shot_id: str) -> dict | None:
    """查找单个镜头（DB 精确查询，不加载全集）"""
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_shot
        return get_shot(get_pool(), episode, shot_id)
    except ConnectionError as e:
        logger.warning(f"DB 连接失败，使用传入数据: {e}")
        # DB 不可用时回退到全量加载
        for s in _load_shots(episode):
            if s.get("shot_id") == shot_id:
                return s
        return None
    except Exception as e:
        logger.error(f"DB 读取意外异常: {e}", exc_info=True)
        # DB 不可用时回退到全量加载
        for s in _load_shots(episode):
            if s.get("shot_id") == shot_id:
                return s
        return None


def _shot_dir(config_path: str, episode: int, shot_id: str) -> Path:
    return _get_config(config_path).paths.shot_dir(episode, shot_id)


def _check_available(tool_name: str, config_path: str) -> tuple[bool, str]:
    """检测工具可用性"""
    from infra.toolcheck import check_tool
    result = check_tool(tool_name, _get_config(config_path).data)
    return result["available"], result.get("reason", "")


def _db_record_step(episode: int, shot_id: str, step: str, result: dict) -> None:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import upsert_status
        upsert_status(get_pool(), episode, shot_id, step,
                      status=result.get("status", "unknown"), path=result.get("path", ""),
                      error=result.get("reason", "") if result.get("status") in (STATUS_SKIPPED, STATUS_ERROR) else "",
                      elapsed=result.get("elapsed", 0.0))
    except Exception as e:
        logger.error(f"AsyncDBWriter 写入失败（数据可能未持久化）[{episode}/{shot_id}/{step}]: {e}", exc_info=True)


class AsyncDBWriter:
    """异步 DB 写入器 — 步骤级流水线的核心

    将 DB 写入提交到线程池，不阻塞下一步的 AI 调用。
    shot_task 返回前调用 wait() 确保持久化。

    用法:
        writer = AsyncDBWriter()
        writer.submit(episode, shot_id, step, result)  # 非阻塞
        # ... 下一步 AI 调用开始 ...
        writer.wait()  # 等待所有写入完成
    """

    def __init__(self, max_workers: int = 2):
        import atexit
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="async-db")
        self._futures: list = []
        atexit.register(self._pool.shutdown, wait=False)

    def submit(self, episode: int, shot_id: str, step: str, result: dict) -> None:
        """异步提交 DB 写入，不阻塞调用方"""
        f = self._pool.submit(_db_record_step, episode, shot_id, step, result)
        self._futures.append(f)

    def wait(self, timeout: float = 10.0) -> int:
        """等待所有待确认的 DB 写入完成，返回失败数"""
        failed = 0
        for f in self._futures:
            try:
                f.result(timeout=timeout)
            except Exception:
                failed += 1
        self._futures.clear()
        return failed


# 模块级单例（Celery prefork 模型下每个 Worker 子进程独立持有）
_async_db = AsyncDBWriter()


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
                # 尝试插入；已存在则检查是否可抢占（非 running 或已 stale >30min）
                cur.execute(f"""
                    INSERT INTO generation_status (project, episode, shot_id, stage, status, updated_at)
                    VALUES ({placeholder()}, {placeholder()}, {placeholder()}, {placeholder()}, 'running', CURRENT_TIMESTAMP)
                    ON CONFLICT (project, episode, shot_id, stage) DO UPDATE
                    SET status = 'running', updated_at = CURRENT_TIMESTAMP
                    WHERE generation_status.status != 'running'
                       OR EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - generation_status.updated_at)) > 1800
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
# 进程内缓存：Celery prefork 模型下每个 Worker 子进程独立持有副本，天然安全。
# 若切换到 eventlet/gevent 等协程模型，需改用 threading.local() 或 per-task 缓存。
_ctx_cache: tuple[str, object, object] | None = None  # (config_path, Config, Container)
_ctx_lock = threading.Lock()


def invalidate_ctx_cache():
    """失效 pipeline 上下文缓存（文件系统监控回调）

    当角色/场景 YAML 文件变化时调用，强制下次 _build_ctx 重建 Config + Container。
    不主动关闭旧 Container — 后端实例自然过期，避免中断正在使用后端的任务。
    """
    global _ctx_cache
    with _cfg_cache_lock:
        _cfg_cache.clear()
    with _ctx_lock:
        _ctx_cache = None
    logger.info("Pipeline ctx 缓存已失效（文件变化触发）")


# 注册缓存失效钩子：文件变化时由 infra/file_watcher 通过 hooks 系统触发
try:
    from infra.hooks import on_cache_invalidate
    on_cache_invalidate(priority=100)(invalidate_ctx_cache)
except ImportError:
    pass


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

    Config 有 mtime 热重载，检测到重载时用 reload() 增量更新 Container（避免全量重建）。
    锁粒度：仅保护缓存读写，Config/Container 构建在锁外执行。
    使用双重检查锁：慢路径完成后再次检查缓存，避免重复创建。

    Celery prefork 模型下每个 Worker 子进程单线程执行任务（worker_prefetch_multiplier=1），
    但 Web 服务器是多线程的，因此需要线程安全。
    """
    global _ctx_cache

    # 快速路径：缓存命中且未重载（锁内只做读+比较）
    with _ctx_lock:
        if _ctx_cache and _ctx_cache[0] == config_path:
            cfg, cont = _ctx_cache[1], _ctx_cache[2]
            if not cfg._check_reload():
                return cfg, cont
            # Config 热重载：用 reload() 增量更新 Container，不全量重建
            logger.info("Config 热重载，增量更新 Container")
            changed = cont.reload(cfg.data)
            if changed:
                logger.info(f"  Container 已更新: {changed}")
            return cfg, cont

    # 慢路径：首次创建（锁外执行，不阻塞其他 worker）
    _ensure_path()
    err = _validate_config_path(config_path)
    if err:
        raise ValueError(err)
    from infra.config import Config
    from api.registry import Container
    cfg = Config(config_path)
    cont = Container(cfg.data)

    # 双重检查：另一个线程可能已经创建了缓存
    with _ctx_lock:
        if _ctx_cache and _ctx_cache[0] == config_path:
            old_cfg = _ctx_cache[1]
            # 如果其他线程已更新到同一 mtime，直接复用
            if old_cfg._mtimes == cfg._mtimes:
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
        skip_result = _skip(params.shot_id, params.step, "该步骤正在执行中")
        _db_record_step(params.episode, params.shot_id, params.step, skip_result)
        return None, None, None, skip_result
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
        shot = _find_shot(params.episode, params.shot_id)
    if params.need_shot and not shot:
        _db_record_step(params.episode, params.shot_id, params.step, {"status": STATUS_ERROR, "reason": "镜头不存在"})
        return None, None, None, _err(params.shot_id, params.step, "镜头不存在")

    # 4. 构建上下文（复用或新建）
    cfg, cont = params.cfg, params.cont
    if cfg is None or cont is None:
        try:
            cfg, cont = _build_ctx(params.config_path)
        except ValueError as e:
            err_result = _err(params.shot_id, params.step, str(e))
            _db_record_step(params.episode, params.shot_id, params.step, err_result)
            return None, None, None, err_result

    return cfg, cont, shot, None


def _is_default_storyboard(config_path: str, shots: list[dict]) -> bool:
    """检测是否为默认示例分镜表（从 config/default_storyboard.py 动态读取 ID）

    检查所有镜头中引用的角色/场景与默认数据的交集比例，
    避免仅检查前 5 个镜头导致的误判或漏判。
    """
    from config.default_storyboard import DEFAULT_CHARACTERS, DEFAULT_SCENES
    default_char_names = {c["name"] for c in DEFAULT_CHARACTERS}
    default_scene_names = {s["name"] for s in DEFAULT_SCENES}
    if not default_char_names:
        return False
    from engines.utils.shot import parse_char_names
    shot_chars, shot_scenes = set(), set()
    for s in shots:
        shot_chars.update(parse_char_names(s))
        scene = (s.get("scene_name") or "").strip()
        if scene:
            shot_scenes.add(scene)
    # 所有引用的角色和场景都在默认数据中，且覆盖了全部默认角色
    return (default_char_names <= shot_chars and
            default_scene_names <= shot_scenes)


def _skip(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": STATUS_SKIPPED, "reason": reason}
def _err(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": reason}
def _done(shot_id, step, path, **kw): return {"shot_id": shot_id, "step": step, "status": STATUS_DONE, "path": path, **kw}


def _validate_output(path: str, step: str, *, min_size: int = 0) -> str | None:
    """轻量质量校验 — 检查文件是否存在、大小、格式完整性。返回错误信息或 None。"""
    p = Path(path)
    if not p.exists():
        return f"{step} 输出文件不存在: {p.name}"
    size = p.stat().st_size
    if size < min_size:
        return f"{step} 输出文件过小 ({size} bytes): {p.name}"
    if p.suffix == ".wav" and size < MIN_WAV_SIZE:
        return f"{step} 音频文件异常 (仅 {size} bytes)"
    if p.suffix == ".png" and size < MIN_PNG_SIZE:
        return f"{step} 图片文件异常 (仅 {size} bytes)"
    if p.suffix == ".mp4" and size < MIN_MP4_SIZE:
        return f"{step} 视频文件异常 (仅 {size} bytes)"
    # 轻量格式完整性校验（magic bytes）
    try:
        with open(p, "rb") as f:
            header = f.read(12)
        if p.suffix == ".png" and header[:4] != b'\x89PNG':
            return f"{step} PNG 文件头损坏: {p.name}"
        if p.suffix == ".wav" and header[:4] != b'RIFF':
            return f"{step} WAV 文件头损坏: {p.name}"
        if p.suffix == ".mp4" and b'ftyp' not in header[:12]:
            return f"{step} MP4 文件头损坏: {p.name}"
    except OSError:
        pass  # 读取失败不阻断，让后续步骤报错
    return None


def _paths(config_path: str):
    """获取统一路径管理对象"""
    return _get_config(config_path).paths


def comfyui_generate(shot_id: str, step: str, comfyui, workflow: dict, out_dir: Path,
                     output_name: str, min_size: int = 500) -> dict:
    """ComfyUI 生成通用流程 — 看门狗跟踪 + 并发组限流 + 重试 + 输出校验

    消除 frame.py / video.py 中重复的 _do_generate + safe_run + 验证模式。

    Args:
        shot_id: 镜头 ID
        step: 步骤名（如 "first_frame" / "video"）
        comfyui: ComfyUI 后端实例
        workflow: ComfyUI 工作流
        out_dir: 输出目录
        output_name: 输出文件名（如 "frame.png" / "video.mp4"）
        min_size: 最小文件大小（bytes）

    Returns:
        {"status": "done"/"error", ...}
    """
    from infra.globals import get_watchdog, get_concurrency_groups
    from infra.concurrency.executor import safe_run
    wd = get_watchdog()
    groups = get_concurrency_groups()

    def _do():
        with groups.acquire("comfyui"):
            with wd.track(f"{shot_id}:{step}", backend="comfyui"):
                return comfyui.generate(workflow, str(out_dir))

    try:
        files = safe_run(_do, retries=2, base_delay=2.0, task_id=f"{shot_id}:{step}")
    except Exception as e:
        return _err(shot_id, step, f"ComfyUI {step} 失败: {e}")
    if not files:
        return _err(shot_id, step, "ComfyUI 未返回任何文件")

    out_path = str(out_dir / output_name)
    try:
        os.replace(files[0], out_path)
    except OSError:
        # 跨文件系统时 os.replace 失败，回退到 shutil.move
        import shutil
        shutil.move(files[0], out_path)
    err = _validate_output(out_path, step, min_size=min_size)
    if err:
        return _err(shot_id, step, err)
    return _done(shot_id, step, out_path)
