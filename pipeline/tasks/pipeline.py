"""Celery 任务定义 — 管线编排（shot_task / preview / produce / post）"""
from __future__ import annotations

from infra.constants import (
    STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED,
    STEP_TTS, STEP_FIRST_FRAME, STEP_VIDEO, STEP_LIPSYNC,
)
import logging
import os
import time
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from pipeline.celery_app import app
from pipeline.tasks.helpers import (
    _load_shots,
    _db_record_step, _is_default_storyboard,
)
from pipeline.tasks.steps import (
    _run_tts, _run_first_frame, _run_video, _run_lipsync,
)
from pipeline.tasks.preflight import ensure_portraits_and_scenes

logger = logging.getLogger(__name__)

# ── 超时常量（秒）──
_TIMEOUT_SHOT = 1800        # 单镜头
_TIMEOUT_PREPARE = 3600     # 准备阶段（LLM 翻译）
_TIMEOUT_PRODUCE = 7200     # 生产阶段（多镜头）
_TIMEOUT_POST = 1800        # 后期合成
_TIMEOUT_RUN_ALL = 14400    # 全流程（prepare + produce + post）
@app.task(bind=True, name="pipeline_shot", soft_time_limit=_TIMEOUT_SHOT)
def shot_task(self, config_path: str, episode: int, shot_data: dict, force: bool = False) -> dict:
    shot_id = shot_data.get("shot_id", "")
    if not shot_id:
        return {"shot_id": "", "status": STATUS_ERROR, "reason": "镜头数据缺少 shot_id"}

    # 绑定项目作用域，确保 DB 写入到正确项目
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        return _shot_task_inner(self, config_path, episode, shot_data, shot_id, force)


def _shot_task_inner(task, config_path: str, episode: int, shot_data: dict, shot_id: str, force: bool) -> dict:
    """shot_task 核心逻辑（在 project_scope 内执行）"""
    from pipeline.tasks.helpers import _build_ctx
    from infra.database.pool import get_pool
    from infra.database.storyboard_db import get_episode_shots
    cfg, cont = _build_ctx(config_path)

    characters, scenes = _preload_shot_data(cfg)

    # 始终从 DB 读取最新 shot 数据（排队期间用户可能已修改分镜）
    fresh_shot = None
    try:
        for row in get_episode_shots(get_pool(), episode):
            if row.get("shot_id") == shot_id:
                fresh_shot = row
                break
    except Exception as e:
        logger.warning(f"从 DB 读取最新 shot 失败，使用传入数据: {e}")
    if fresh_shot:
        shot_data = fresh_shot

    ctx = {"cfg": cfg, "cont": cont, "shot": shot_data, "characters": characters, "scenes": scenes}

    # 复制避免污染传入的共享 dict + 裁剪 duration
    shot_data = dict(shot_data)
    from infra.constants import clip_duration
    shot_data["duration"] = clip_duration(shot_data.get("duration"))
    ctx["shot"] = shot_data

    results = _run_shot_steps(task, config_path, episode, shot_id, force, ctx)
    errors = [k for k, v in results.items() if v.get("status") == STATUS_ERROR]
    return {"shot_id": shot_id, "status": STATUS_ERROR if errors else STATUS_DONE,
            "done": [k for k, v in results.items() if v.get("status") == STATUS_DONE],
            "skipped": [k for k, v in results.items() if v.get("status") == STATUS_SKIPPED],
            "errors": errors,
            "details": results}


def _preload_shot_data(cfg):
    """预加载角色和场景数据（不加载分镜 — 分镜由调用方从 DB 新鲜读取）"""
    try:
        from infra.config import load_project_entities
        characters, scenes = load_project_entities(cfg.paths)
        logger.info(f"预加载: {len(characters)} 角色, {len(scenes)} 场景")
        return characters, scenes
    except Exception as e:
        logger.warning(f"预加载角色/场景数据失败（后续步骤可能受影响）: {e}")
        return None, None


def _run_shot_steps(task, config_path, episode, shot_id, force, ctx):
    """执行单镜头的 4 个步骤（tts → first_frame → video → lipsync）"""
    steps = [(STEP_TTS, _run_tts), (STEP_FIRST_FRAME, _run_first_frame), (STEP_VIDEO, _run_video), (STEP_LIPSYNC, _run_lipsync)]
    skip_deps = {STEP_VIDEO: [STEP_FIRST_FRAME], STEP_LIPSYNC: [STEP_VIDEO, STEP_TTS]}
    results = {}

    for i, (name, fn) in enumerate(steps):
        deps = skip_deps.get(name, [])
        failed_deps = [d for d in deps if results.get(d, {}).get("status") == STATUS_ERROR]
        if failed_deps:
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_SKIPPED,
                             "reason": f"前置步骤 {', '.join(failed_deps)} 失败，跳过"}
            _db_record_step(episode, shot_id, name, results[name])
            logger.warning(f"[{shot_id}] {name}: 跳过（前置步骤 {', '.join(failed_deps)} 失败）")
            continue

        if task:
            task.update_state(state="PROGRESS", meta={"step": name, "shot_id": shot_id,
                "progress": int((i + 1) / len(steps) * 100), "message": f"[{shot_id}] {name} ({i+1}/{len(steps)})"})
        try:
            t0 = time.time()
            result = fn(config_path, episode, shot_id, force=force, **ctx)
            result["elapsed"] = round(time.time() - t0, 2)
            results[name] = result
            _db_record_step(episode, shot_id, name, result)
            log = logger.info if result.get("status") == STATUS_DONE else logger.warning if result.get("status") == STATUS_ERROR else logger.info
            log(f"[{shot_id}] {name}: {result.get('status')} — {result.get('reason', '')}")
        except SoftTimeLimitExceeded:
            logger.warning(f"[{shot_id}] {name}: 超时（soft_time_limit）")
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_ERROR, "reason": "步骤执行超时"}
            _db_record_step(episode, shot_id, name, results[name])
        except Exception as e:
            logger.error(f"[{shot_id}] {name}: 异常 — {e}", exc_info=True)
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_ERROR, "reason": str(e)}
            _db_record_step(episode, shot_id, name, results[name])

    return results


# ══════════════════════════════════════════════════════════
#  集级任务
# ══════════════════════════════════════════════════════════

def _iterate_shots(task, config_path: str, episode: int, shots: list[dict], progress_base: int = 0, progress_range: int = 100, *, force: bool = False, concurrent: bool = False):
    """逐镜头执行 shot_task，返回结果列表。失败镜头自动重试一次。"""
    total = len(shots)
    results = []
    failed_indices = []

    if concurrent and total > 1:
        results, failed_indices = _run_concurrent(task, config_path, episode, shots, force, progress_base, progress_range)
    else:
        results, failed_indices = _run_serial(task, config_path, episode, shots, force, progress_base, progress_range)

    _retry_failed(task, config_path, episode, shots, results, failed_indices, progress_base, progress_range, total)
    return results


def _run_shot_direct(config_path: str, episode: int, shot: dict, force: bool) -> dict:
    """直接执行 shot_task 逻辑（绕过 Celery 队列，避免 worker 阻塞死锁）

    需要独立设置 project_scope：串行路径冗余但无害，并发路径（ThreadPoolExecutor）
    的 worker 线程不继承主线程的 threading.local，必须显式设置。
    """
    shot_id = shot.get("shot_id", "")
    if not shot_id:
        return {"shot_id": "", "status": STATUS_ERROR, "reason": "镜头数据缺少 shot_id"}
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        return _shot_task_inner(None, config_path, episode, shot, shot_id, force)


def _run_serial(task, config_path, episode, shots, force, progress_base, progress_range):
    """串行执行所有镜头（直接调用，不经过 Celery 队列）"""
    total = len(shots)
    results, failed_indices = [], []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        task.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
            "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = _run_shot_direct(config_path, episode, shot, force)
            results.append(result)
            if result.get("errors"):
                failed_indices.append(i)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})
            failed_indices.append(i)
    return results, failed_indices


def _run_concurrent(task, config_path, episode, shots, force, progress_base, progress_range):
    """错开并发执行所有镜头（直接调用，不经过 Celery 队列）"""
    from infra.concurrency import run_staggered_sync
    total = len(shots)
    results, failed_indices = [], []

    def _make_task(i, shot):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        def _run():
            task.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
                "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
                "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
            return _run_shot_direct(config_path, episode, shot, force)
        return _run

    tasks = [_make_task(i, shot) for i, shot in enumerate(shots)]
    try:
        raw_results = run_staggered_sync(tasks, max_concurrent=2, stagger_ms=3000,
            on_progress=lambda c, t, m: task.update_state(state="PROGRESS",
                meta={"step": "shots", "progress": int(progress_base + c / total * progress_range),
                      "message": f"[{c}/{t}] {m}"}))
    except Exception as e:
        logger.error(f"并发执行器异常: {e}", exc_info=True)
        for i, shot in enumerate(shots):
            shot_id = shot.get("shot_id", f"{i+1:03d}")
            results.append({"shot_id": shot_id, "error": f"并发执行器异常: {e}"})
            failed_indices.append(i)
        return results, failed_indices

    for i, (shot, raw) in enumerate(zip(shots, raw_results)):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        if raw is None:
            results.append({"shot_id": shot_id, "error": "执行失败"})
            failed_indices.append(i)
        elif isinstance(raw, Exception):
            results.append({"shot_id": shot_id, "error": str(raw)})
            failed_indices.append(i)
        else:
            results.append(raw)
            if isinstance(raw, dict) and raw.get("errors"):
                failed_indices.append(i)
    return results, failed_indices


def _retry_failed(task, config_path, episode, shots, results, failed_indices, progress_base, progress_range, total):
    """重试失败的镜头（仅一次）。就地修改 results 列表。"""
    if not failed_indices:
        return
    logger.info(f"重试 {len(failed_indices)} 个失败镜头...")
    for retry_idx, i in enumerate(failed_indices):
        shot = shots[i]
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        task.update_state(state="PROGRESS", meta={"step": "retry", "shot_id": shot_id,
            "progress": int(progress_base + retry_idx / len(failed_indices) * progress_range),
            "message": f"重试镜头 {shot_id} ({retry_idx+1}/{len(failed_indices)})..."})
        try:
            result = _run_shot_direct(config_path, episode, shot, force=True)
            results[i] = result
            logger.info(f"  镜头 {shot_id} 重试完成: done={result.get('done', [])}, errors={result.get('errors', [])}")
        except Exception as e:
            logger.warning(f"  镜头 {shot_id} 重试仍失败: {e}")


@app.task(bind=True, name="pipeline_preview", soft_time_limit=_TIMEOUT_SHOT)
def preview_task(self, config_path: str, episode: int, preset: str = "draft", force: bool = False) -> dict:
    # 绑定项目作用域
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        shots = _load_shots(episode)
        if not shots:
            return {"status": "empty", "message": f"第{episode}集没有镜头"}
        # 生产前自检：确保定妆照和场景图就绪
        self.update_state(state="PROGRESS", meta={"step": "assets", "progress": 2, "message": "检查资产..."})
        ensure_portraits_and_scenes(config_path, self)
        # 根据 preset 缩放生成参数，写入临时配置文件
        effective_cfg = _apply_preset(config_path, preset)
        try:
            return {"status": STATUS_DONE, "episode": episode, "preset": preset,
                    "shots": _iterate_shots(self, effective_cfg, episode, shots, force=force)}
        finally:
            # 清理临时配置文件
            if effective_cfg != config_path:
                try:
                    os.unlink(effective_cfg)
                except OSError as e:
                    logger.debug(f"{type(e).__name__}: {e}")


def _apply_preset(config_path: str, preset: str) -> str:
    """根据 preset 缩放生成参数，返回（可能新建的）配置文件路径"""
    if preset == "draft":
        return config_path  # draft 不修改，使用默认参数
    from infra.config import Config, save_config, load_config
    import tempfile
    cfg = Config(config_path)
    gen = cfg.get("generation", {})
    # 未配置 generation 段时，不覆盖后端默认值
    if not gen:
        return config_path
    base_steps = gen.get("image_steps")
    base_res = gen.get("resolution")
    if not base_steps or not base_res:
        return config_path
    if not isinstance(base_res, (list, tuple)) or len(base_res) != 2:
        return config_path
    if preset == "high":
        overrides = {
            "image_steps": int(base_steps * 1.4),
            "resolution": [min(1920, int(base_res[0] * 1.5)), min(1080, int(base_res[1] * 1.5))],
        }
    elif preset == "standard":
        overrides = {
            "image_steps": int(base_steps * 1.2),
        }
    else:
        return config_path
    # 写入临时配置文件（继承原配置 + 覆盖 generation 段）
    existing = load_config(config_path)
    existing.setdefault("generation", {}).update(overrides)
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", dir=str(Path(config_path).parent))
    os.close(fd)
    try:
        save_config(tmp_path, existing)
    except Exception:
        os.unlink(tmp_path)
        raise
    return tmp_path


@app.task(bind=True, name="pipeline_produce", soft_time_limit=_TIMEOUT_PRODUCE)
def produce_task(self, config_path: str, episode: int, vertical: bool = False, force: bool = False) -> dict:
    """镜头生产（TTS → 首帧 → 视频 → 口型同步）

    注意：后期合成（拼接/字幕/配乐）由 pipeline_post 独立负责，
    一键全流程会依次调用 produce → post，不要在此重复执行。
    """
    # 绑定项目作用域
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        shots = _load_shots(episode)
        if not shots:
            return {"status": "empty", "message": f"第{episode}集没有镜头"}

        # 检测是否为默认示例分镜（U-06）
        if _is_default_storyboard(config_path, shots):
            logger.warning(
                "⚠ 当前分镜表为默认示例数据（林夏/顾辰），"
                "请确认是否需要替换为你自己的剧本。"
                "如需替换，请在 Web 工作台「📝 分镜表」→「🤖 AI 生成」中输入你的大纲。"
            )

        # ── 生产前自检：确保定妆照和场景图就绪 ──
        self.update_state(state="PROGRESS", meta={"step": "assets", "progress": 3, "message": "检查资产..."})
        ensure_portraits_and_scenes(config_path, self)

        results = _iterate_shots(self, config_path, episode, shots, progress_base=5, progress_range=90, force=force)

        return {"status": STATUS_DONE, "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline_run_all", soft_time_limit=_TIMEOUT_RUN_ALL)
def run_all_task(self, config_path: str, episode: int, vertical: bool = False, force: bool = False) -> dict:
    """一键全流程 — prepare → produce → post

    单个 Celery 任务编排全部阶段，前端只需轮询一次。
    bible 已合并到角色生成阶段（AI 生成角色时自动生成），无需独立步骤。
    """
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        stages = [
            ("prepare", lambda: _run_stage_prepare(config_path, episode, force)),
            ("produce", lambda: _run_stage_produce(config_path, episode, force, vertical)),
            ("post",    lambda: _run_stage_post(config_path, episode, vertical)),
        ]
        total = len(stages)
        results = {}
        for i, (name, fn) in enumerate(stages):
            self.update_state(state="PROGRESS", meta={
                "step": name, "progress": int(i / total * 100),
                "message": f"[{i+1}/{total}] {name}..."})
            try:
                result = fn()
                results[name] = result
                if isinstance(result, dict) and result.get("status") == "error":
                    return {"status": STATUS_ERROR, "stage": name,
                            "reason": result.get("reason", "未知错误"), "results": results}
            except Exception as e:
                logger.error(f"全流程 {name} 阶段异常: {e}", exc_info=True)
                return {"status": STATUS_ERROR, "stage": name,
                        "reason": str(e), "results": results}
        return {"status": STATUS_DONE, "episode": episode, "results": results}


def _run_stage_prepare(config_path: str, episode: int, force: bool) -> dict:
    from pipeline.tasks.ai import ai_prepare_task
    # 直接调用（同步），不走 Celery 队列 — 避免单 Worker 死锁
    return ai_prepare_task(config_path, episode, force=force, translate=True)


def _run_stage_produce(config_path: str, episode: int, force: bool, vertical: bool = False) -> dict:
    # 直接调用（同步），不走 Celery 队列
    return produce_task(config_path, episode, vertical=vertical, force=force)


def _run_stage_post(config_path: str, episode: int, vertical: bool) -> dict:
    from pipeline.tasks.media_tasks import post_task
    # 直接调用（同步），不走 Celery 队列
    return post_task(config_path, episode, vertical=vertical)
