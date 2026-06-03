"""定妆照生成 — 为角色生成五视图 + 各服装参考图

被以下入口调用：
- portraits_task / drama portraits CLI（批量，Celery）
- portrait_single_task（单角色，Celery）
"""
from __future__ import annotations

from infra.constants import STATUS_DONE
import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from infra.config import Config, load_yaml_full
from engines.portrait import (
    _view_seed, _outfit_seed, _generating, _generating_lock, _FIVE_VIEWS,
    _generate_view as _engine_generate_view, ViewGenParams,
)

logger = logging.getLogger(__name__)


@dataclass
class OutfitGenParams:
    """服装生成参数 — 消除 _generate_outfit/_process_outfits 的 10 个参数"""
    char_id: str
    outfit_key: str
    outfit_desc: str
    base_dir: Path
    comfyui: object
    wb: object
    seed: int | None = None
    ref_image: str | None = None
    project_dir: str = ""
    appearance_prompt_en: str = ""


@dataclass
class ProcessOutfitParams:
    """服装处理参数 — 消除 _process_outfits 的 10 个参数"""
    char: dict
    char_id: str
    generation: int
    portrait_dir: Path
    cover_path: Path
    comfyui: object
    wb: object
    appearance_prompt_en: str
    paths: object
    force: bool = False



def _generate_outfit(p: OutfitGenParams) -> bool:
    """为指定服装生成参考图，成功返回 True"""
    outfit_dir = p.base_dir / p.outfit_key
    outfit_dir.mkdir(parents=True, exist_ok=True)

    char_desc = p.appearance_prompt_en
    if not char_desc:
        from infra.constants import ERR_NOT_PREPARED
        logger.error(f"角色 '{p.char_id}' 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}")
        return False
    full_desc = f"{char_desc}, wearing {p.outfit_desc}"

    fake_shot = {"characters": p.char_id, "emotion": "neutral",
                 "shot_type": "全身", "camera": "固定"}
    _, wf = p.wb.build_first_frame(fake_shot, character_desc=full_desc, seed=p.seed)
    if not wf:
        return False

    if p.ref_image and os.path.exists(p.ref_image):
        from engines.workflow import find_character_load_image_nodes
        from infra.asset_tracker import comfyui_asset_name, AssetTracker
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            remote_name = comfyui_asset_name(p.project_dir, p.char_id, os.path.basename(p.ref_image))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                tracker = AssetTracker(p.project_dir)
                tracker.upload_if_needed(p.comfyui, p.ref_image, remote_name, p.comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    files = p.comfyui.generate(wf, str(outfit_dir))
    if not files:
        return False
    cover_path = outfit_dir / "cover.png"
    os.replace(files[0], str(p.cover_path))
    return True


def _generate_five_views(char: dict, char_id: str, portrait_dir: Path,
                         cover_path: Path, comfyui, wb, paths, force: bool) -> int:
    """生成五视图，返回成功数"""
    generation = char.get("portrait_generation", 0)
    if force and any((portrait_dir / fn).exists() for fn, *_ in _FIVE_VIEWS):
        generation += 1
        char["portrait_generation"] = generation
        from infra.config import save_yaml
        save_yaml(paths.character_yaml(char_id), {"character": char})
        logger.info(f"    🔄 重新生成，代数: {generation}")

    generated = 0
    for i, (filename, shot_type, camera, label, vk) in enumerate(_FIVE_VIEWS):
        view_path = portrait_dir / filename
        if view_path.exists() and not force:
            logger.info(f"    ⏭ {label}视图已存在: {filename}")
            continue
        logger.info(f"    🎨 生成{label}视图 ({filename})...")
        view_seed = _view_seed(char_id, generation, i)
        ref = str(cover_path) if i > 0 and cover_path.exists() else None
        try:
            ok = bool(_engine_generate_view(ViewGenParams(
                comfyui=comfyui, wb=wb, char_id=char_id, portrait_dir=portrait_dir,
                filename=filename, shot_type=shot_type, seed=view_seed, ref_image=ref,
                char=char, project_dir=str(paths.root), view_key=vk)))
            if ok:
                logger.info(f"    ✅ {label}视图完成 (seed={view_seed})")
                generated += 1
            else:
                logger.warning(f"    ⚠ {label}视图未生成")
        except Exception as e:
            logger.error(f"    ❌ {label}视图失败: {e}", exc_info=True)
    return generated


def _save_character_yaml_db(f: Path, data: dict, char_id: str, char: dict, write_db: bool) -> None:
    """写回角色 YAML"""
    from infra.config import save_yaml
    data["character"] = char
    save_yaml(f, data)
    logger.info(f"    📝 已更新 YAML")


def _process_single_character(f: Path, cfg, paths, cont, force: bool, write_db: bool) -> bool:
    """处理单个角色的定妆照生成，返回是否成功"""
    try:
        data = load_yaml_full(f)
    except Exception as e:
        logger.warning(f"角色 YAML 格式错误 {f}: {e}")
        return False

    char = data.get("character", {})
    char_id = char.get("id", "")
    if not char_id:
        return False
    logger.info(f"  角色: {char.get('name', char_id)} ({char_id})")

    portrait_dir = paths.character_asset_dir(char_id)
    portrait_dir.mkdir(parents=True, exist_ok=True)
    if not cont:
        logger.warning(f"    ⚠ 无 ComfyUI 连接，跳过")
        return False

    try:
        comfyui = cont.get("image")
        from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig
        wb = WorkflowBuilder(WorkflowBuilderConfig(
            config=cfg.data, models=cfg.get("models", {}), project_dir=str(paths.root),
            comfyui=comfyui, force=force))
        wb.load_workflows()

        import time as _time
        with _generating_lock:
            _generating[char_id] = _time.time()

        cover_path = portrait_dir / "cover.png"
        char_generated = _generate_five_views(char, char_id, portrait_dir, cover_path, comfyui, wb, paths, force)
        _update_view_refs(char, char_id, portrait_dir)

        appearance_prompt_en = char.get("appearance_prompt_en", "") or char.get("appearance", "")
        _process_outfits(ProcessOutfitParams(
            char=char, char_id=char_id, generation=char.get("portrait_generation", 0),
            portrait_dir=portrait_dir, cover_path=cover_path, comfyui=comfyui, wb=wb,
            appearance_prompt_en=appearance_prompt_en, paths=paths, force=force))

        _save_character_yaml_db(f, data, char_id, char, write_db)
        return char_generated > 0
    except Exception as e:
        logger.error(f"    ❌ 失败: {e}", exc_info=True)
        return False
    finally:
        with _generating_lock:
            _generating.pop(char_id, None)


def _update_view_refs(char: dict, char_id: str, portrait_dir: Path):
    """回写五视图 reference_images"""
    view_urls = []
    for filename, _, _, _, _ in _FIVE_VIEWS:
        if (portrait_dir / filename).exists():
            view_urls.append(f"/api/assets/characters/{char_id}/{filename}")
    if not view_urls:
        return
    char.setdefault("reference_images", [])
    prefix = f"/api/assets/characters/{char_id}/"
    view_filenames = {fn for fn, _, _, _, _ in _FIVE_VIEWS}
    char["reference_images"] = [
        u for u in char["reference_images"]
        if not u.startswith(prefix) or u.rsplit("/", 1)[-1] not in view_filenames
    ]
    existing_set = set(char["reference_images"])
    for url in view_urls:
        if url not in existing_set:
            char["reference_images"].append(url)


def _process_outfits(p: ProcessOutfitParams):
    """处理角色的各服装参考图"""
    outfits = p.char.get("outfits", {})
    if not isinstance(outfits, dict) or not outfits:
        return
    logger.info(f"    👗 服装: {', '.join(outfits.keys())}")
    for outfit_idx, (outfit_key, outfit_val) in enumerate(outfits.items()):
        if not isinstance(outfit_val, dict):
            continue
        outfit_desc_en = outfit_val.get("description_en", "")
        outfit_desc_zh = outfit_val.get("description", "")
        if not outfit_desc_en and not outfit_desc_zh:
            continue
        if not outfit_desc_en and outfit_desc_zh:
            from infra.constants import ERR_NOT_PREPARED_CN
            logger.warning(f"      ⚠ {outfit_key}: 尚未生成英文描述，{ERR_NOT_PREPARED_CN}")
            continue

        outfit_dir = p.portrait_dir / outfit_key
        outfit_existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
        if outfit_existing and not p.force:
            logger.info(f"      ⏭ {outfit_key}: 已有图，跳过")
            continue

        outfit_seed = _outfit_seed(p.char_id, p.generation, outfit_idx)
        ref = str(p.cover_path) if p.cover_path.exists() else None
        logger.info(f"      🎨 生成 {outfit_key}...")
        try:
            ok = _generate_outfit(OutfitGenParams(
                char_id=p.char_id, outfit_key=outfit_key, outfit_desc=outfit_desc_en,
                base_dir=p.portrait_dir, comfyui=p.comfyui, wb=p.wb,
                seed=outfit_seed, ref_image=ref,
                project_dir=str(p.paths.root),
                appearance_prompt_en=p.appearance_prompt_en))
            if ok:
                outfit_url = f"/api/assets/characters/{p.char_id}/{outfit_key}/cover.png"
                outfit_val.setdefault("reference_images", [])
                pfx = f"/api/assets/characters/{p.char_id}/{outfit_key}/cover"
                outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(pfx)]
                outfit_val["reference_images"].append(outfit_url)
                logger.info(f"      ✅ {outfit_key} 完成 (seed={outfit_seed})")
            else:
                logger.warning(f"      ⚠ {outfit_key} 未生成")
        except Exception as e:
            logger.error(f"      ❌ {outfit_key} 失败: {e}", exc_info=True)


def run_portraits(
    config_path: str,
    *,
    force: bool = False,
    char_ids: list[str] | None = None,
    write_db: bool = False,
):
    """生成定妆照（五视图 + 各服装参考图）"""
    cfg = Config(config_path)
    paths = cfg.paths
    logger.info("生成定妆照（五视图）")

    from api.registry import Container
    chars_dir = paths.characters_dir
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return

    try:
        cont = Container(cfg.data)
    except Exception as e:
        logger.warning(f"无法创建容器: {e}")
        cont = None

    if char_ids is not None:
        char_files = [chars_dir / f"{cid}.yaml" for cid in char_ids if (chars_dir / f"{cid}.yaml").exists()]
    else:
        from infra.config import load_yaml_entities as _load_wp
        char_files = [f for f, _ in _load_wp(chars_dir, "character", with_paths=True)]

    generated = 0
    for f in char_files:
        if _process_single_character(f, cfg, paths, cont, force, write_db):
            generated += 1

    logger.info(f"定妆照生成完成 ({generated} 个角色)")
    return {"status": STATUS_DONE, "generated": generated, "total": len(char_files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_portraits(args.config)


if __name__ == "__main__":
    main()
