"""定妆照生成 — 确保角色有参考图（含五视图）"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["ensure_portrait", "ViewGenParams"]

def _safe_rename(src: str, dst: str) -> None:
    """安全重命名（跨文件系统自动回退到 copy2）"""
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copy2(src, dst)
        try:
            os.unlink(src)
        except OSError:
            pass


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

# 五视图配置：文件名 → (shot_type, camera, 描述, view_key)
_FIVE_VIEWS = [
    ("cover.png",        "特写",     "固定", "正面",  "front"),
    ("full_body.png",    "全身",     "固定", "全身",  "full_body"),
    ("left_side.png",    "侧面特写", "固定", "左侧",  "left_side"),
    ("right_side.png",   "侧面特写", "固定", "右侧",  "right_side"),
    ("back.png",         "背面特写", "固定", "背面",  "back"),
    ("three_quarter.png","特写",     "固定", "3/4侧", "three_quarter"),
]


def _view_seed(char_id: str, generation: int, view_index: int) -> int:
    """五视图 seed：同角色同代不同视角使用不同 seed（避免视角雷同）

    view_index 用于区分不同视角，确保每个视角有独立的生成结果。
    """
    h = hashlib.md5(f"{char_id}:gen{generation}:view{view_index}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)  # 64-bit seed, 碰撞概率 2^-64


def _outfit_seed(char_id: str, generation: int, outfit_key: str) -> int:
    """服装图 seed：同角色同代不同服装，不同角色完全隔离

    使用 outfit_key（而非 index）使 seed 与 YAML 中的声明顺序无关，
    避免用户调整 outfit 顺序后已生成图片与新 seed 不匹配。
    """
    h = hashlib.md5(f"{char_id}:gen{generation}:outfit:{outfit_key}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _inject_ref_image(wf: dict, ref_image: str, char_id: str, project_dir: str, comfyui, *, raise_on_error: bool = False) -> None:
    """注入参考图到工作流的 IP-Adapter/PuLID LoadImage 节点

    当 ref_image 为空时（如正面视图生成 cover.png 之前），移除工作流中已注入的
    一致性节点（PuLID / IP-Adapter），避免 ComfyUI 因引用不存在的图片而报错。
    """
    from engines.workflow.utils import find_character_load_image_nodes, find_load_image_nodes

    if not ref_image or not os.path.exists(ref_image):
        # 无参考图时，移除已注入的一致性节点（PuLID / IP-Adapter），避免 ComfyUI 校验失败
        _remove_consistency_nodes(wf)
        return
    char_nodes = find_character_load_image_nodes(wf)
    if not char_nodes:
        # 回退：定妆照生成时无 IP-Adapter/PuLID 节点，使用第一个普通 LoadImage
        char_nodes = find_load_image_nodes(wf)
    if not char_nodes:
        return
    from infra.storage.asset_tracker import comfyui_asset_name, AssetTracker
    remote_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref_image))
    for nid in char_nodes:
        wf[nid]["inputs"]["image"] = remote_name
    try:
        AssetTracker(project_dir).upload_if_needed(comfyui, ref_image, remote_name, comfyui.url)
    except Exception as e:
        if raise_on_error:
            raise RuntimeError(f"参考图上传到 ComfyUI 失败: {e}") from e
        logger.warning(f"参考图上传失败: {e}")


def _remove_consistency_nodes(wf: dict) -> None:
    """从工作流中移除 PuLID / IP-Adapter 一致性节点子图

    正面视图生成 cover.png 之前无参考图可用，需要清理已注入的一致性节点，
    否则 ComfyUI 会因引用不存在的图片文件而报 'Invalid image file' 错误。

    保留 LoRA 节点（角色 LoRA / 全局 LoRA / 风格 LoRA）——它们不依赖一致性节点。
    移除一致性节点后，KSampler.model 重连到 LoRA（如有），保持 LoRA 在链路中。
    """
    from engines.workflow.utils import find_character_load_image_nodes
    char_nodes = find_character_load_image_nodes(wf)
    if not char_nodes:
        return

    # 1. 收集需要移除的节点
    to_remove = set()
    for nid in list(wf.keys()):
        cls = wf[nid].get("class_type", "")
        # PuLID 节点
        if cls in ("PulidFluxModelLoader", "PulidFluxInsightFaceLoader",
                    "PulidFluxEvaClipLoader", "ApplyPulidFlux"):
            to_remove.add(nid)
        # IP-Adapter 节点
        elif cls in ("IPAdapterModelLoader", "CLIPVisionLoader", "IPAdapterAdvanced"):
            to_remove.add(nid)
        # 一致性 LoadImage 节点（pulid_ref_* / ipadapter_ref_*）
        elif nid in char_nodes:
            to_remove.add(nid)

    if not to_remove:
        return

    # 2. 先回退 KSampler model 输入（避免递归收集时把 KSampler/VAEDecode 误删）
    #    沿 model 链回退到第一个不在 to_remove 中的祖先节点。
    #    典型链路: UNETLoader → LoRA → ApplyPulidFlux → KSampler
    #    PuLID 的 model 链: PulidFluxModelLoader → UNETLoader（不经过 LoRA），
    #    因此 while 循环会跳过 LoRA 直连 UNETLoader。需要额外修正：
    #    如果重连目标被 LoRA 消费，则连接到 LoRA 而非直连源。
    for nid, node in wf.items():
        if node.get("class_type") == "KSampler":
            model_input = node["inputs"].get("model")
            if isinstance(model_input, list) and len(model_input) == 2:
                source_nid = model_input[0]
                if source_nid in to_remove:
                    cur = source_nid
                    while cur in to_remove:
                        cur_node = wf.get(cur, {})
                        parent = cur_node.get("inputs", {}).get("model")
                        if isinstance(parent, list) and len(parent) == 2:
                            cur = parent[0]
                        else:
                            break
                    # 修正: 如果 cur（如 UNETLoader）被 LoRA 消费，连接到 LoRA
                    for _nid, _node in wf.items():
                        if _nid in to_remove:
                            continue
                        if _node.get("class_type") == "LoraLoader":
                            _model_in = _node.get("inputs", {}).get("model")
                            if isinstance(_model_in, list) and _model_in[0] == cur:
                                cur = _nid
                                break
                    node["inputs"]["model"] = [cur, 0]
                    logger.debug(f"KSampler model 输入回退到 {cur}")

    # 3. 递归收集：输出引用被移除节点的其他节点（如 LoRA → pulid_model 链路断裂）
    #    KSampler/VAEDecode 等核心节点已在步骤 2 重连，不会被误删
    changed = True
    while changed:
        changed = False
        for nid, node in list(wf.items()):
            if nid in to_remove:
                continue
            for inp_val in node.get("inputs", {}).values():
                if isinstance(inp_val, list) and len(inp_val) == 2 and inp_val[0] in to_remove:
                    to_remove.add(nid)
                    changed = True
                    break

    for nid in to_remove:
        del wf[nid]
    logger.debug(f"已移除 {len(to_remove)} 个一致性节点（无参考图可用）")


def _generate_view(params: ViewGenParams) -> str:
    """生成单张视图，返回文件路径或空字符串"""
    p = params
    # 获取视角专属 prompt（prepare 阶段已生成）
    from engines.prompt.view import get_view_appearance
    view_desc = get_view_appearance(p.char, p.shot_type, view_key=p.view_key) if p.char else ""
    from infra.constants import ERR_NOT_PREPARED
    if not view_desc:
        logger.error(f"角色 '{p.char_id}' 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}")
        return ""

    fake_shot = {"characters": p.char_id, "emotion": "neutral",
                 "shot_type": p.shot_type, "camera": "固定", "scene_name": "",
                 "view_key": p.view_key}
    # 正面视图（view_key="front"）无参考图，跳过一致性注入（PuLID/IP-Adapter），
    # 避免注入后 _remove_consistency_nodes 清理不彻底的问题。
    # LoRA 仍由 build_first_frame 内部按 skip_consistency 分支注入。
    skip_consistency = (p.view_key == "front")
    _, wf = p.wb.build_first_frame(fake_shot, character_desc=view_desc, seed=p.seed,
                                    skip_consistency=skip_consistency)
    if not wf:
        return ""

    _inject_ref_image(wf, p.ref_image, p.char_id, p.project_dir, p.comfyui, raise_on_error=True)
    if p.ref_image:
        logger.info(f"  📎 参考图注入: {os.path.basename(p.ref_image)} → view={p.view_key}")

    # 注入视角专属负面提示（防止背面视图生成正面人脸等）
    from engines.prompt.view import get_view_negative
    view_neg = get_view_negative(p.view_key)
    if view_neg:
        from engines.workflow.utils import append_negative_prompt
        append_negative_prompt(wf, view_neg)

    files = p.comfyui.generate(wf, str(p.portrait_dir))
    if not files:
        return ""
    target = p.portrait_dir / p.filename
    try:
        _safe_rename(files[0], str(target))
    except FileNotFoundError:
        logger.error(f"生成文件丢失: {files[0]}")
        return ""
    return str(target)




def _generate_five_views(comfyui, wb, char_id: str, portrait_dir: Path,
                         char: dict, project_dir: str, generation: int,
                         force: bool = False) -> list[str]:
    """生成五视图，返回已生成的 URL 列表"""
    cover_path = portrait_dir / "cover.png"
    generated_urls = []

    for i, (filename, shot_type, _, label, vk) in enumerate(_FIVE_VIEWS):
        if not force and (portrait_dir / filename).exists():
            generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
            continue

        view_seed = _view_seed(char_id, generation, i)
        # 参考图策略：正面视图(i==0)无参考；其余视图都用正面参考（由 _VIEW_NEGATIVE 控制视角方向）
        ref = None
        if i > 0 and cover_path.exists():
            ref = str(cover_path)
        elif i > 0 and not cover_path.exists():
            logger.warning(f"  ⚠ {label}视图: cover.png 不存在，无参考图，一致性可能受影响")

        try:
            result = _generate_view(ViewGenParams(
                comfyui=comfyui, wb=wb, char_id=char_id, portrait_dir=portrait_dir,
                filename=filename, shot_type=shot_type, seed=view_seed, ref_image=ref,
                char=char, project_dir=project_dir, view_key=vk))
        except Exception as e:
            logger.error(f"  ❌ {label}视图生成异常: {e}")
            result = None

        if result:
            cover_path = portrait_dir / filename if i == 0 else cover_path
            generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
            ref_info = f" (ref={os.path.basename(ref)})" if ref else " (无参考图)"
            logger.info(f"  ✅ {label}视图: {filename} (seed={view_seed}){ref_info}")
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
        if not u.startswith(prefix) or u[len(prefix):] not in view_filenames
    ]
    existing_set = set(char["reference_images"])
    for url in generated_urls:
        if url not in existing_set:
            char["reference_images"].append(url)


def ensure_portrait(char_id: str, config: dict, container=None, force: bool = False) -> str:
    """确保角色有定妆照（五视图），没有则生成

    生成五张图：
      - cover.png        正面特写
      - left_side.png    左侧特写
      - right_side.png   右侧特写
      - back.png         背面特写
      - three_quarter.png 3/4 侧特写

    配置项 portraits.auto_outfit:
      - False（默认）: 只生成五视图，不遍历 outfits
      - True: 同时为各 outfit 生成参考图

    Args:
        force: True 时重新生成（递增代数计数器）
    """
    from infra.config import ProjectPaths
    project_dir = config.get("_project_dir", os.getcwd())
    paths = ProjectPaths(project_dir)
    portrait_dir = paths.character_asset_dir(char_id)

    # 检查五视图是否齐全（force 时跳过，强制重新生成）
    if not force:
        all_views_exist = all((portrait_dir / fname).exists() for fname, *_ in _FIVE_VIEWS)
        if all_views_exist:
            # 检查 YAML 是否缺少五视图引用（图片存在但 YAML 未引用）
            from infra.config import load_character, load_yaml_full, save_yaml
            char_file = paths.character_yaml(char_id)
            char_data = load_character(paths, char_id)
            existing_refs = set(char_data.get("reference_images", []))
            view_filenames = {fn for fn, *_ in _FIVE_VIEWS}
            char_prefix = f"/api/assets/characters/{char_id}/"
            has_view_refs = any(
                u.startswith(char_prefix) and u[len(char_prefix):] in view_filenames
                for u in existing_refs
            )
            if not has_view_refs:
                generated_urls = [f"/api/assets/characters/{char_id}/{fn}" for fn, *_ in _FIVE_VIEWS]
                _update_view_refs(char_data, char_id, generated_urls)
                data = load_yaml_full(char_file)
                data["character"] = char_data
                save_yaml(char_file, data)
                logger.info(f"  ✅ 补充五视图引用到 YAML ({len(generated_urls)} 张)")
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

    from infra.config import load_character, load_yaml_full
    char = load_character(paths, char_id)
    data = load_yaml_full(char_file) if char_file.exists() else {"character": char}

    if not container:
        with _generating_lock:
            _generating.pop(char_id, None)
        return ""

    try:
        comfyui = container.get("image")
        from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
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

        generated_urls = _generate_five_views(comfyui, wb, char_id, portrait_dir, char, project_dir, generation, force=force)
        _update_view_refs(char, char_id, generated_urls)
        if generated_urls:
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)

        # outfit 图
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit:
            _ensure_outfit_images(char_id, config, container, project_dir, portrait_dir, force=force)

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
                            project_dir: str, outfit_seed: int,
                            force: bool = False, gender: str = "") -> str | None:
    """为单个 outfit 生成参考图，返回 URL 或 None"""
    outfit_dir = portrait_dir / outfit_key
    if not force and outfit_dir.exists():
        from infra.constants import IMAGE_GLOB_PATTERNS
        existing = [f for ext in IMAGE_GLOB_PATTERNS for f in outfit_dir.glob(ext)]
        if existing:
            return None

    outfit_dir.mkdir(parents=True, exist_ok=True)
    from engines.prompt.builder import _ensure_gender_tag
    full_desc = _ensure_gender_tag(f"{appearance_en}, wearing {outfit_desc_en}", gender)

    fake_shot = {"characters": char_id, "emotion": "neutral", "shot_type": "全身",
                 "camera": "固定", "scene_name": "", "view_key": "full_body"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=outfit_seed)
    if not wf:
        return None

    _inject_ref_image(wf, str(cover_path) if cover_path.exists() else None, char_id, project_dir, comfyui, raise_on_error=True)

    # 全身服装图面部占比小，提高 PuLID 权重确保面部一致性
    from engines.workflow.utils import find_nodes_by_class
    pulid_nodes = find_nodes_by_class(wf, "ApplyPulidFlux")
    for nid in pulid_nodes:
        old_weight = wf[nid]["inputs"].get("weight", 0.75)
        new_weight = min(old_weight * 1.2, 0.95)
        wf[nid]["inputs"]["weight"] = new_weight
        logger.debug(f"  Outfit PuLID weight: {old_weight:.2f} → {new_weight:.2f}")

    try:
        files = comfyui.generate(wf, str(outfit_dir))
    except Exception as e:
        logger.warning(f"  ⚠ outfit '{outfit_key}' 生成失败: {e}")
        return None
    if not files:
        return None
    cover_out = outfit_dir / "cover.png"
    try:
        _safe_rename(files[0], str(cover_out))
    except FileNotFoundError:
        logger.error(f"生成文件丢失: {files[0]}")
        return None
    return f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"


def _ensure_outfit_images(char_id: str, config: dict, container,
                          project_dir: str, portrait_dir: Path,
                          force: bool = False) -> None:
    """为角色的各 outfit 生成参考图（如果尚未存在）"""
    from infra.config import ProjectPaths, load_character, load_yaml_full
    paths = ProjectPaths(project_dir)
    char_file = paths.character_yaml(char_id)
    if not char_file.exists():
        return

    char = load_character(paths, char_id)
    if not char or char == {"id": char_id}:
        logger.warning(f"加载角色配置失败 {char_id}")
        return
    data = load_yaml_full(char_file)
    outfits = char.get("outfits", {})
    if not isinstance(outfits, dict) or not outfits:
        return

    comfyui = container.get("image")
    from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
    models = config.get("models", {})
    wb = WorkflowBuilder(WorkflowBuilderConfig(config=config, models=models, project_dir=str(paths.root), comfyui=comfyui, force=force, no_auto_gen=True))
    wb.load_workflows()

    cover_path = portrait_dir / "cover.png"
    generation = char.get("portrait_generation", 0)
    appearance_en = char.get("appearance_prompt_en", "") or char.get("appearance", "")
    if not appearance_en:
        from infra.constants import ERR_NOT_PREPARED
        logger.error(f"角色 '{char_id}' 缺少外貌描述（appearance），无法生成定妆照")
        return

    for outfit_key, outfit_val in outfits.items():
        if not isinstance(outfit_val, dict) or not outfit_val.get("description"):
            continue
        outfit_desc_en = outfit_val.get("description_en", "") or outfit_val.get("description", "")
        if not outfit_desc_en:
            continue

        outfit_seed = _outfit_seed(char_id, generation, outfit_key)
        url = _generate_single_outfit(comfyui, wb, char_id, outfit_key,
                                      outfit_desc_en, appearance_en, portrait_dir,
                                      cover_path, project_dir, outfit_seed, force=force,
                                      gender=char.get("gender", ""))
        if url:
            outfit_val.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
            outfit_val["reference_images"].append(url)
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)
            logger.info(f"  👗 outfit '{outfit_key}' 生成完成 (seed={outfit_seed})")
