"""Celery 任务 — 定妆照 / 场景图 / 服装图"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import logging

from pipeline.app import app
from pipeline.tasks.helpers import _build_ctx, _paths, _project_scope_from_config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  批量定妆照 / 场景图
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str, force: bool = False) -> dict:
    self.update_state(state="PROGRESS", meta={"step": "portraits", "progress": 10})
    with _project_scope_from_config(config_path):
        try:
            from pipeline.portraits import run_portraits
            result = run_portraits(config_path, force=force)
        except Exception as e:
            logger.error(f"定妆照生成失败: {e}", exc_info=True)
            return {"status": STATUS_ERROR, "reason": str(e)}
    return result if isinstance(result, dict) else {"status": STATUS_DONE}


@app.task(bind=True, name="pipeline_scene_images", soft_time_limit=1800)
def scene_images_task(self, config_path: str, force: bool = False) -> dict:
    """为所有场景批量生成参考图"""
    update = self.update_state

    update(state="PROGRESS", meta={"step": "scene_images", "progress": 10, "message": "加载场景..."})
    with _project_scope_from_config(config_path):
        try:
            from pipeline.scene_images import run_scene_images

            def on_progress(current, total, msg):
                update(state="PROGRESS", meta={
                    "step": "scene_images",
                    "progress": int(10 + current / max(total, 1) * 80),
                    "message": f"[{current}/{total}] {msg}",
                    "current": current, "total": total})

            return run_scene_images(config_path, force=force, progress_cb=on_progress)
        except Exception as e:
            logger.error(f"场景图批量生成失败: {e}", exc_info=True)
            return {"status": STATUS_ERROR, "reason": str(e)}


# ══════════════════════════════════════════════════════════
#  单资产生成任务
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_portrait_single", soft_time_limit=600)
def portrait_single_task(self, config_path: str, char_id: str) -> dict:
    """为单个角色 AI 生成定妆照 + 各服装参考图"""
    self.update_state(state="PROGRESS", meta={"step": "portrait", "progress": 10, "message": f"生成 {char_id} 定妆照..."})

    with _project_scope_from_config(config_path):
        paths = _paths(config_path)
        if not paths.character_yaml(char_id).exists():
            return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

        try:
            from pipeline.portraits import run_portraits
            run_portraits(config_path, force=True, char_ids=[char_id])
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"定妆照生成失败: {e}"}

        # 检查生成结果，返回 cover URL
        paths = _paths(config_path)
        cover = paths.character_asset_dir(char_id) / "cover.png"
        url = f"/api/assets/characters/{char_id}/cover.png" if cover.exists() else ""
        if not url:
            return {"status": STATUS_ERROR, "reason": "定妆照生成未产出图片"}
        return {"status": STATUS_DONE, "char_id": char_id, "url": url}


@app.task(bind=True, name="pipeline_outfit_single", soft_time_limit=300)
def outfit_single_task(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """为单个角色的指定服装生成参考图"""
    with _project_scope_from_config(config_path):
        return _outfit_single_inner(self, config_path, char_id, outfit_key)


def _validate_outfit(char: dict, char_id: str, outfit_key: str) -> tuple[str, str | None]:
    """校验服装有效性 → (outfit_desc_en, error_or_None)"""
    appearance_en = char.get("appearance_prompt_en", "")
    if not appearance_en:
        from infra.constants import ERR_NOT_PREPARED
        return "", f"角色 {char_id} 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}"

    outfits = char.get("outfits", {})
    if not isinstance(outfits, dict) or outfit_key not in outfits:
        available = list(outfits.keys()) if isinstance(outfits, dict) else []
        return "", f"角色 {char_id} 没有名为 '{outfit_key}' 的服装，可用: {available}"

    desc_en = outfits[outfit_key].get("description_en", "")
    desc_zh = outfits[outfit_key].get("description", "")
    if not desc_en and not desc_zh:
        return "", f"角色 {char_id} 的服装 '{outfit_key}' 描述为空"
    if not desc_en and desc_zh:
        from infra.constants import ERR_NOT_PREPARED
        return "", f"角色 {char_id} 的服装 '{outfit_key}' 尚未生成英文描述，{ERR_NOT_PREPARED}"
    return desc_en, None


def _outfit_single_inner(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """outfit_single 核心逻辑（委托给 engines/portrait.py）"""
    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 10, "message": f"生成 {char_id}/{outfit_key} 服装图..."})
    cfg, cont = _build_ctx(config_path)
    paths = _paths(config_path)

    char_yaml = paths.character_yaml(char_id)
    if not char_yaml.exists():
        return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

    from infra.config import load_character
    char = load_character(paths, char_id)
    outfit_desc_en, err = _validate_outfit(char, char_id, outfit_key)
    if err:
        return {"status": STATUS_ERROR, "reason": err}

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 50, "message": "ComfyUI 生成中..."})
    try:
        from engines.content.portrait import _generate_single_outfit, _outfit_seed
        comfyui = cont.get("image")
        from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
        wb = WorkflowBuilder(WorkflowBuilderConfig(config=cfg.data, models=cfg.get("models", {}),
                                                    project_dir=str(paths.root), comfyui=comfyui))
        wb.load_workflows()

        generation = char.get("portrait_generation", 0)
        seed = _outfit_seed(char_id, generation, outfit_key)
        cover_path = paths.character_asset_dir(char_id) / "cover.png"

        url = _generate_single_outfit(
            comfyui, wb, char_id, outfit_key, outfit_desc_en,
            char.get("appearance_prompt_en", ""),
            paths.character_asset_dir(char_id), cover_path,
            str(paths.root), seed, gender=char.get("gender", ""))

        if url:
            return {"status": STATUS_DONE, "url": url, "char_id": char_id, "outfit": outfit_key}
        return {"status": STATUS_ERROR, "reason": "ComfyUI 未返回任何图片"}
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"ComfyUI 生成失败: {e}"}


@app.task(bind=True, name="pipeline_outfits_batch", soft_time_limit=600)
def outfits_batch_task(self, config_path: str, char_id: str) -> dict:
    """为单个角色的所有服装批量生成参考图"""
    with _project_scope_from_config(config_path):
        return _outfits_batch_inner(self, config_path, char_id)


def _outfits_batch_inner(self, config_path: str, char_id: str) -> dict:
    self.update_state(state="PROGRESS", meta={"step": "outfits", "progress": 5, "message": f"加载角色 {char_id}..."})

    paths = _paths(config_path)
    char_yaml = paths.character_yaml(char_id)
    if not char_yaml.exists():
        return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

    from infra.config import load_character
    char = load_character(paths, char_id)
    outfits = char.get("outfits", {})

    if not isinstance(outfits, dict) or not outfits:
        return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 没有定义任何服装"}

    total = len(outfits)
    results = []
    errors = []
    for i, key in enumerate(outfits):
        self.update_state(state="PROGRESS", meta={
            "step": "outfits", "progress": int(10 + i / total * 80),
            "message": f"[{i+1}/{total}] 生成 {key}...", "current": i + 1, "total": total})
        try:
            # 直接调用内部函数，避免 Celery .apply() 同步调用导致单 Worker 死锁
            result = _outfit_single_inner(self, config_path, char_id, key)
            if result.get("status") == STATUS_DONE:
                results.append(result)
            else:
                errors.append({"outfit": key, "error": result.get("reason", "未知错误")})
        except Exception as e:
            errors.append({"outfit": key, "error": str(e)})

    return {"status": STATUS_DONE, "char_id": char_id,
            "generated": results, "errors": errors,
            "total": total, "success": len(results), "failed": len(errors)}


@app.task(bind=True, name="pipeline_scene_image_single", soft_time_limit=300)
def scene_image_single_task(self, config_path: str, scene_id: str) -> dict:
    """为单个场景 AI 生成参考图"""
    update = self.update_state

    update(state="PROGRESS", meta={"step": "scene_image", "progress": 10, "message": f"生成场景 {scene_id} 参考图..."})

    with _project_scope_from_config(config_path):
        def on_progress(current, total, msg):
            update(state="PROGRESS", meta={
                "step": "scene_image", "progress": int(10 + current / max(total, 1) * 80),
                "message": f"生成场景 {msg}..."})

        try:
            from pipeline.scene_images import run_scene_images
            result = run_scene_images(config_path, force=True, scene_ids=[scene_id], progress_cb=on_progress)
            if result.get("status") == STATUS_ERROR:
                return result
            # 检查生成结果，返回 cover URL
            paths = _paths(config_path)
            cover = paths.scene_asset_dir(scene_id) / "cover.png"
            url = f"/api/assets/scenes/{scene_id}/cover.png" if cover.exists() else ""
            return {"status": STATUS_DONE, "scene_id": scene_id, "url": url, **result}
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"场景图生成失败: {e}"}
