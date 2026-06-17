"""生产前置检查 — 确保定妆照和场景图就绪"""
from __future__ import annotations

import logging

from infra.constants import IMAGE_GLOB_PATTERNS

logger = logging.getLogger(__name__)

__all__ = ["ensure_portraits_and_scenes"]


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
        has_images = asset_dir.exists() and any(asset_dir.glob(ext) for ext in IMAGE_GLOB_PATTERNS)
        if not has_images:
            need_image.append(scene.get("name", sid))
    return need_image


def ensure_portraits_and_scenes(config_path: str, task_self=None) -> None:
    """生产前自检：检查定妆照和场景图是否就绪

    硬依赖（阻断）：角色缺少 prompt 或定妆照 → 无法生成首帧
    软依赖（警告）：场景缺少参考图 → 可以继续但质量降低

    Raises:
        RuntimeError: 有硬依赖未满足时
    """
    from pipeline.tasks.helpers import _build_ctx
    try:
        cfg, _ = _build_ctx(config_path)
    except Exception as e:
        raise RuntimeError(f"生产前置检查失败（配置加载异常）: {e}") from e

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
            f"  3. （可选）在 Web 工作台「🏔️ 场景」页面点击「🎨 AI 生成场景图」\n")
        if task_self:
            task_self.update_state(state="PROGRESS", meta={"step": "preflight", "progress": 4, "message": msg})
        raise RuntimeError(msg)
