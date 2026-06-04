"""Celery 任务定义 — 管线编排（shot_task / preview / produce / post）"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED
import logging
import os
import time
from pathlib import Path

from pipeline.celery_app import app
from pipeline.tasks.helpers import (
    _ensure_path, _load_shots,
    _db_record_step, _prepare,
    _is_default_storyboard,
    _init_ctx,
)
from pipeline.tasks.steps import (
    _run_tts, _run_first_frame, _run_video, _run_lipsync,
)
from pipeline.tasks.media_tasks import _run_post

logger = logging.getLogger(__name__)
@app.task(bind=True, name="pipeline_shot", soft_time_limit=1800)
def shot_task(self, config_path: str, episode: int, shot_data: dict, force: bool = False) -> dict:
    shot_id = shot_data.get("shot_id", "")
    if not shot_id:
        return {"shot_id": "", "status": STATUS_ERROR, "reason": "镜头数据缺少 shot_id"}

    # 绑定项目作用域，确保 DB 写入到正确项目
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        return _shot_task_inner(self, config_path, episode, shot_data, shot_id, force)


def _shot_task_inner(self, config_path: str, episode: int, shot_data: dict, shot_id: str, force: bool) -> dict:
    """shot_task 核心逻辑（在 project_scope 内执行）"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    from infra.database.pool import get_pool
    from infra.database.storyboard_db import get_episode_shots
    cfg = Config(config_path)
    cont = Container(cfg.data)

    characters, scenes = _preload_shot_data(cfg)

    # 始终从 DB 读取最新 shot 数据（排队期间用户可能已修改分镜）
    fresh_shot = None
    try:
        for row in get_episode_shots(get_pool(), episode):
            if row.get("shot_id") == shot_id:
                fresh_shot = row
                break
    except Exception as e:
        logger.debug(f"从 DB 读取最新 shot 失败，使用传入数据: {e}")
    if fresh_shot:
        shot_data = fresh_shot

    ctx = {"cfg": cfg, "cont": cont, "shot": shot_data, "characters": characters, "scenes": scenes}

    try:
        shot_data["duration"] = max(2, min(8, int(shot_data.get("duration", 4))))
    except (ValueError, TypeError):
        shot_data["duration"] = 4

    results = _run_shot_steps(self, config_path, episode, shot_id, force, ctx)
    return {"shot_id": shot_id,
            "done": [k for k, v in results.items() if v.get("status") == STATUS_DONE],
            "skipped": [k for k, v in results.items() if v.get("status") == STATUS_SKIPPED],
            "errors": [k for k, v in results.items() if v.get("status") == STATUS_ERROR],
            "details": results}


def _preload_shot_data(cfg):
    """预加载角色和场景数据"""
    try:
        from engines.shot_manager import ShotManager
        sm = ShotManager(str(cfg.paths.config_dir))
        return sm.characters, sm.scenes
    except Exception as e:
        logger.warning(f"预加载角色/场景数据失败（后续步骤可能受影响）: {e}")
        return None, None


def _run_shot_steps(self, config_path, episode, shot_id, force, ctx):
    """执行单镜头的 4 个步骤（tts → first_frame → video → lipsync）"""
    steps = [("tts", _run_tts), ("first_frame", _run_first_frame), ("video", _run_video), ("lipsync", _run_lipsync)]
    skip_deps = {"video": "first_frame", "lipsync": "video"}
    results = {}

    for i, (name, fn) in enumerate(steps):
        dep = skip_deps.get(name)
        if dep and results.get(dep, {}).get("status") == STATUS_ERROR:
            results[name] = {"shot_id": shot_id, "step": name, "status": STATUS_SKIPPED,
                             "reason": f"前置步骤 {dep} 失败，跳过"}
            _db_record_step(episode, shot_id, name, results[name])
            logger.warning(f"[{shot_id}] {name}: 跳过（前置步骤 {dep} 失败）")
            continue

        self.update_state(state="PROGRESS", meta={"step": name, "shot_id": shot_id,
            "progress": int((i + 1) / len(steps) * 100), "message": f"[{shot_id}] {name} ({i+1}/{len(steps)})"})
        try:
            t0 = time.time()
            result = fn(config_path, episode, shot_id, force=force, **ctx)
            result["elapsed"] = round(time.time() - t0, 2)
            results[name] = result
            _db_record_step(episode, shot_id, name, result)
            log = logger.info if result.get("status") == STATUS_DONE else logger.warning if result.get("status") == STATUS_ERROR else logger.info
            log(f"[{shot_id}] {name}: {result.get('status')} — {result.get('reason', '')}")
        except Exception as e:
            logger.error(f"[{shot_id}] {name}: 异常 — {e}", exc_info=True)
            results[name] = {"status": STATUS_ERROR, "reason": str(e)}
            _db_record_step(episode, shot_id, name, results[name])

    return results


# ══════════════════════════════════════════════════════════
#  集级任务
# ══════════════════════════════════════════════════════════

def _iterate_shots(self, config_path: str, episode: int, shots: list[dict], progress_base: int = 0, progress_range: int = 100, *, force: bool = False, concurrent: bool = False):
    """逐镜头执行 shot_task，返回结果列表。失败镜头自动重试一次。"""
    total = len(shots)
    results = []
    failed_indices = []

    if concurrent and total > 1:
        results, failed_indices = _run_concurrent(self, config_path, episode, shots, force, progress_base, progress_range)
    else:
        results, failed_indices = _run_serial(self, config_path, episode, shots, force, progress_base, progress_range)

    _retry_failed(self, config_path, episode, shots, results, failed_indices, progress_base, progress_range, total)
    return results


def _run_serial(self, config_path, episode, shots, force, progress_base, progress_range):
    """串行执行所有镜头"""
    total = len(shots)
    results, failed_indices = [], []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
            "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = shot_task.apply(args=[config_path, episode, shot], kwargs={"force": force}).get(timeout=1800)
            results.append(result)
            if result.get("errors"):
                failed_indices.append(i)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})
            failed_indices.append(i)
    return results, failed_indices


def _run_concurrent(self, config_path, episode, shots, force, progress_base, progress_range):
    """错开并发执行所有镜头"""
    from infra.concurrency import run_staggered_sync
    total = len(shots)
    results, failed_indices = [], []

    def _make_task(i, shot):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        def _run():
            self.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
                "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
                "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
            return shot_task.apply(args=[config_path, episode, shot], kwargs={"force": force}).get(timeout=1800)
        return _run

    tasks = [_make_task(i, shot) for i, shot in enumerate(shots)]
    raw_results = run_staggered_sync(tasks, max_concurrent=2, stagger_ms=3000,
        on_progress=lambda c, t, m: self.update_state(state="PROGRESS",
            meta={"step": "shots", "progress": int(progress_base + c / total * progress_range),
                  "message": f"[{c}/{t}] {m}"}))

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
            if raw.get("errors"):
                failed_indices.append(i)
    return results, failed_indices


def _retry_failed(self, config_path, episode, shots, results, failed_indices, progress_base, progress_range, total):
    """重试失败的镜头（仅一次）"""
    if not failed_indices:
        return
    logger.info(f"重试 {len(failed_indices)} 个失败镜头...")
    for i in failed_indices:
        shot = shots[i]
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={"step": "retry", "shot_id": shot_id,
            "progress": int(progress_base + (total + len(failed_indices)) / total * progress_range),
            "message": f"重试镜头 {shot_id}..."})
        try:
            result = shot_task.apply(args=[config_path, episode, shot], kwargs={"force": True}).get(timeout=1800)
            results[i] = result
            logger.info(f"  镜头 {shot_id} 重试完成: done={result.get('done', [])}, errors={result.get('errors', [])}")
        except Exception as e:
            logger.warning(f"  镜头 {shot_id} 重试仍失败: {e}")

    return results


@app.task(bind=True, name="pipeline_preview", soft_time_limit=1800)
def preview_task(self, config_path: str, episode: int, preset: str = "draft", force: bool = False) -> dict:
    # 绑定项目作用域
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        shots = _load_shots(config_path, episode)
        if not shots:
            return {"status": "empty", "message": f"第{episode}集没有镜头"}
        # 生产前自检：确保定妆照和场景图就绪
        self.update_state(state="PROGRESS", meta={"step": "assets", "progress": 2, "message": "检查资产..."})
        _ensure_portraits_and_scenes(config_path, self, episode=episode)
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
    save_config(tmp_path, existing)
    return tmp_path


@app.task(bind=True, name="pipeline_produce", soft_time_limit=7200)
def produce_task(self, config_path: str, episode: int, vertical: bool = False, force: bool = False) -> dict:
    # 绑定项目作用域
    project_name = Path(config_path).resolve().parent.parent.name
    from infra.database._db import project_scope
    with project_scope(project_name):
        shots = _load_shots(config_path, episode)
        if not shots:
            return {"status": "empty", "message": f"第{episode}集没有镜头"}

        # 检测是否为默认示例分镜（U-06）
        if _is_default_storyboard(config_path, shots):
            logger.warning(
                "⚠ 当前分镜表为默认示例数据（林夏/顾辰），"
                "请确认是否需要替换为你自己的剧本。"
                "如需替换，请使用 AI 生成或通过 Web 工作台编辑: "
                "drama generate storyboard 1 --outline your_outline.txt"
            )

        # ── 生产前自检：确保定妆照和场景图就绪 ──
        self.update_state(state="PROGRESS", meta={"step": "assets", "progress": 3, "message": "检查资产..."})
        _ensure_portraits_and_scenes(config_path, self, episode=episode)

        results = _iterate_shots(self, config_path, episode, shots, progress_base=5, progress_range=85, force=force)
        self.update_state(state="PROGRESS", meta={"step": "post", "progress": 90, "message": "后期合成..."})
        try:
            _run_post(config_path, episode, vertical)
        except Exception as e:
            logger.error(f"后期失败: {e}", exc_info=True)

        # ── 质量门禁：生产后检查 ──
        try:
            from engines.quality_gate import check_quality
            proj_root = str(Path(config_path).resolve().parent.parent)
            issues = check_quality("after_produce", proj_root, episode=episode)
            if issues:
                errors = [i for i in issues if i["severity"] == "error"]
                warnings = [i for i in issues if i["severity"] == "warning"]
                for w in warnings:
                    logger.warning(f"⚠ 质量检查: {w['name']} — {w['message']}")
                for e in errors:
                    logger.error(f"❌ 质量检查: {e['name']} — {e['message']}")
                results["quality_issues"] = issues
        except Exception as e:
            logger.debug(f"质量门禁跳过: {e}")

        return {"status": STATUS_DONE, "episode": episode, "shots": results}


def _check_portrait_readiness(paths) -> tuple[list[str], list[str]]:
    """检查定妆照就绪状态 → (需要准备的角色名, 需要定妆照的角色名)"""
    from infra.config import load_yaml_entities
    chars = load_yaml_entities(paths.characters_dir, "character")
    need_prepare, need_portrait = [], []
    for char in chars:
        cid = char.get("id", "")
        if not cid:
            continue
        cover = paths.character_asset_dir(cid) / "cover.png"
        if not cover.exists():
            (need_portrait if char.get("appearance_prompt_en") else need_prepare).append(char.get("name", cid))
    return need_prepare, need_portrait


def _check_scene_readiness(paths) -> list[str]:
    """检查场景图就绪状态 → 缺少参考图的场景名列表"""
    from infra.config import load_yaml_entities
    scene_dir = paths.scenes_dir
    if not scene_dir.exists():
        return []
    need_image = []
    for scene in load_yaml_entities(scene_dir, "scene"):
        sid = scene.get("id", "")
        if not sid:
            continue
        asset_dir = paths.scene_asset_dir(sid)
        has_images = asset_dir.exists() and list(asset_dir.glob("*.png")) + list(asset_dir.glob("*.jpg"))
        if not has_images:
            need_image.append(scene.get("name", sid))
    return need_image


def _ensure_portraits_and_scenes(config_path: str, task_self=None, episode: int = 1) -> None:
    """生产前自检：检查定妆照和场景图是否就绪

    硬依赖（阻断）：角色缺少 prompt 或定妆照 → 无法生成首帧
    软依赖（警告）：场景缺少参考图 → 可以继续但质量降低
    """
    _ensure_path()
    try:
        cfg, _ = _init_ctx(config_path)
    except Exception as e:
        logger.warning(f"资产自检跳过（初始化失败）: {e}")
        return

    paths = cfg.paths
    blocking, warnings = [], []

    # ── 定妆照（硬依赖） ──
    need_prepare, need_portrait = _check_portrait_readiness(paths)
    if need_prepare:
        blocking.append(
            f"角色「{'、'.join(need_prepare)}」还没有生成 AI 绘图所需的英文描述。\n"
            f"     👉 请在 Web 工作台「🎬 生产管线」页面点击「🔧 准备阶段」")
    if need_portrait:
        blocking.append(
            f"角色「{'、'.join(need_portrait)}」还没有定妆照（角色形象图）。\n"
            f"     👉 请先在 Web 工作台「👤 角色」页面点击「🎨 AI 生成定妆照」")

    # ── 场景图（软依赖） ──
    scenes_need_image = _check_scene_readiness(paths)
    if scenes_need_image:
        warnings.append(
            f"场景「{'、'.join(scenes_need_image)}」还没有参考图，生成的画面可能与预期有偏差。\n"
            f"     👉 建议在 Web 工作台「🏔️ 场景」页面点击「🎨 AI 生成场景图」")

    for w in warnings:
        logger.warning(f"⚠ {w}")
    if blocking:
        for b in blocking:
            logger.error(f"❌ {b}")
        msg = (
            f"有 {len(blocking)} 个角色还没准备好，无法开始生产。\n\n"
            f"请按以下步骤准备：\n"
            f"  1. 在 Web 工作台「🎬 生产管线」页面点击「🔧 准备阶段」（生成英文 prompt + 翻译）\n"
            f"  2. 在 Web 工作台「👤 角色」页面点击「🎨 AI 生成定妆照」\n"
            f"  3. （可选）在 Web 工作台「🏔️ 场景」页面点击「🎨 AI 生成场景图」\n\n"
            f"或使用 CLI：\n  drama prepare {episode}\n  drama portraits\n")
        if task_self:
            task_self.update_state(state="PROGRESS", meta={"step": "preflight", "progress": 4, "message": msg})
        raise RuntimeError(msg)
