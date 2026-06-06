"""工作流注入 — IP-Adapter / PuLID-Flux / LoRA 节点注入

从 workflow_builder.py 拆分而来。
所有函数接受 builder 作为第一个参数，访问其 _paths / project_dir / config 等属性。

用法（在 WorkflowBuilder 内部）：
    from engines.workflow_inject import (
        inject_character_refs, inject_ip_adapter_plus, inject_ip_adapter_chain,
        inject_pulid_flux, inject_pulid_flux_chain,
        find_character_lora, find_style_lora, inject_lora,
    )
"""
from __future__ import annotations

import copy
import itertools
import logging
import os
from pathlib import Path

from engines.workflow import (
    find_character_load_image_nodes, find_first_node, find_nodes_by_class,
    resolve_model_source,
)

logger = logging.getLogger(__name__)

# 原子计数器 — 保证单个工作流内节点 ID 唯一（替代 random.randint 碰撞风险）
_suffix_counter = itertools.count(1000)

__all__ = [
    "inject_character_refs", "update_existing_ip_adapter",
    "inject_ip_adapter_plus", "inject_ip_adapter_chain",
    "inject_pulid_flux", "inject_pulid_flux_chain",
    "find_character_lora", "find_style_lora", "inject_lora",
]


# ══════════════════════════════════════════════════════════
#  IP-Adapter Plus 注入（SD1.5/SDXL UNet 架构）
# ══════════════════════════════════════════════════════════

def inject_character_refs(builder: object, wf: dict, char_ids: list[str],
                          ip_config: dict, outfit: str = "") -> dict:
    """注入角色参考图到工作流（IP-Adapter Plus 链式注入）

    支持两种模式：
    1. 模板已含 IP-Adapter 节点 → 只更新参考图和权重
    2. 模板不含 IP-Adapter 节点 → 完整注入 IPAdapterModelLoader + CLIPVisionLoader + IPAdapterAdvanced
    """
    if not char_ids:
        return wf

    primary_id = char_ids[0]
    primary_refs = builder._get_character_refs(primary_id, outfit=outfit)
    existing_ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")

    if existing_ip_nodes:
        wf = update_existing_ip_adapter(builder, wf, char_ids, ip_config, outfit)
    else:
        if primary_refs:
            wf = inject_ip_adapter_plus(wf, primary_id, primary_refs, ip_config)
        else:
            logger.warning(f"角色 '{primary_id}' 无定妆照，跳过 IP-Adapter 注入")

        if len(char_ids) > 1:
            for secondary_id in char_ids[1:]:
                secondary_refs = builder._get_character_refs(secondary_id, outfit=outfit)
                if secondary_refs:
                    secondary_weight = ip_config.get("secondary_weight",
                        max(0.3, ip_config.get("weight", 0.75) * 0.6))
                    wf = inject_ip_adapter_chain(wf, secondary_id, secondary_refs,
                                                  weight=secondary_weight, ip_config=ip_config)
                else:
                    logger.warning(f"第二角色 '{secondary_id}' 无定妆照，跳过 IP-Adapter")

    return wf


def update_existing_ip_adapter(builder: object, wf: dict, char_ids: list[str],
                                ip_config: dict, outfit: str = "") -> dict:
    """更新模板中已有的 IP-Adapter 节点（参考图 + 权重）"""
    weight = ip_config.get("weight", 0.75)
    ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")

    if ip_nodes:
        wf[ip_nodes[0]]["inputs"]["weight"] = weight
        for key in ("weight_type", "combine_embeds", "embeds_scaling", "start_at", "end_at"):
            if key in ip_config:
                wf[ip_nodes[0]]["inputs"][key] = ip_config[key]

    primary_id = char_ids[0]
    primary_refs = builder._get_character_refs(primary_id, outfit=outfit)
    char_nodes = find_character_load_image_nodes(wf)
    if primary_refs and char_nodes:
        wf[char_nodes[0]]["inputs"]["image"] = os.path.basename(primary_refs[0])

    if len(char_ids) > 1:
        for secondary_id in char_ids[1:]:
            secondary_refs = builder._get_character_refs(secondary_id, outfit=outfit)
            if secondary_refs:
                secondary_weight = ip_config.get("secondary_weight",
                    max(0.3, weight * 0.6))
                wf = inject_ip_adapter_chain(wf, secondary_id, secondary_refs,
                                              weight=secondary_weight, ip_config=ip_config)

    return wf


def inject_ip_adapter_plus(wf: dict, char_id: str, ref_images: list[str],
                           ip_config: dict) -> dict:
    """完整注入 IP-Adapter Plus 子图（IPAdapterModelLoader + CLIPVisionLoader + IPAdapterAdvanced + LoadImage）"""
    wf = copy.deepcopy(wf)

    ksampler = find_first_node(wf, "KSampler")
    if not ksampler:
        logger.warning("未找到 KSampler，无法注入 IP-Adapter")
        return wf
    model_source = resolve_model_source(wf, ksampler)
    if not model_source:
        logger.warning("未找到模型加载节点，无法注入 IP-Adapter")
        return wf

    weight = ip_config.get("weight", 0.75)
    suffix = next(_suffix_counter)
    wf = _build_ip_adapter_nodes(wf, ksampler, model_source, ref_images[0], ip_config, weight, suffix)

    logger.info(f"注入 IP-Adapter Plus: {char_id} "
                f"(model={ip_config.get('model', 'ip-adapter-plus-face_sd15.safetensors')}, "
                f"weight={weight}, embeds_scaling={ip_config.get('embeds_scaling', 'V only')})")
    return wf


def _build_ip_adapter_nodes(wf: dict, ksampler: str, model_source: str,
                            ref_image: str, config: dict, weight: float, suffix: int) -> dict:
    """创建 IP-Adapter 节点子图并连接到 KSampler"""
    ip_model_name = config.get("model", "ip-adapter-plus-face_sd15.safetensors")
    clip_vision_name = config.get("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors")

    nodes = {
        f"ipadapter_model_{suffix}": {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": ip_model_name}},
        f"ipadapter_clip_vision_{suffix}": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": clip_vision_name}},
        f"ipadapter_ref_{suffix}": {
            "class_type": "LoadImage",
            "inputs": {"image": os.path.basename(ref_image)}},
    }
    ip_id = f"ipadapter_{suffix}"
    nodes[ip_id] = {
        "class_type": "IPAdapterAdvanced",
        "inputs": {
            "weight": weight,
            "weight_type": config.get("weight_type", "linear"),
            "combine_embeds": config.get("combine_embeds", "concat"),
            "start_at": config.get("start_at", 0.0),
            "end_at": config.get("end_at", 1.0),
            "embeds_scaling": config.get("embeds_scaling", "V only"),
            "model": [model_source, 0],
            "ipadapter": [f"ipadapter_model_{suffix}", 0],
            "clip_vision": [f"ipadapter_clip_vision_{suffix}", 0],
            "image": [f"ipadapter_ref_{suffix}", 0],
        }}
    wf.update(nodes)
    wf[ksampler]["inputs"]["model"] = [ip_id, 0]
    return wf


def inject_ip_adapter_chain(wf: dict, char_id: str, ref_images: list[str],
                             weight: float = 0.45, ip_config: dict | None = None) -> dict:
    """链式注入第二个角色的 IP-Adapter（串联在已有 IP-Adapter 之后）"""
    if not ref_images:
        logger.warning(f"inject_ip_adapter_chain: ref_images 为空，跳过 {char_id}")
        return wf
    wf = copy.deepcopy(wf)
    if ip_config is None:
        ip_config = {}

    ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
    if not ip_nodes:
        logger.warning("未找到已有 IP-Adapter 节点，无法链式注入")
        return wf

    last_ip = ip_nodes[-1]
    from engines.workflow_builder import WorkflowBuilder
    downstream_node, downstream_input = WorkflowBuilder._find_downstream_consumer(wf, last_ip)
    if not downstream_node:
        logger.warning(f"链式注入失败: 未找到 IP-Adapter 下游消费者，跳过 {char_id}")
        return wf

    suffix = next(_suffix_counter)
    new_load = f"ipadapter_ref2_{char_id}_{suffix}"
    new_ip = f"ipadapter2_{char_id}_{suffix}"

    weight_type = ip_config.get("weight_type", "linear")
    combine_embeds = ip_config.get("combine_embeds", "concat")
    start_at = ip_config.get("start_at", 0.0)
    end_at = ip_config.get("end_at", 1.0)
    embeds_scaling = ip_config.get("embeds_scaling", "V only")

    ip_model_node = None
    clip_vision_node = None
    for nid, node in wf.items():
        if node.get("class_type") == "IPAdapterModelLoader":
            ip_model_node = nid
        elif node.get("class_type") == "CLIPVisionLoader":
            clip_vision_node = nid

    wf[new_load] = {
        "class_type": "LoadImage",
        "inputs": {"image": os.path.basename(ref_images[0])}
    }

    ip_inputs = {
        "weight": weight, "weight_type": weight_type,
        "combine_embeds": combine_embeds,
        "start_at": start_at, "end_at": end_at,
        "embeds_scaling": embeds_scaling,
        "model": [last_ip, 0],
        "image": [new_load, 0],
    }
    if ip_model_node:
        ip_inputs["ipadapter"] = [ip_model_node, 0]
    if clip_vision_node:
        ip_inputs["clip_vision"] = [clip_vision_node, 0]

    wf[new_ip] = {"class_type": "IPAdapterAdvanced", "inputs": ip_inputs}

    if downstream_node and downstream_input:
        wf[downstream_node]["inputs"][downstream_input] = [new_ip, 0]

    logger.info(f"链式注入第二角色 IP-Adapter: {char_id} (weight={weight:.2f})")
    return wf


# ══════════════════════════════════════════════════════════
#  PuLID-Flux 注入（Flux DiT 架构专用）
# ══════════════════════════════════════════════════════════

def inject_pulid_flux(builder: object, wf: dict, char_ids: list[str],
                      pulid_config: dict, outfit: str = "") -> dict:
    """注入 PuLID-Flux 面部一致性节点（Flux 后端专用）"""
    wf = copy.deepcopy(wf)

    if not char_ids:
        return wf

    ksampler = find_first_node(wf, "KSampler")
    if not ksampler:
        logger.warning("未找到 KSampler，无法注入 PuLID-Flux")
        return wf
    model_source = resolve_model_source(wf, ksampler)
    if not model_source:
        logger.warning("未找到模型加载节点，无法注入 PuLID-Flux")
        return wf

    weight = pulid_config.get("weight", 0.9)
    primary_injected = False

    for char_id in char_ids:
        refs = builder._get_character_refs(char_id, outfit=outfit)
        if not refs:
            logger.warning(f"角色 '{char_id}' 无定妆照，跳过该角色的 PuLID-Flux 注入")
            continue

        if not primary_injected:
            suffix = next(_suffix_counter)
            wf = _inject_pulid_nodes(wf, ksampler, model_source, refs[0], pulid_config, weight, suffix)
            logger.info(f"注入 PuLID-Flux: {char_id} (weight={weight}, refs={os.path.basename(refs[0])})")
            primary_injected = True
        else:
            secondary_weight = max(0.3, weight * 0.7)
            wf = inject_pulid_flux_chain(
                wf, char_id, refs,
                weight=secondary_weight, pulid_config=pulid_config)

    return wf


def _inject_pulid_nodes(wf: dict, ksampler: str, model_source: str,
                        ref_image: str, config: dict, weight: float, suffix: int) -> dict:
    """创建 PuLID-Flux 节点子图并连接到 KSampler"""
    nodes = {
        f"pulid_model_{suffix}": {
            "class_type": "PulidFluxModelLoader",
            "inputs": {"pulid_file": config.get("model", "pulid_flux_v0.9.0.safetensors")}},
        f"pulid_insightface_{suffix}": {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {"provider": "CPU"}},
        f"pulid_eva_clip_{suffix}": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {}},
        f"pulid_ref_{suffix}": {
            "class_type": "LoadImage",
            "inputs": {"image": os.path.basename(ref_image)}},
    }
    apply_id = f"pulid_apply_{suffix}"
    nodes[apply_id] = {
        "class_type": "ApplyPulidFlux",
        "inputs": {
            "weight": weight, "start_at": config.get("start_at", 0.0), "end_at": config.get("end_at", 1.0),
            "model": [model_source, 0],
            "pulid_flux": [f"pulid_model_{suffix}", 0],
            "face_analysis": [f"pulid_insightface_{suffix}", 0],
            "eva_clip": [f"pulid_eva_clip_{suffix}", 0],
            "image": [f"pulid_ref_{suffix}", 0],
        }}
    wf.update(nodes)
    wf[ksampler]["inputs"]["model"] = [apply_id, 0]
    return wf


def inject_pulid_flux_chain(wf: dict, char_id: str, ref_images: list[str],
                             weight: float = 0.6, pulid_config: dict | None = None) -> dict:
    """链式注入第二个角色的 PuLID-Flux（串联在已有 PuLID 之后）"""
    if not ref_images:
        logger.warning(f"inject_pulid_flux_chain: ref_images 为空，跳过 {char_id}")
        return wf
    wf = copy.deepcopy(wf)
    if pulid_config is None:
        pulid_config = {}

    pulid_nodes = find_nodes_by_class(wf, "ApplyPulidFlux")
    if not pulid_nodes:
        logger.warning("未找到已有 PuLID-Flux 节点，无法链式注入")
        return wf

    last_pulid = pulid_nodes[-1]
    from engines.workflow_builder import WorkflowBuilder
    downstream_node, downstream_input = WorkflowBuilder._find_downstream_consumer(wf, last_pulid)
    if not downstream_node:
        logger.warning(f"链式注入失败: 未找到 PuLID-Flux 下游消费者，跳过 {char_id}")
        return wf

    pulid_model_node = None
    insightface_node = None
    eva_clip_node = None
    for nid, node in wf.items():
        ct = node.get("class_type", "")
        if ct == "PulidFluxModelLoader":
            pulid_model_node = nid
        elif ct == "PulidFluxInsightFaceLoader":
            insightface_node = nid
        elif ct == "PulidFluxEvaClipLoader":
            eva_clip_node = nid

    s = next(_suffix_counter)
    new_load = f"pulid_ref2_{char_id}_{s}"
    new_apply = f"pulid_apply2_{char_id}_{s}"

    wf[new_load] = {
        "class_type": "LoadImage",
        "inputs": {"image": os.path.basename(ref_images[0])}
    }

    apply_inputs = {
        "weight": weight,
        "start_at": pulid_config.get("start_at", 0.0),
        "end_at": pulid_config.get("end_at", 1.0),
        "model": [last_pulid, 0],
        "image": [new_load, 0],
    }
    if pulid_model_node:
        apply_inputs["pulid_flux"] = [pulid_model_node, 0]
    if insightface_node:
        apply_inputs["face_analysis"] = [insightface_node, 0]
    if eva_clip_node:
        apply_inputs["eva_clip"] = [eva_clip_node, 0]

    wf[new_apply] = {"class_type": "ApplyPulidFlux", "inputs": apply_inputs}

    if downstream_node and downstream_input:
        wf[downstream_node]["inputs"][downstream_input] = [new_apply, 0]

    logger.info(f"链式注入第二角色 PuLID-Flux: {char_id} (weight={weight:.2f})")
    return wf


# ══════════════════════════════════════════════════════════
#  LoRA 查找与注入
# ══════════════════════════════════════════════════════════

def find_character_lora(builder: object, char_id: str) -> str | None:
    """查找已训练的角色 LoRA 文件。

    搜索顺序：comfyui_asset_name 规范名 → 原始名 → 角色 lora 子目录。

    Args:
        builder: WorkflowBuilder 实例
        char_id: 角色 ID

    Returns:
        LoRA 文件路径，未找到返回 None
    """
    lora_dir = builder._paths.loras_dir
    from infra.asset_tracker import comfyui_asset_name
    lora_name = comfyui_asset_name(builder.project_dir, char_id, f"{char_id}_lora.safetensors")
    candidates = [
        lora_dir / lora_name,
        lora_dir / f"{char_id}_lora.safetensors",
        lora_dir / f"{char_id}.safetensors",
    ]
    char_dir = builder._paths.character_lora_dir(char_id)
    if char_dir.exists():
        for f in char_dir.glob("*.safetensors"):
            candidates.append(f)

    for p in candidates:
        if p.exists():
            return str(p)
    return None


def find_style_lora(builder: object, genre: str) -> str | None:
    """查找已训练的风格 LoRA 文件。

    Args:
        builder: WorkflowBuilder 实例
        genre: 题材类型（如 urban、romance）

    Returns:
        LoRA 文件路径，未找到返回 None
    """
    lora_dir = builder._paths.loras_dir
    candidates = [
        lora_dir / f"style_{genre}_lora.safetensors",
        lora_dir / f"style_{genre}.safetensors",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def inject_lora(wf: dict, lora_path: str, strength: float = 0.7,
                lora_name: str | None = None) -> dict:
    """向工作流注入 LoRA 加载节点

    在 UNETLoader/CheckpointLoader 之后、KSampler 之前插入 LoraLoader 节点。

    Args:
        lora_name: ComfyUI 服务端的 LoRA 文件名。由调用方决定命名策略：
            - 字符 LoRA: comfyui_asset_name()（带 project hash 防跨项目碰撞）
            - 风格 LoRA: os.path.basename()（用户手动放置，保持原名）
            - None: 回退到 os.path.basename()
    """
    wf = copy.deepcopy(wf)

    ksampler = find_first_node(wf, "KSampler")
    if not ksampler:
        logger.warning("未找到 KSampler 节点，无法注入 LoRA")
        return wf

    # 追踪当前 KSampler 的实际 model/clip 来源（可能是前一个 LoRA 的输出）
    model_source = resolve_model_source(wf, ksampler)
    if not model_source:
        logger.warning("未找到模型加载节点，无法注入 LoRA")
        return wf

    clip_ref = wf[ksampler].get("inputs", {}).get("clip")
    if isinstance(clip_ref, list) and len(clip_ref) == 2:
        clip_source, clip_output_idx = clip_ref[0], clip_ref[1]
    else:
        clip_source, clip_output_idx = None, 0
        if wf.get(model_source, {}).get("class_type") == "CheckpointLoaderSimple":
            clip_source = model_source
            clip_output_idx = 1
        else:
            clip_source = (find_first_node(wf, "DualCLIPLoader")
                           or find_first_node(wf, "CLIPLoader"))
        if not clip_source:
            logger.warning(f"inject_lora: 未找到 CLIP 来源节点，LoRA clip 将指向 model 节点（可能不正确）")

    lora_node_id = f"lora_{Path(lora_path).stem}_{next(_suffix_counter)}"
    if not lora_name:
        lora_name = os.path.basename(lora_path)

    wf[lora_node_id] = {
        "class_type": "LoraLoader",
        "inputs": {
            "lora_name": lora_name,
            "strength_model": strength,
            "strength_clip": strength,
            "model": [model_source, 0],
            "clip": [clip_source, clip_output_idx] if clip_source else [model_source, 0],
        }
    }

    wf[ksampler]["inputs"]["model"] = [lora_node_id, 0]
    wf[ksampler]["inputs"]["clip"] = [lora_node_id, 1]

    logger.info(f"注入 LoRA 节点: {lora_node_id} (strength={strength})")
    return wf
