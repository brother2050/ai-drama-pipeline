"""Celery 任务 — LoRA 训练 / JSON 导入"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED
import logging
import os
from pathlib import Path

from pipeline.app import app
from pipeline.tasks.helpers import (
    _build_ctx, _paths,
    _db_record_step, _db_mark_running, _try_mark_running_atomic,
)
from infra.config import load_yaml_full

logger = logging.getLogger(__name__)


def _validate_lora_training(paths, char_id: str, force: bool) -> tuple[Path | None, str | None]:
    """校验 LoRA 训练前置条件 → (lora_path_or_None, error_or_None)"""
    from infra.storage.asset_tracker import comfyui_asset_name

    char_yaml = paths.character_yaml(char_id)
    if not char_yaml.exists():
        return None, f"角色 {char_id} 不存在"

    # 检查已有 LoRA
    lora_dir = paths.loras_dir
    lora_filename = comfyui_asset_name(str(paths.root), char_id, f"{char_id}_lora.safetensors")
    for candidate in [lora_dir / lora_filename, lora_dir / f"{char_id}_lora.safetensors", lora_dir / f"{char_id}.safetensors"]:
        if candidate.exists() and not force:
            return candidate, None

    # 检查训练图片
    char_assets_dir = paths.character_asset_dir(char_id)
    if not char_assets_dir.exists():
        return None, f"角色 {char_id} 无定妆照，请先生成定妆照"

    img_count = _count_training_images(char_assets_dir)
    if img_count < 3:
        return None, f"训练图片不足（{img_count} 张），至少需要 3 张"

    return None, None


def _count_training_images(char_assets_dir: Path) -> int:
    """统计训练图片数量（递归搜索所有子目录）"""
    count = 0
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        count += len(list(char_assets_dir.rglob(ext)))
    return count


def _resolve_trigger_word(char_yaml: Path, char_id: str) -> str:
    """解析 trigger_word，优先读 YAML 中的 lora_trigger，否则从角色名推导"""
    try:
        from infra.config import load_character
        char = load_character(char_yaml.parent, char_id)
        # 优先使用用户配置的 lora_trigger
        stored = char.get("lora_trigger", "")
        if stored:
            return stored
        char_name = char.get("name", char_id)
        return f"ohwx {char_name}"
    except Exception:
        return f"ohwx {char_id}"


def _rename_lora_result(result_path: str, paths, char_id: str) -> str:
    """重命名 LoRA 文件为 comfyui_asset_name 规范"""
    from infra.storage.asset_tracker import comfyui_asset_name
    original_name = Path(result_path).name
    new_name = comfyui_asset_name(str(paths.root), char_id, original_name)
    new_path = Path(result_path).parent / new_name
    if Path(result_path).exists() and not new_path.exists():
        os.replace(result_path, str(new_path))
        logger.info(f"LoRA 已重命名: {original_name} → {new_name}")
        return str(new_path)
    return result_path


def _save_lora_to_yaml(char_yaml: Path, result_path: str) -> None:
    """将 LoRA 路径写入角色 YAML"""
    try:
        data = load_yaml_full(char_yaml)
        data.setdefault("character", {})["lora_path"] = result_path
        from infra.config import save_yaml
        save_yaml(char_yaml, data)
    except Exception as e:
        logger.warning(f"更新角色 LoRA 路径失败: {e}")


@app.task(bind=True, name="pipeline_train_lora", soft_time_limit=7200)
def train_lora_task(self, config_path: str, char_id: str, *,
                    steps: int = 600,
                    learning_rate: float = 1e-4, rank: int = 16,
                    resolution: str = "512x768", force: bool = False,
                    train_config: dict | None = None) -> dict:
    """为角色训练 LoRA 模型（异步）

    Args:
        train_config: 可选的训练参数覆盖 dict（steps/learning_rate/rank/resolution），
                      优先级高于单独的同名参数。
    """
    # 合并 train_config（优先级高于单独参数）
    cfg_overrides = train_config or {}
    steps = cfg_overrides.get("steps", steps)
    learning_rate = cfg_overrides.get("learning_rate", learning_rate)
    rank = cfg_overrides.get("rank", rank)
    resolution = cfg_overrides.get("resolution", resolution)

    if not force and not _try_mark_running_atomic(0, char_id, "train_lora"):
        return {"status": STATUS_SKIPPED, "reason": f"角色 {char_id} 的 LoRA 训练已在执行中，请等待完成"}
    if force:
        _db_mark_running(0, char_id, "train_lora")

    self.update_state(state="PROGRESS", meta={"step": "train_lora", "progress": 5, "message": f"准备训练 {char_id} 的 LoRA..."})
    _, cont = _build_ctx(config_path)
    paths = _paths(config_path)

    existing_lora, err = _validate_lora_training(paths, char_id, force)
    if err:
        _db_record_step(0, char_id, "train_lora", {"status": STATUS_ERROR, "reason": err})
        return {"status": STATUS_ERROR, "reason": err}
    if existing_lora:
        _db_record_step(0, char_id, "train_lora", {"status": STATUS_SKIPPED, "reason": f"LoRA 已存在: {existing_lora.name}"})
        return {"status": STATUS_SKIPPED, "reason": f"LoRA 已存在: {existing_lora.name}，使用 force 覆盖"}

    char_assets_dir = paths.character_asset_dir(char_id)
    img_count = _count_training_images(char_assets_dir)
    self.update_state(state="PROGRESS", meta={"step": "train_lora", "progress": 15, "message": f"找到 {img_count} 张训练图片，开始训练..."})

    try:
        trainer = cont.get("training")
    except Exception as e:
        _db_record_step(0, char_id, "train_lora", {"status": STATUS_ERROR, "reason": f"训练后端不可用: {e}"})
        return {"status": STATUS_ERROR, "reason": f"训练后端不可用: {e}"}

    trigger_word = _resolve_trigger_word(paths.character_yaml(char_id), char_id)

    update = self.update_state
    def _on_progress(current: int, total: int, msg: str):
        update(state="PROGRESS", meta={"step": "train_lora", "progress": int(15 + current / max(total, 1) * 80),
                                       "message": msg, "current": current, "total": total})
    try:
        from api.backends.training.ai_toolkit import TrainLoraParams
        result_path = trainer.train_lora(TrainLoraParams(
            char_id=char_id, images_dir=str(char_assets_dir), trigger_word=trigger_word,
            steps=steps, learning_rate=learning_rate, rank=rank, resolution=resolution,
            output_name=f"{char_id}_lora", progress_cb=_on_progress))
    except Exception as e:
        logger.error(f"LoRA 训练失败: {e}", exc_info=True)
        _db_record_step(0, char_id, "train_lora", {"status": STATUS_ERROR, "reason": f"训练失败: {e}"})
        return {"status": STATUS_ERROR, "reason": f"训练失败: {e}"}

    self.update_state(state="PROGRESS", meta={"step": "train_lora", "progress": 95, "message": "训练完成，更新角色配置..."})
    result_path = _rename_lora_result(result_path, paths, char_id)
    _save_lora_to_yaml(paths.character_yaml(char_id), result_path)
    _db_record_step(0, char_id, "train_lora", {"status": STATUS_DONE, "path": result_path})
    return {"status": STATUS_DONE, "char_id": char_id, "lora_path": result_path,
            "trigger_word": trigger_word, "steps": steps, "images": img_count}


# ══════════════════════════════════════════════════════════
#  剧本 JSON 导入
# ══════════════════════════════════════════════════════════

def _import_json_append(builder, plan, project_dir, translation, root) -> dict:
    """追加模式导入"""
    result = builder.append(plan, root, project_dir=project_dir)
    logger.info(f"追加导入完成: {result}")
    return {
        "status": STATUS_DONE, "mode": "append",
        "project_name": plan.project_name or Path(result["project_dir"]).name,
        "project_dir": result["project_dir"],
        "added_characters": result["added_characters"],
        "added_scenes": result["added_scenes"],
        "added_shots": result["added_shots"],
        "characters": result["added_characters"],
        "scenes": result["added_scenes"],
        "shots": result["added_shots"],
        "translation": translation,
    }


def _import_json_full(builder, plan, project_dir, translation, root) -> dict:
    """全量模式导入（项目已存在时自动切换追加，并通知调用方）"""
    from scripts.project_builder import ProjectAlreadyExists
    try:
        project_dir = builder.build(plan, root)
    except ProjectAlreadyExists:
        if project_dir and project_dir.exists():
            logger.info(f"项目已存在，自动切换到追加模式: {project_dir}")
            result = _import_json_append(builder, plan, project_dir, translation, root)
            result["mode_switched"] = True
            result["warning"] = f"项目 '{plan.project_name}' 已存在，已自动切换为追加模式"
            return result
        raise
    logger.info(f"导入完成: {project_dir} ({len(plan.characters)} 角色, {len(plan.scenes)} 场景, {len(plan.shots)} 镜头)")
    return {
        "status": STATUS_DONE, "mode": "full",
        "project_dir": str(project_dir), "project_name": plan.project_name,
        "characters": len(plan.characters), "scenes": len(plan.scenes),
        "shots": len(plan.shots), "translation": translation,
    }


@app.task(bind=True, name="pipeline_import_json", soft_time_limit=300)
def import_json_task(self, plan_data: dict) -> dict:
    """从 JSON 导入项目（异步）"""
    try:
        self.update_state(state="PROGRESS", meta={"step": "validate", "progress": 10, "message": "校验数据..."})

        from infra.models import ImportPlan, ImportValidator, get_translation_status
        plan = ImportPlan(**plan_data)
        translation = get_translation_status(plan)

        from infra.config import projects_dir, get_root
        _ROOT = get_root()
        from scripts.project_builder import ProjectBuilder
        project_dir = None

        if plan.append:
            if plan.project_name:
                project_dir = projects_dir() / ProjectBuilder._safe_name(plan.project_name)
            else:
                from infra.config import get_active_project_dir
                project_dir = get_active_project_dir()
            if not project_dir.exists():
                return {"status": STATUS_ERROR, "reason": f"项目 '{plan.project_name}' 不存在，无法追加。请先执行全量导入。"}
        elif plan.project_name:
            candidate = projects_dir() / ProjectBuilder._safe_name(plan.project_name)
            if candidate.exists():
                project_dir = candidate

        # 校验 + 构建统一在 project_scope 内执行，确保 DB 读写绑定到正确项目
        from infra.database._db import project_scope
        scope_name = project_dir.name if project_dir else ""
        with project_scope(scope_name):
            # 查询已有镜头 ID（避免 models.py 直接依赖数据库层）
            existing_shots: set[tuple[int, str]] = set()
            try:
                from infra.database.pool import get_pool
                from infra.database.storyboard_db import get_all_shots
                existing_shots = {(r.get("episode", 0), r.get("shot_id", ""))
                                  for r in get_all_shots(get_pool()) if r.get("shot_id")}
            except Exception as e:
                logger.warning(f"读取已有镜头 ID 跳过（DB 不可用？）: {e}")

            errors = ImportValidator.validate_references(plan, project_dir, existing_shots=existing_shots)
            if errors:
                return {"status": STATUS_ERROR, "reason": "校验失败", "errors": errors}

            builder = ProjectBuilder()
            self.update_state(state="PROGRESS", meta={"step": "build", "progress": 50, "message": "构建项目..."})

            if plan.append:
                return _import_json_append(builder, plan, project_dir, translation, _ROOT)
            return _import_json_full(builder, plan, project_dir, translation, _ROOT)

    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            errors = [f"{' → '.join(str(loc_part) for loc_part in err.get('loc', []))}: {err.get('msg', '校验失败')}" for err in e.errors()]
            return {"status": STATUS_ERROR, "reason": "数据格式错误", "errors": errors}
        if isinstance(e, ValueError):
            return {"status": STATUS_ERROR, "reason": str(e)}
        logger.error(f"导入异常: {e}", exc_info=True)
        return {"status": STATUS_ERROR, "reason": f"导入失败: {type(e).__name__}: {str(e)[:200]}"}
