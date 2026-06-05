"""定妆照生成 — 确保角色有参考图（含五视图）"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["ensure_portrait", "ViewGenParams"]


# 重入保护：正在生成中的角色，防止 build_first_frame → _get_character_refs → ensure_portrait 死循环
_generating: dict[str, float] = {}  # char_id → start_time（TTL 防残留）
_generating_lock = threading.Lock()
_GENERATING_TTL = 300  # 5 分钟超时（单张定妆照生成不应超过此时间，超时则视为卡死）


@dataclass
class ViewGenParams:
    """视图生成参数 — 消除 _generate_view 的 11 个参数"""
    comfyui: object
    wb: object
    char_id: str
    portrait_dir: Path
    filename: str
    shot_type: str
    seed: int | None = None
    ref_image: str | None = None
    char: dict | None = None
    project_dir: str = ""
    view_key: str = ""

# 五视图配置：文件名 → (shot_type, camera, 描述)
# 五视图配置：文件名 → (shot_type, camera, 描述, view_key)
_FIVE_VIEWS = [
    ("cover.png",        "特写",     "固定", "正面",  "front"),
    ("left_side.png",    "侧面特写", "固定", "左侧",  "left_side"),
    ("right_side.png",   "侧面特写", "固定", "右侧",  "right_side"),
    ("back.png",         "背面特写", "固定", "背面",  "back"),
    ("three_quarter.png","特写",     "固定", "3/4侧", "three_quarter"),
]


def _view_seed(char_id: str, generation: int, view_index: int) -> int:
    """五视图 seed：同角色同代不同视角，不同角色完全隔离

    注意：为保持五视图人物一致性，所有视角使用相同 seed。
    view_index 保留用于未来需要差异化时扩展。
    """
    h = hashlib.md5(f"{char_id}:gen{generation}:portrait".encode("utf-8")).hexdigest()
    return int(h[:16], 16)  # 64-bit seed, 碰撞概率 2^-64，实际可忽略


def _outfit_seed(char_id: str, generation: int, outfit_index: int) -> int:
    """服装图 seed：同角色同代不同服装，不同角色完全隔离"""
    h = hashlib.md5(f"{char_id}:gen{generation}:outfit{outfit_index}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _generate_view(params: ViewGenParams) -> str:
    """生成单张视图，返回文件路径或空字符串"""
    p = params
    # 获取视角专属 prompt（prepare 阶段已生成）
    from engines.prompt import get_view_appearance
    view_desc = get_view_appearance(p.char, p.shot_type, view_key=p.view_key) if p.char else ""
    from infra.constants import ERR_NOT_PREPARED
    if not view_desc:
        logger.error(f"角色 '{p.char_id}' 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}")
        return ""

    fake_shot = {"characters": p.char_id, "emotion": "neutral",
                 "shot_type": p.shot_type, "camera": "固定"}
    prompt, wf = p.wb.build_first_frame(fake_shot, character_desc=view_desc, seed=p.seed)
    if not wf:
        return ""

    # 注入参考图到 IP-Adapter（保持角色面部/体型一致性）
    if p.ref_image and os.path.exists(p.ref_image):
        from engines.workflow import find_character_load_image_nodes
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            from infra.asset_tracker import comfyui_asset_name, AssetTracker
            remote_name = comfyui_asset_name(p.project_dir, p.char_id, os.path.basename(p.ref_image))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                tracker = AssetTracker(p.project_dir)
                tracker.upload_if_needed(p.comfyui, p.ref_image, remote_name, p.comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    files = p.comfyui.generate(wf, str(p.portrait_dir))
    if not files:
        return ""
    # 重命名为目标文件名
    target = p.portrait_dir / p.filename
    os.replace(files[0], str(target))
    return str(target)



def _generate_five_views(comfyui, wb, char_id: str, portrait_dir: Path,
                         char: dict, project_dir: str, generation: int) -> list[str]:
    """生成五视图，返回已生成的 URL 列表"""
    cover_path = portrait_dir / "cover.png"
    generated_urls = []

    for i, (filename, shot_type, camera, label, vk) in enumerate(_FIVE_VIEWS):
        if (portrait_dir / filename).exists():
            generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
            continue

        view_seed = _view_seed(char_id, generation, i)
        ref = str(cover_path) if i > 0 and cover_path.exists() else None

        result = _generate_view(ViewGenParams(
            comfyui=comfyui, wb=wb, char_id=char_id, portrait_dir=portrait_dir,
            filename=filename, shot_type=shot_type, seed=view_seed, ref_image=ref,
            char=char, project_dir=project_dir, view_key=vk))
        if result:
            generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
            logger.info(f"  ✅ {label}视图: {filename} (seed={view_seed})")
        else:
            logger.warning(f"  ⚠ {label}视图生成失败")

    return generated_urls


def _update_view_refs(char: dict, char_id: str, generated_urls: list[str]) -> None:
    """回写五视图 reference_images（去重 + 移除旧的 cover/side/back）"""
    if not generated_urls:
        return
    char.setdefault("reference_images", [])
    prefix = f"/api/assets/characters/{char_id}/"
    view_filenames = {fn for fn, *_ in _FIVE_VIEWS}
    char["reference_images"] = [
        u for u in char["reference_images"]
        if not u.startswith(prefix) or u.rsplit("/", 1)[-1] not in view_filenames
    ]
    existing_set = set(char["reference_images"])
    for url in generated_urls:
        if url not in existing_set:
            char["reference_images"].append(url)


def ensure_portrait(char_id: str, config: dict, container=None, force: bool = False) -> str:
    """确保角色有定妆照（五视图），没有则生成

    生成三张图：
      - cover.png 正面特写
      - side.png  侧面特写
      - back.png  背面特写

    配置项 portraits.auto_outfit:
      - False（默认）: 只生成五视图，不遍历 outfits
      - True: 同时为各 outfit 生成参考图

    Args:
        force: True 时重新生成（递增代数计数器）
    """
    from infra.config import ProjectPaths, load_yaml_full
    project_dir = config.get("_project_dir", os.getcwd())
    paths = ProjectPaths(project_dir)
    portrait_dir = paths.character_asset_dir(char_id)

    # 检查五视图是否齐全
    all_views_exist = all((portrait_dir / fname).exists() for fname, *_ in _FIVE_VIEWS)
    if all_views_exist:
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit and container:
            _ensure_outfit_images(char_id, config, container, project_dir, portrait_dir)
        return str(portrait_dir / "cover.png")

    # 重入保护（检查 + 标记必须在同一把锁内，避免间隙导致重复生成）
    import time
    my_ts = time.time()
    with _generating_lock:
        if char_id in _generating:
            # TTL 检查：超时的残留条目自动清除
            if time.time() - _generating[char_id] < _GENERATING_TTL:
                logger.warning(f"角色 '{char_id}' 定妆照正在生成中，跳过重入")
                return ""
        _generating[char_id] = my_ts

    logger.info(f"角色 '{char_id}' 缺少五视图，自动生成...")
    char_file = paths.character_yaml(char_id)
    if not char_file.exists():
        logger.warning(f"角色配置不存在: {char_file}")
        with _generating_lock:
            _generating.pop(char_id, None)
        return ""

    data = load_yaml_full(char_file)
    char = data.get("character", {})

    if not container:
        with _generating_lock:
            _generating.pop(char_id, None)
        return ""

    try:
        comfyui = container.get("image")
        from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig
        models = config.get("models", {})
        wb = WorkflowBuilder(WorkflowBuilderConfig(config=config, models=models, project_dir=str(paths.root), comfyui=comfyui, force=force, no_auto_gen=True))
        wb.load_workflows()

        # 读取代数计数器（force 时递增，得到不同的生成结果）
        generation = char.get("portrait_generation", 0)
        if force:
            generation += 1
            char["portrait_generation"] = generation
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)
            logger.info(f"  🔄 重新生成，代数: {generation}")

        # 确定性 seed：同一角色+同一代 → 所有视图/服装共享基础 seed

        generated_urls = _generate_five_views(comfyui, wb, char_id, portrait_dir, char, project_dir, generation)
        _update_view_refs(char, char_id, generated_urls)
        if generated_urls:
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)

        # outfit 图
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit:
            _ensure_outfit_images(char_id, config, container, project_dir, portrait_dir)

        return str(portrait_dir / "cover.png") if (portrait_dir / "cover.png").exists() else ""

    except Exception as e:
        logger.error(f"定妆照生成失败: {e}", exc_info=True)
        return ""
    finally:
        with _generating_lock:
            # 只清除自己设置的条目，避免 TTL 竞态下误删其他线程的标记
            if _generating.get(char_id) == my_ts:
                _generating.pop(char_id, None)


def _generate_single_outfit(comfyui, wb, char_id: str, outfit_key: str,
                            outfit_desc_en: str, appearance_en: str,
                            portrait_dir: Path, cover_path: Path,
                            project_dir: str, outfit_seed: int) -> str | None:
    """为单个 outfit 生成参考图，返回 URL 或 None"""
    outfit_dir = portrait_dir / outfit_key
    if outfit_dir.exists():
        existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
        if existing:
            return None

    outfit_dir.mkdir(parents=True, exist_ok=True)
    full_desc = f"{appearance_en}, wearing {outfit_desc_en}"

    fake_shot = {"characters": char_id, "emotion": "neutral", "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=outfit_seed)
    if not wf:
        return None

    if cover_path.exists():
        from engines.workflow import find_character_load_image_nodes
        from infra.asset_tracker import comfyui_asset_name, AssetTracker
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            remote_name = comfyui_asset_name(project_dir, char_id, os.path.basename(str(cover_path)))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                AssetTracker(project_dir).upload_if_needed(comfyui, str(cover_path), remote_name, comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    try:
        files = comfyui.generate(wf, str(outfit_dir))
    except Exception as e:
        logger.warning(f"  ⚠ outfit '{outfit_key}' 生成失败: {e}")
        return None
    if not files:
        return None
    cover_out = outfit_dir / "cover.png"
    os.replace(files[0], str(cover_out))
    return f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"


def _ensure_outfit_images(char_id: str, config: dict, container,
                          project_dir: str, portrait_dir: Path) -> None:
    """为角色的各 outfit 生成参考图（如果尚未存在）"""
    from infra.config import ProjectPaths, load_yaml_full
    paths = ProjectPaths(project_dir)
    char_file = paths.character_yaml(char_id)
    if not char_file.exists():
        return

    try:
        data = load_yaml_full(char_file)
    except Exception as e:
        logger.warning(f"加载角色配置失败 {char_id}: {e}")
        return

    char = data.get("character", {})
    outfits = char.get("outfits", {})
    if not isinstance(outfits, dict) or not outfits:
        return

    comfyui = container.get("image")
    from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig
    models = config.get("models", {})
    wb = WorkflowBuilder(WorkflowBuilderConfig(config=config, models=models, project_dir=str(paths.root), comfyui=comfyui, no_auto_gen=True))
    wb.load_workflows()

    cover_path = portrait_dir / "cover.png"
    generation = char.get("portrait_generation", 0)
    appearance_en = char.get("appearance_prompt_en", "")
    if not appearance_en:
        from infra.constants import ERR_NOT_PREPARED
        logger.error(f"角色 '{char_id}' 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}")
        return

    for outfit_idx, (outfit_key, outfit_val) in enumerate(outfits.items()):
        if not isinstance(outfit_val, dict) or not outfit_val.get("description"):
            continue
        outfit_desc_en = outfit_val.get("description_en", "")
        if not outfit_desc_en:
            from infra.constants import ERR_NOT_PREPARED
            logger.error(f"角色 '{char_id}' 的服装 '{outfit_key}' 尚未生成英文描述，{ERR_NOT_PREPARED}")
            continue

        outfit_seed = _outfit_seed(char_id, generation, outfit_idx)
        url = _generate_single_outfit(comfyui, wb, char_id, outfit_key,
                                      outfit_desc_en, appearance_en, portrait_dir,
                                      cover_path, project_dir, outfit_seed)
        if url:
            outfit_val.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
            outfit_val["reference_images"].append(url)
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)
            logger.info(f"  👗 outfit '{outfit_key}' 生成完成 (seed={outfit_seed})")
