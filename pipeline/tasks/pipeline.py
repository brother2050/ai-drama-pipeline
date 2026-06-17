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
from pipeline.app import app
from pipeline.tasks.helpers import (
    _load_shots,
    _db_record_step, _is_default_storyboard,
    _project_scope_from_config,
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
    try:
        with _project_scope_from_config(config_path):
            return _shot_task_inner(self, config_path, episode, shot_data, shot_id, force)
    except Exception as e:
        logger.error(f"[{shot_id}] shot_task 顶层异常: {e}", exc_info=True)
        _db_record_step(episode, shot_id, "pipeline", {"status": STATUS_ERROR, "reason": str(e)})
        return {"shot_id": shot_id, "status": STATUS_ERROR, "reason": str(e)}


def _shot_task_inner(task, config_path: str, episode: int, shot_data: dict, shot_id: str, force: bool) -> dict:
    """shot_task 核心逻辑（在 project_scope 内执行）

    task: Celery task 实例（从 shot_task 调用时为 self，从 _run_shot_direct 调用时为 None）
    """
    from pipeline.tasks.helpers import _build_ctx
    from infra.database.pool import get_pool
    cfg, cont = _build_ctx(config_path)

    characters, scenes, char_name_to_id, scene_name_to_id = _preload_shot_data(cfg)

    # 始终从 DB 读取最新 shot 数据（排队期间用户可能已修改分镜）
    fresh_shot = None
    try:
        from infra.database.storyboard_db import get_shot
        fresh_shot = get_shot(get_pool(), episode, shot_id)
    except Exception as e:
        logger.debug(f"从 DB 读取最新 shot 失败，使用传入数据: {e}")
    if fresh_shot:
        shot_data = fresh_shot

    ctx = {"cfg": cfg, "cont": cont, "shot": shot_data,
           "characters": _key_by_name(characters), "scenes": _key_by_name(scenes),
           "char_name_to_id": char_name_to_id, "scene_name_to_id": scene_name_to_id}

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
        from infra.config import load_project_entities, load_char_name_to_id, load_scene_name_to_id
        characters, scenes = load_project_entities(cfg.paths)
        # 构建 name→id 映射（资产文件用 hash ID，分镜用名称）
        char_name_to_id = load_char_name_to_id(cfg.paths)
        scene_name_to_id = load_scene_name_to_id(cfg.paths)
        logger.info(f"预加载: {len(characters)} 角色, {len(scenes)} 场景")
        return characters, scenes, char_name_to_id, scene_name_to_id
    except Exception as e:
        logger.warning(f"预加载角色/场景数据失败（后续步骤可能受影响）: {e}")
        return None, None, {}, {}


def _key_by_name(entities: dict[str, dict] | None) -> dict[str, dict]:
    """将 {id: entity} dict 转换为 {name: entity} dict（分镜用 name 引用）"""
    if not entities:
        return {}
    return {e.get("name", eid): e for eid, e in entities.items() if e.get("name")}


def _run_shot_steps(task, config_path, episode, shot_id, force, ctx):
    """执行单镜头的 4 个步骤（tts → first_frame → video → lipsync）

    步骤级流水线：DB 写入异步提交到线程池，不阻塞下一步 AI 调用。
    返回前等待所有异步 DB 写入完成，确保前端轮询看到最新状态。

    task: Celery task 实例（可为 None，从 _run_shot_direct 调用时）
    """
    from pipeline.tasks.helpers import _async_db
    steps = [(STEP_TTS, _run_tts), (STEP_FIRST_FRAME, _run_first_frame), (STEP_VIDEO, _run_video), (STEP_LIPSYNC, _run_lipsync)]
    skip_deps = {STEP_VIDEO: [STEP_FIRST_FRAME], STEP_LIPSYNC: [STEP_VIDEO, STEP_TTS]}
    results = {}

    for i, (name, fn) in enumerate(steps):
        deps = skip_deps.get(name, [])
        # 前置步骤失败或被跳过时，当前步骤也应跳过（级联跳过）
        failed_deps = [d for d in deps if results.get(d, {}).get("status") in (STATUS_ERROR, STATUS_SKIPPED)]
        if failed_deps:
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_SKIPPED,
                             "reason": f"前置步骤 {', '.join(failed_deps)} 失败，跳过"}
            _async_db.submit(episode, shot_id, name, results[name])
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
            # 异步 DB 写入，不阻塞下一步 AI 调用
            _async_db.submit(episode, shot_id, name, result)
            log = logger.info if result.get("status") == STATUS_DONE else logger.warning if result.get("status") == STATUS_ERROR else logger.info
            log(f"[{shot_id}] {name}: {result.get('status')} — {result.get('reason', '')}")
        except SoftTimeLimitExceeded:
            logger.warning(f"[{shot_id}] {name}: 超时（soft_time_limit）")
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_ERROR, "reason": "步骤执行超时"}
            _async_db.submit(episode, shot_id, name, results[name])
        except Exception as e:
            logger.error(f"[{shot_id}] {name}: 异常 — {e}", exc_info=True)
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_ERROR, "reason": str(e)}
            _async_db.submit(episode, shot_id, name, results[name])

    # 等待所有异步 DB 写入完成（确保前端轮询看到最新状态）
    failed_writes = _async_db.wait()
    if failed_writes:
        logger.warning(f"[{shot_id}] {failed_writes} 个异步 DB 写入失败")

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
    with _project_scope_from_config(config_path):
        return _shot_task_inner(None, config_path, episode, shot, shot_id, force)


def _run_serial(task, config_path, episode, shots, force, progress_base, progress_range):
    """串行执行所有镜头（直接调用，不经过 Celery 队列）"""
    total = len(shots)
    results, failed_indices = [], []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        if task:
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
    from infra.concurrency.groups import run_staggered_sync
    total = len(shots)
    results, failed_indices = [], []

    def _make_task(i, shot):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        def _run():
            if task:
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
                      "message": f"[{c}/{t}] {m}"}) if task else None)
    except Exception as e:
        logger.error(f"并发执行器异常: {e}", exc_info=True)
        # 降级：所有镜头标记失败
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
    """重试失败的镜头（仅一次，force=True 跳过文件存在性检查）。就地修改 results 列表。"""
    if not failed_indices:
        return
    logger.info(f"重试 {len(failed_indices)} 个失败镜头...")
    for retry_idx, i in enumerate(failed_indices):
        shot = shots[i]
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        if task:
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
    with _project_scope_from_config(config_path):
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
    # 类型安全：YAML 手动编辑可能产生字符串，需转为数值
    try:
        base_steps = int(base_steps)
    except (ValueError, TypeError):
        logger.warning(f"generation.image_steps 非法值: {base_steps!r}，跳过预设缩放")
        return config_path
    if not isinstance(base_res, (list, tuple)) or len(base_res) != 2:
        logger.warning(f"generation.resolution 格式错误: {base_res!r}，跳过预设缩放")
        return config_path
    try:
        base_res = [int(v) for v in base_res]
    except (ValueError, TypeError):
        logger.warning(f"generation.resolution 非法值: {base_res!r}，跳过预设缩放")
        return config_path
    if preset == "high":
        overrides = {
            "image_steps": round(base_steps * 1.4),
            "resolution": [min(1920, round(base_res[0] * 1.5)) & ~1, min(1080, round(base_res[1] * 1.5)) & ~1],
        }
    elif preset == "standard":
        overrides = {
            "image_steps": round(base_steps * 1.2),
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
def produce_task(self, config_path: str, episode: int, force: bool = False) -> dict:
    """镜头生产（TTS → 首帧 → 视频 → 口型同步）

    注意：后期合成（拼接/字幕/配乐）由 pipeline_post 独立负责，
    一键全流程会依次调用 produce → post，不要在此重复执行。
    竖屏模式仅在 post 阶段生效（横转竖），不影响 produce 的分辨率。
    """
    # 绑定项目作用域
    with _project_scope_from_config(config_path):
        shots = _load_shots(episode)
        if not shots:
            return {"status": "empty", "message": f"第{episode}集没有镜头"}

        # 检测是否为默认示例分镜
        if _is_default_storyboard(config_path, shots):
            logger.warning(
                "⚠ 当前分镜表为默认示例数据，请确认是否需要替换为你自己的剧本。"
                "如需替换，请在 Web 工作台「📝 分镜表」→「🤖 AI 生成」中输入你的大纲。"
            )

        # ── 生产前自检：确保定妆照和场景图就绪 ──
        self.update_state(state="PROGRESS", meta={"step": "assets", "progress": 3, "message": "检查资产..."})
        ensure_portraits_and_scenes(config_path, self)

        results = _iterate_shots(self, config_path, episode, shots, progress_base=5, progress_range=90, force=force)

        return {"status": STATUS_DONE, "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline_run_all", soft_time_limit=_TIMEOUT_RUN_ALL)
def run_all_task(self, config_path: str, episode: int, vertical: bool = False, force: bool = False) -> dict:
    """一键全流程 — entities → prepare → portraits → produce → post

    单个 Celery 任务编排全部阶段，前端只需轮询一次。
    """
    with _project_scope_from_config(config_path):
        # 前置检查：分镜必须存在
        from engines.content.storyboard import load_storyboard
        shots = load_storyboard(episode)
        if not shots:
            return {"status": STATUS_ERROR, "reason": f"第{episode}集没有分镜，请先在 Web 工作台生成分镜"}

        stages = [
            ("entities",  lambda: _run_stage_entities(config_path, episode)),
            ("prepare",   lambda: _run_stage_prepare(config_path, episode, force)),
            ("portraits", lambda: _run_stage_portraits(config_path, force)),
            ("produce",   lambda: _run_stage_produce(config_path, episode, force, vertical)),
            ("post",      lambda: _run_stage_post(config_path, episode, vertical)),
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
                if isinstance(result, dict):
                    if result.get("status") == STATUS_ERROR:
                        return {"status": STATUS_ERROR, "stage": name,
                                "reason": result.get("reason", "未知错误"), "results": results}
                    if result.get("status") == STATUS_SKIPPED:
                        logger.warning(f"全流程 {name} 阶段跳过: {result.get('reason', '')}")
                    # produce 阶段：镜头级错误不阻断全流程，但记录警告
                    if result.get("_has_errors"):
                        logger.warning(f"全流程 {name} 阶段有 {result['_error_count']} 个镜头失败")
            except Exception as e:
                logger.error(f"全流程 {name} 阶段异常: {e}", exc_info=True)
                return {"status": STATUS_ERROR, "stage": name,
                        "reason": str(e), "results": results}
        return {"status": STATUS_DONE, "episode": episode, "results": results,
                "quality_issues": _collect_all_quality_issues(results)}


def _collect_all_quality_issues(results: dict) -> list:
    """从各阶段结果中汇总所有 quality_issues"""
    all_issues = []
    for stage_key in ("prepare", "post"):
        stage_result = results.get(stage_key)
        if isinstance(stage_result, dict):
            qis = stage_result.get("quality_issues")
            if isinstance(qis, list):
                all_issues.extend(qis)
    return all_issues


def _run_stage_entities(config_path: str, episode: int) -> dict:
    from pipeline.tasks.ai import ai_entities_task
    return ai_entities_task.apply(args=[config_path, episode]).get()


def _run_stage_portraits(config_path: str, force: bool) -> dict:
    from pipeline.tasks.portrait import portraits_task
    result = portraits_task.apply(args=[config_path], kwargs={"force": force}).get()
    if not isinstance(result, dict):
        return {"status": STATUS_ERROR, "reason": f"定妆照任务返回异常: {type(result).__name__}"}
    return result


def _run_stage_prepare(config_path: str, episode: int, force: bool) -> dict:
    from pipeline.tasks.prepare import ai_prepare_task
    result = ai_prepare_task.apply(args=[config_path, episode], kwargs={"force": force, "translate": True}).get()
    if not isinstance(result, dict):
        return {"status": STATUS_ERROR, "reason": f"准备阶段任务返回异常: {type(result).__name__}"}
    return result


def _run_stage_produce(config_path: str, episode: int, force: bool, vertical: bool = False) -> dict:
    result = produce_task.apply(args=[config_path, episode], kwargs={"force": force}).get()
    # 检查镜头级错误（produce_task 顶层 status 始终为 DONE，需检查子任务）
    if isinstance(result, dict):
        shot_errors = [s for s in result.get("shots", [])
                       if isinstance(s, dict) and (s.get("errors") or s.get("error"))]
        if shot_errors:
            result["_has_errors"] = True
            result["_error_count"] = len(shot_errors)
    return result


def _run_stage_post(config_path: str, episode: int, vertical: bool) -> dict:
    from pipeline.tasks.media import post_task
    result = post_task.apply(args=[config_path, episode], kwargs={"vertical": vertical}).get()
    if not isinstance(result, dict):
        return {"status": STATUS_ERROR, "reason": f"后期合成任务返回异常: {type(result).__name__}"}
    return result
