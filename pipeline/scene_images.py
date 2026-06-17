"""场景参考图生成 — 为所有场景生成参考图（共享逻辑）

被以下入口调用：
- scene_images_task（批量，Celery）
- scene_image_single_task（单场景，Celery）
- ai_prepare_task step 5（准备阶段，Celery）
"""
from __future__ import annotations
from infra.config import load_yaml_full

from infra.constants import STATUS_DONE, STATUS_ERROR
import logging
import os
import re
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

def _noop_progress(*a, **kw): return None

# 进度回调类型: (current, total, message)
ProgressCB = Callable[[int, int, str], None] | None



def _process_single_scene(f: Path, wb, comfyui, paths, cfg, force: bool) -> tuple[bool, str]:
    """处理单个场景，返回 (success, scene_name)"""
    try:
        data = load_yaml_full(f)
    except Exception as e:
        logger.warning(f"场景 YAML 格式错误 {f}: {e}")
        return False, ""

    scene = data.get("scene", {})
    sid = scene.get("id", "")
    if not sid:
        return False, ""
    sname = scene.get("name", sid)

    # 已有图 → 跳过或强制删除
    scene_asset_dir = paths.scene_asset_dir(sid)
    existing = _existing_images(scene_asset_dir)
    if existing:
        if force:
            for img in existing:
                img.unlink()
            logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，已删除（强制模式）")
        else:
            logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，跳过")
            return False, sname

    scene_asset_dir.mkdir(parents=True, exist_ok=True)

    # 翻译检查
    desc_en = _resolve_scene_desc(scene, sname)
    if not desc_en:
        return False, sname

    # 生成
    fake_shot = {"characters": "", "emotion": "neutral", "shot_type": "全景", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, scene_desc=desc_en)
    if not wf:
        logger.warning(f"  ⚠ 场景 {sname}: 工作流为空")
        return False, sname

    try:
        files = comfyui.generate(wf, str(scene_asset_dir))
    except Exception as e:
        logger.error(f"  ❌ 场景 {sname}: {e}", exc_info=True)
        return False, sname
    if not files:
        logger.warning(f"  ⚠ 场景 {sname}: ComfyUI 未返回图片")
        return False, sname

    _save_scene_cover(scene_asset_dir, files[0], sid, scene, data, f)
    logger.info(f"  ✅ 场景 {sname}: 生成完成")
    return True, sname


def _existing_images(asset_dir: Path) -> list:
    if not asset_dir.exists():
        return []
    from infra.constants import IMAGE_GLOB_PATTERNS
    return [f for ext in IMAGE_GLOB_PATTERNS for f in asset_dir.glob(ext)]


def _resolve_scene_desc(scene: dict, sname: str) -> str:
    """解析场景英文描述，缺失时给出提示"""
    desc_en = scene.get("description_en", "")
    if not desc_en:
        description = scene.get("description", "")
        if description and not description.isascii():
            from infra.constants import ERR_NOT_PREPARED
            logger.warning(f"  ⚠ 场景 {sname}: 尚未生成英文描述，{ERR_NOT_PREPARED}")
            return ""
        desc_en = description
    if not desc_en:
        logger.warning(f"  ⚠ 场景 {sname}: 描述为空，跳过")
        return ""
    # 校验：英文描述不应包含中文（说明翻译未完成或被污染）
    if re.search(r'[\u4e00-\u9fff]', desc_en):
        logger.warning(f"  ⚠ 场景 {sname}: description_en 仍含中文，跳过（请重新执行准备阶段）")
        return ""
    # 校验：描述过短（<5 词）可能不是有效场景描述
    if len(desc_en.split()) < 5:
        logger.warning(f"  ⚠ 场景 {sname}: description_en 过短（'{desc_en[:50]}'），跳过")
        return ""
    return desc_en


def _save_scene_cover(asset_dir: Path, source_file: str, sid: str,
                      scene: dict, data: dict, yaml_path: Path) -> None:
    """保存场景封面图 + 更新 YAML + 同步 DB"""
    from infra.config import save_yaml
    cover_path = asset_dir / "cover.png"
    os.replace(source_file, str(cover_path))
    img_url = f"/api/assets/scenes/{sid}/cover.png"
    scene.setdefault("reference_images", [])
    prefix = f"/api/assets/scenes/{sid}/cover"
    scene["reference_images"] = [u for u in scene["reference_images"] if not u.startswith(prefix)]
    scene["reference_images"].append(img_url)
    data["scene"] = scene
    save_yaml(yaml_path, data)


def run_scene_images(
    config_path: str,
    *,
    force: bool = False,
    scene_ids: list[str] | None = None,
    progress_cb: ProgressCB = None,
) -> dict:
    """生成场景参考图"""
    from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
    from infra.config import Config
    from api.registry import Container
    cfg = Config(config_path)
    paths = cfg.paths
    cb = progress_cb or _noop_progress

    try:
        cont = Container(cfg.data)
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"ComfyUI 不可用: {e}"}

    scenes_dir = paths.scenes_dir
    if not scenes_dir.exists():
        return {"status": STATUS_ERROR, "reason": "场景配置目录不存在"}

    if scene_ids is not None:
        scene_files = [scenes_dir / f"{sid}.yaml" for sid in scene_ids if (scenes_dir / f"{sid}.yaml").exists()]
    else:
        from infra.config import load_yaml_entities as _load_wp
        scene_files = [f for f, _ in _load_wp(scenes_dir, "scene", with_paths=True)]

    if not scene_files:
        return {"status": STATUS_DONE, "generated": 0, "total": 0, "skipped": 0}

    wb = WorkflowBuilder(WorkflowBuilderConfig(config=cfg.data, models=cfg.get("models", {}), project_dir=str(paths.root), comfyui=comfyui))
    wb.load_workflows()

    generated = skipped = 0
    for i, f in enumerate(scene_files):
        cb(i + 1, len(scene_files), f.stem)
        ok, _ = _process_single_scene(f, wb, comfyui, paths, cfg, force)
        if ok:
            generated += 1
        else:
            skipped += 1

    return {"status": STATUS_DONE, "generated": generated, "total": len(scene_files), "skipped": skipped}
