"""Celery 任务 — 定妆照 / 场景图 / 服装图"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import logging
import os

from pipeline.celery_app import app
from pipeline.tasks.helpers import _ensure_path, _init_ctx, _paths, _project_scope_from_config
from infra.config import load_yaml_full

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  批量定妆照 / 场景图
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str, force: bool = False) -> dict:
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "portraits", "progress": 10})
    with _project_scope_from_config(config_path):
        try:
            from pipeline.portraits import run_portraits
            run_portraits(config_path, force=force)
        except Exception as e:
            logger.error(f"定妆照生成失败: {e}", exc_info=True)
            return {"status": STATUS_ERROR, "reason": str(e)}
    return {"status": STATUS_DONE}


@app.task(bind=True, name="pipeline_scene_images", soft_time_limit=1800)
def scene_images_task(self, config_path: str, force: bool = False) -> dict:
    """为所有场景批量生成参考图"""
    _ensure_path()
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
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "portrait", "progress": 10, "message": f"生成 {char_id} 定妆照..."})

    with _project_scope_from_config(config_path):
        paths = _paths(config_path)
        if not paths.character_yaml(char_id).exists():
            return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

        try:
            from pipeline.portraits import run_portraits
            run_portraits(config_path, force=True, char_ids=[char_id], write_db=True)
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"定妆照生成失败: {e}"}

    return {"status": STATUS_DONE, "char_id": char_id}


@app.task(bind=True, name="pipeline_outfit_single", soft_time_limit=300)
def outfit_single_task(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """为单个角色的指定服装生成参考图"""
    _ensure_path()
    with _project_scope_from_config(config_path):
        return _outfit_single_inner(self, config_path, char_id, outfit_key)


def _update_outfit_reference(char_yaml, char_id: str, outfit_key: str, img_url: str) -> None:
    """更新服装 YAML 中的 reference_images"""
    try:
        data = load_yaml_full(char_yaml)
        char = data.get("character", {})
        outfits_data = char.get("outfits", {})
        if isinstance(outfits_data, dict) and outfit_key in outfits_data:
            outfit_val = outfits_data[outfit_key]
            outfit_val.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
            outfit_val["reference_images"].append(img_url)
        char["outfits"] = outfits_data
        data["character"] = char
        from infra.config import save_yaml
        save_yaml(char_yaml, data)
    except Exception as e:
        logger.debug(f"更新 outfit reference_images 跳过: {e}")


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
        from infra.constants import ERR_NOT_PREPARED_CN
        return "", f"角色 {char_id} 的服装 '{outfit_key}' 尚未生成英文描述，{ERR_NOT_PREPARED_CN}"
    return desc_en, None


def _build_and_generate_outfit(comfyui, wb, char_id: str, outfit_key: str,
                               full_desc: str, outfit_seed: int, outfit_dir: Path,
                               old_imgs: list, paths) -> tuple[str | None, str | None]:
    """构建工作流 + 上传参考图 + 生成 → (img_url, error)"""
    fake_shot = {"characters": char_id, "emotion": "neutral", "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=outfit_seed)
    if not wf:
        return None, "首帧工作流为空（缺少模板）"

    cover_ref = paths.character_asset_dir(char_id) / "cover.png"
    if cover_ref.exists():
        from engines.workflow import find_character_load_image_nodes
        from infra.asset_tracker import comfyui_asset_name, AssetTracker
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            remote_name = comfyui_asset_name(str(paths.root), char_id, os.path.basename(str(cover_ref)))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                AssetTracker(str(paths.root)).upload_if_needed(comfyui, str(cover_ref), remote_name, comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    try:
        files = comfyui.generate(wf, str(outfit_dir))
    except Exception as e:
        return None, f"ComfyUI 生成失败: {e}"
    if not files:
        return None, "ComfyUI 未返回任何图片"

    for old_img in old_imgs:
        try: old_img.unlink()
        except OSError: pass

    cover_path = outfit_dir / "cover.png"
    os.replace(files[0], str(cover_path))
    return f"/api/assets/characters/{char_id}/{outfit_key}/cover.png", None


def _outfit_single_inner(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """outfit_single 核心逻辑（在 project_scope 内执行）"""
    from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 10, "message": f"生成 {char_id}/{outfit_key} 服装图..."})
    cfg, cont = _init_ctx(config_path)
    paths = _paths(config_path)

    char_yaml = paths.character_yaml(char_id)
    if not char_yaml.exists():
        return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

    with open(char_yaml, encoding="utf-8") as f:
        data = load_yaml_full(f)
    char = data.get("character", {})

    outfit_desc_en, err = _validate_outfit(char, char_id, outfit_key)
    if err:
        return {"status": STATUS_ERROR, "reason": err}

    try:
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"ComfyUI 不可用: {e}"}

    outfit_dir = paths.character_outfit_dir(char_id, outfit_key)
    outfit_dir.mkdir(parents=True, exist_ok=True)
    old_imgs = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))

    full_desc = f"{char.get('appearance_prompt_en', '')}, wearing {outfit_desc_en}"
    wb = WorkflowBuilder(WorkflowBuilderConfig(config=cfg.data, models=cfg.get("models", {}),
                                                project_dir=str(paths.root), comfyui=comfyui))
    wb.load_workflows()

    from engines.portrait import _outfit_seed
    outfits = char.get("outfits", {})
    outfit_seed = _outfit_seed(char_id, char.get("portrait_generation", 0), list(outfits.keys()).index(outfit_key))

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 50, "message": "ComfyUI 生成中..."})
    img_url, gen_err = _build_and_generate_outfit(comfyui, wb, char_id, outfit_key, full_desc,
                                                  outfit_seed, outfit_dir, old_imgs, paths)
    if gen_err:
        return {"status": STATUS_ERROR, "reason": gen_err}

    _update_outfit_reference(char_yaml, char_id, outfit_key, img_url)
    return {"status": STATUS_DONE, "url": img_url, "char_id": char_id, "outfit": outfit_key}


@app.task(bind=True, name="pipeline_outfits_batch", soft_time_limit=600)
def outfits_batch_task(self, config_path: str, char_id: str) -> dict:
    """为单个角色的所有服装批量生成参考图"""
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "outfits", "progress": 5, "message": f"加载角色 {char_id}..."})

    paths = _paths(config_path)
    char_yaml = paths.character_yaml(char_id)
    if not char_yaml.exists():
        return {"status": STATUS_ERROR, "reason": f"角色 {char_id} 不存在"}

    with open(char_yaml, encoding="utf-8") as f:
        data = load_yaml_full(f)
    char = data.get("character", {})
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
            result = outfit_single_task.apply(args=[config_path, char_id, key]).get(timeout=300)
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
    _ensure_path()
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
            return {"status": STATUS_DONE, "scene_id": scene_id, **result}
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"场景图生成失败: {e}"}
