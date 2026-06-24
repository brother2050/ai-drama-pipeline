"""工作流注入 — IP-Adapter / PuLID-Flux / ControlNet Depth / LoRA 节点注入

从 workflow_builder.py 拆分而来。
所有函数接受 builder 作为第一个参数，访问其 _paths / project_dir / config 等属性。

用法（在 WorkflowBuilder 内部）：
    from engines.workflow.inject import (
        inject_character_refs, inject_ip_adapter_plus, inject_ip_adapter_chain,
        inject_pulid_flux, inject_pulid_flux_chain,
        inject_controlnet_depth,
        find_character_lora, find_style_lora, inject_lora,
    )
"""
from __future__ import annotations

import itertools
import logging
import os
import threading
from pathlib import Path

from engines.workflow.utils import (
    find_character_load_image_nodes,
    find_first_node,
    find_nodes_by_class,
    resolve_model_source,
)

logger = logging.getLogger(__name__)

# 原子计数器 — 保证单个工作流内节点 ID 唯一
_suffix_counter = itertools.count(1000)
_counter_lock = threading.Lock()


def _next_suffix() -> int:
    with _counter_lock:
        return next(_suffix_counter)


# ══════════════════════════════════════════════════════════
#  通用辅助函数（消除重复代码）
# ══════════════════════════════════════════════════════════

def _find_model_pipeline(wf: dict) -> tuple[str | None, str | None]:
    """查找 KSampler / XlabsSampler 和其 model source 节点"""
    ksampler = find_first_node(wf, "KSampler")
    if not ksampler:
        ksampler = find_first_node(wf, "KSamplerAdvanced")
    if not ksampler:
        ksampler = find_first_node(wf, "XlabsSampler")
    if not ksampler:
        return None, None
    model_source = resolve_model_source(wf, ksampler)
    return ksampler, model_source


def _create_ref_nodes(wf: dict, ref_images: list[str], prefix: str,
                      suffix: int, project_dir: str = "", char_id: str = "") -> str:
    """创建参考图 LoadImage 节点（支持单图和多图 batch）

    单图: 返回 LoadImage 节点 ID
    多图: 返回最后一个 ImageBatch 节点 ID
    """
    from infra.storage.asset_tracker import comfyui_asset_name

    if len(ref_images) == 1:
        nid = f"{prefix}_{suffix}"
        ref_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref_images[0])) if project_dir else os.path.basename(ref_images[0])
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        return nid

    # 多图: LoadImage × N → ImageBatch 链
    load_nodes = []
    for i, ref in enumerate(ref_images):
        nid = f"{prefix}_{suffix}_{i}"
        ref_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref)) if project_dir else os.path.basename(ref)
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        load_nodes.append(nid)

    batch_prev = load_nodes[0]
    for i in range(1, len(load_nodes)):
        batch_nid = f"{prefix}_batch_{suffix}_{i}"
        wf[batch_nid] = {
            "class_type": "ImageBatch",
            "inputs": {"image1": [batch_prev, 0], "image2": [load_nodes[i], 0]}
        }
        batch_prev = batch_nid
    return batch_prev


def _upload_controlnet_ref(builder: object, local_path: str,
                          project_dir: str, char_id: str) -> None:
    """将 ControlNet 全身参考图上传到 ComfyUI 服务器"""
    try:
        comfyui = getattr(builder, 'comfyui', None)
        if not comfyui:
            logger.debug("builder 无 comfyui 引用，跳过 ControlNet 参考图上传")
            return
        from infra.storage.asset_tracker import AssetTracker, comfyui_asset_name
        remote_name = comfyui_asset_name(project_dir, char_id, os.path.basename(local_path))
        AssetTracker(project_dir).upload_if_needed(comfyui, local_path, remote_name, comfyui.url)
        logger.debug(f"ControlNet 参考图已上传: {remote_name}")
    except Exception as e:
        logger.warning(f"ControlNet 参考图上传失败: {e}")


def _connect_to_model_pipeline(wf: dict, ksampler: str, node_id: str) -> None:
    """将节点输出连接到 KSampler 的 model 输入"""
    wf[ksampler]["inputs"]["model"] = [node_id, 0]


__all__ = [
    "find_character_lora",
    "find_style_lora",
    "inject_character_refs",
    "inject_controlnet_depth",
    "inject_ip_adapter_chain",
    "inject_ip_adapter_plus",
    "inject_lora",
    "inject_pulid_flux",
    "inject_pulid_flux_chain",
    "update_existing_ip_adapter",
]


# ══════════════════════════════════════════════════════════
#  IP-Adapter Plus 注入（SD1.5/SDXL UNet 架构）
# ══════════════════════════════════════════════════════════

def inject_character_refs(builder: object, wf: dict, char_names: list[str],
                          ip_config: dict) -> dict:
    """注入角色参考图到工作流（IP-Adapter Plus 链式注入）

    支持多图参考（face + full_body）和单图参考（face only）。
    支持两种模式：
    1. 模板已含 IP-Adapter 节点 → 只更新参考图和权重
    2. 模板不含 IP-Adapter 节点 → 完整注入 IPAdapterModelLoader + CLIPVisionLoader + IPAdapterAdvanced
    """
    if not char_names:
        return wf
    weight = ip_config.get("weight", 0.75)
    if weight <= 0:
        logger.info(f"IP-Adapter weight={weight}，跳过注入")
        return wf

    primary_name = char_names[0]
    primary_refs = builder._get_character_refs(primary_name, _no_auto_gen=True, ip_config=ip_config)
    existing_ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
    project_dir = getattr(builder, 'project_dir', '')
    name_to_id = getattr(builder, '_char_name_to_id', {})

    if existing_ip_nodes:
        wf = update_existing_ip_adapter(builder, wf, char_names, ip_config)
    else:
        if primary_refs:
            resolved_id = name_to_id.get(primary_name, primary_name)
            wf = inject_ip_adapter_plus(wf, resolved_id, primary_refs, ip_config,
                                         project_dir=project_dir, char_name=primary_name)
        else:
            logger.warning(f"角色 '{primary_name}' 无定妆照，跳过 IP-Adapter 注入")

        if len(char_names) > 1:
            for secondary_name in char_names[1:]:
                secondary_refs = builder._get_character_refs(secondary_name, _no_auto_gen=True, ip_config=ip_config)
                if secondary_refs:
                    secondary_weight = ip_config.get("secondary_weight",
                        max(0.3, ip_config.get("weight", 0.75) * 0.6))
                    resolved_id = name_to_id.get(secondary_name, secondary_name)
                    wf = inject_ip_adapter_chain(wf, resolved_id, secondary_refs,
                                                  weight=secondary_weight, ip_config=ip_config,
                                                  project_dir=project_dir, char_name=secondary_name)
                else:
                    logger.warning(f"第二角色 '{secondary_name}' 无定妆照，跳过 IP-Adapter")

    return wf


def update_existing_ip_adapter(builder: object, wf: dict, char_names: list[str],
                                ip_config: dict) -> dict:
    """更新模板中已有的 IP-Adapter 节点（参考图 + 权重）"""
    weight = ip_config.get("weight", 0.75)
    ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")

    if ip_nodes:
        wf[ip_nodes[0]]["inputs"]["weight"] = weight
        for key in ("weight_type", "combine_embeds", "embeds_scaling", "start_at", "end_at"):
            if key in ip_config:
                wf[ip_nodes[0]]["inputs"][key] = ip_config[key]

    primary_name = char_names[0]
    primary_refs = builder._get_character_refs(primary_name, _no_auto_gen=True)
    char_nodes = find_character_load_image_nodes(wf)
    name_to_id = getattr(builder, '_char_name_to_id', {})
    project_dir = getattr(builder, 'project_dir', '')
    if primary_refs and char_nodes:
        from infra.storage.asset_tracker import comfyui_asset_name
        resolved_id = name_to_id.get(primary_name, primary_name)
        wf[char_nodes[0]]["inputs"]["image"] = comfyui_asset_name(
            project_dir, resolved_id, os.path.basename(primary_refs[0]))

    if len(char_names) > 1:
        for secondary_name in char_names[1:]:
            secondary_refs = builder._get_character_refs(secondary_name, _no_auto_gen=True)
            if secondary_refs:
                secondary_weight = ip_config.get("secondary_weight",
                    max(0.3, weight * 0.6))
                resolved_id = name_to_id.get(secondary_name, secondary_name)
                wf = inject_ip_adapter_chain(wf, resolved_id, secondary_refs,
                                              weight=secondary_weight, ip_config=ip_config,
                                              project_dir=project_dir, char_name=secondary_name)

    return wf


def inject_ip_adapter_plus(wf: dict, char_id: str, ref_images: list[str],
                           ip_config: dict, project_dir: str = "",
                           char_name: str = "") -> dict:
    """完整注入 IP-Adapter Plus 子图（IPAdapterModelLoader + CLIPVisionLoader + IPAdapterAdvanced + LoadImage）

    支持单图和多图参考：
    - 单图：直接 LoadImage → IPAdapterAdvanced
    - 多图：LoadImage × N → ImageBatch 链 → IPAdapterAdvanced

    char_id: hash ID（资产命名用）
    char_name: 角色名（日志用，为空时回退到 char_id）
    注意: 就地修改 wf，调用方需确保已 deepcopy。
    """
    display = char_name or char_id
    if not ref_images:
        logger.warning(f"inject_ip_adapter_plus: ref_images 为空，跳过 {display}")
        return wf

    ksampler, model_source = _find_model_pipeline(wf)
    if not ksampler or not model_source:
        logger.warning("未找到 KSampler 或模型加载节点，无法注入 IP-Adapter")
        return wf

    weight = ip_config.get("weight", 0.75)
    suffix = _next_suffix()
    wf = _build_ip_adapter_nodes(wf, ksampler, model_source, ref_images, ip_config, weight, suffix,
                                  project_dir=project_dir, char_id=char_id)

    logger.info(f"注入 IP-Adapter Plus: {display} "
                f"(model={ip_config.get('model', 'ip-adapter-plus-face_sd15.safetensors')}, "
                f"weight={weight}, refs={len(ref_images)}, "
                f"embeds_scaling={ip_config.get('embeds_scaling', 'V only')})")
    return wf


def _build_ip_adapter_nodes(wf: dict, ksampler: str, model_source: str,
                            ref_images: list[str], config: dict, weight: float, suffix: int,
                            project_dir: str = "", char_id: str = "") -> dict:
    """创建 IP-Adapter 节点子图（支持单图和多图参考）

    单图: LoadImage → IPAdapterAdvanced
    多图: LoadImage × N → ImageBatch 链 → IPAdapterAdvanced
    """
    if model_source not in wf:
        logger.warning(f"model_source '{model_source}' 不在工作流中，跳过 IP-Adapter 构建")
        return wf

    # 模型加载器 + CLIP Vision 加载器
    wf[f"ipadapter_model_{suffix}"] = {
        "class_type": "IPAdapterModelLoader",
        "inputs": {"ipadapter_file": config.get("model", "ip-adapter-plus-face_sd15.safetensors")}
    }
    wf[f"ipadapter_clip_vision_{suffix}"] = {
        "class_type": "CLIPVisionLoader",
        "inputs": {"clip_name": config.get("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors")}
    }

    # 参考图节点（单图或多图 batch）
    ref_node = _create_ref_nodes(wf, ref_images, "ipadapter_ref", suffix, project_dir, char_id)

    # IPAdapterAdvanced
    ip_id = f"ipadapter_{suffix}"
    wf[ip_id] = {
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
            "image": [ref_node, 0],
        }
    }
    _connect_to_model_pipeline(wf, ksampler, ip_id)
    return wf


def inject_ip_adapter_chain(wf: dict, char_id: str, ref_images: list[str],
                             weight: float = 0.45, ip_config: dict | None = None,
                             project_dir: str = "", char_name: str = "") -> dict:
    """链式注入第二个角色的 IP-Adapter（串联在已有 IP-Adapter 之后）

    支持多图参考：多张参考图通过 ImageBatch 合并后注入。

    char_id: hash ID（资产命名用）
    char_name: 角色名（日志用，为空时回退到 char_id）
    注意: 就地修改 wf，调用方需确保已 deepcopy。
    """
    display = char_name or char_id
    if not ref_images:
        logger.warning(f"inject_ip_adapter_chain: ref_images 为空，跳过 {display}")
        return wf
    if ip_config is None:
        ip_config = {}

    ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
    if not ip_nodes:
        logger.warning("未找到已有 IP-Adapter 节点，无法链式注入")
        return wf

    last_ip = ip_nodes[-1]
    from engines.workflow.builder import WorkflowBuilder
    downstream_node, downstream_input = WorkflowBuilder._find_downstream_consumer(wf, last_ip)
    if not downstream_node:
        logger.warning(f"链式注入失败: 未找到 IP-Adapter 下游消费者，跳过 {display}")
        return wf

    suffix = _next_suffix()
    new_ip = f"ipadapter2_{char_id}_{suffix}"

    # 使用通用辅助函数创建参考图节点
    ref_node = _create_ref_nodes(wf, ref_images, f"ipadapter_ref2_{char_id}", suffix, project_dir, char_id)

    # 复用已有的 IP-Adapter 模型和 CLIP Vision 加载器
    ip_model_node = None
    clip_vision_node = None
    for nid, node in wf.items():
        if node.get("class_type") == "IPAdapterModelLoader":
            ip_model_node = nid
        elif node.get("class_type") == "CLIPVisionLoader":
            clip_vision_node = nid

    ip_inputs = {
        "weight": weight,
        "weight_type": ip_config.get("weight_type", "linear"),
        "combine_embeds": ip_config.get("combine_embeds", "concat"),
        "start_at": ip_config.get("start_at", 0.0),
        "end_at": ip_config.get("end_at", 1.0),
        "embeds_scaling": ip_config.get("embeds_scaling", "V only"),
        "model": [last_ip, 0],
        "image": [ref_node, 0],
    }
    if ip_model_node:
        ip_inputs["ipadapter"] = [ip_model_node, 0]
    if clip_vision_node:
        ip_inputs["clip_vision"] = [clip_vision_node, 0]

    wf[new_ip] = {"class_type": "IPAdapterAdvanced", "inputs": ip_inputs}

    if downstream_node and downstream_input:
        wf[downstream_node]["inputs"][downstream_input] = [new_ip, 0]

    logger.info(f"链式注入第二角色 IP-Adapter: {display} (weight={weight:.2f}, refs={len(ref_images)})")
    return wf


# ══════════════════════════════════════════════════════════
#  PuLID-Flux 注入（Flux DiT 架构专用）
# ══════════════════════════════════════════════════════════

_face_app = None
_face_app_lock = threading.Lock()
_insightface_warned = False


def _check_face_detectable(ref_image: str) -> bool:
    """轻量检查参考图是否含可检测的人脸（InsightFace）

    返回 True 表示检测到人脸，False 表示未检测到。
    InsightFace 不可用时返回 True（不阻断，让 ComfyUI 端处理）。
    使用模块级单例缓存 FaceAnalysis，避免每次调用重新加载模型。
    模型未预下载时跳过检查，避免在任务中触发极慢的 GitHub 下载。
    """
    global _face_app, _insightface_warned
    try:
        import cv2
        from insightface.app import FaceAnalysis
    except ImportError:
        logger.debug("InsightFace 不可用，跳过参考图人脸预检")
        return True

    # 检查模型是否已预下载（避免在 worker 任务中触发极慢的下载）
    model_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    if not model_dir.exists() or not any(model_dir.iterdir()):
        if not _insightface_warned:
            _insightface_warned = True
            logger.warning(
                "InsightFace buffalo_l 模型未下载，跳过人脸预检。"
                "请运行 `drama setup --insightface` 一次性预下载模型。"
            )
        return True

    try:
        if _face_app is None:
            with _face_app_lock:
                if _face_app is None:
                    _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
                    _face_app.prepare(ctx_id=0, det_size=(640, 640))
        img = cv2.imread(ref_image)
        if img is None:
            logger.warning(f"参考图读取失败: {ref_image}")
            return True  # 不阻断
        faces = _face_app.get(img)
        if not faces:
            return False
        return True
    except Exception as e:
        logger.debug(f"人脸预检异常（不阻断）: {e}")
        return True


def inject_pulid_flux(builder: object, wf: dict, char_names: list[str],
                      pulid_config: dict) -> dict:
    """注入 PuLID-Flux 面部一致性节点（Flux 后端专用）

    面部一致性始终使用主 cover.png（不随 outfit 变化）。
    注意: 就地修改 wf，调用方需确保已 deepcopy。
    """
    if not char_names:
        return wf
    weight = pulid_config.get("weight", 0.9)
    if weight <= 0:
        logger.info(f"PuLID-Flux weight={weight}，跳过注入")
        return wf

    ksampler = find_first_node(wf, "KSampler") or find_first_node(wf, "KSamplerAdvanced") or find_first_node(wf, "XlabsSampler")
    if not ksampler:
        logger.warning("未找到 KSampler / XlabsSampler，无法注入 PuLID-Flux")
        return wf
    model_source = resolve_model_source(wf, ksampler)
    if not model_source:
        logger.warning("未找到模型加载节点，无法注入 PuLID-Flux")
        return wf

    primary_injected = False
    name_to_id = getattr(builder, '_char_name_to_id', {})
    project_dir = getattr(builder, 'project_dir', '')

    for char_name in char_names:
        refs = builder._get_character_refs(char_name, _no_auto_gen=True)
        if not refs:
            logger.warning(f"角色 '{char_name}' 无定妆照，跳过该角色的 PuLID-Flux 注入")
            continue

        char_id = name_to_id.get(char_name, char_name)

        if not primary_injected:
            suffix = _next_suffix()
            wf = _inject_pulid_nodes(wf, ksampler, model_source, refs[0], pulid_config, weight, suffix,
                                      project_dir=project_dir, char_id=char_id)
            logger.info(f"注入 PuLID-Flux: {char_name} (weight={weight}, refs={os.path.basename(refs[0])})")
            primary_injected = True
        else:
            secondary_weight = max(0.3, weight * 0.7)
            wf = inject_pulid_flux_chain(
                wf, char_id, refs,
                weight=secondary_weight, pulid_config=pulid_config,
                project_dir=project_dir, char_name=char_name)

    return wf


def _inject_pulid_nodes(wf: dict, ksampler: str, model_source: str,
                        ref_image: str, config: dict, weight: float, suffix: int,
                        project_dir: str = "", char_id: str = "") -> dict:
    """创建 PuLID-Flux 节点子图并连接到 KSampler"""
    from infra.storage.asset_tracker import comfyui_asset_name
    ref_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref_image)) if project_dir else os.path.basename(ref_image)
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
            "inputs": {"image": ref_name}},
    }
    apply_id = f"pulid_apply_{suffix}"
    nodes[apply_id] = {
        "class_type": "ApplyPulidFlux",
        "inputs": {
            "weight": weight, "start_at": config.get("start_at", 0.0), "end_at": config.get("end_at", 1.0),
            "fusion": config.get("fusion", "mean"),
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
                             weight: float = 0.6, pulid_config: dict | None = None,
                             project_dir: str = "", char_name: str = "") -> dict:
    """链式注入第二个角色的 PuLID-Flux（串联在已有 PuLID 之后）

    char_id: hash ID（资产命名用）
    char_name: 角色名（日志用，为空时回退到 char_id）
    注意: 就地修改 wf，调用方需确保已 deepcopy。
    """
    display = char_name or char_id
    if not ref_images:
        logger.warning(f"inject_pulid_flux_chain: ref_images 为空，跳过 {display}")
        return wf
    if pulid_config is None:
        pulid_config = {}

    pulid_nodes = find_nodes_by_class(wf, "ApplyPulidFlux")
    if not pulid_nodes:
        logger.warning("未找到已有 PuLID-Flux 节点，无法链式注入")
        return wf

    last_pulid = pulid_nodes[-1]
    from engines.workflow.builder import WorkflowBuilder
    downstream_node, downstream_input = WorkflowBuilder._find_downstream_consumer(wf, last_pulid)
    if not downstream_node:
        logger.warning(f"链式注入失败: 未找到 PuLID-Flux 下游消费者，跳过 {display}")
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

    s = _next_suffix()
    new_load = f"pulid_ref2_{char_id}_{s}"
    new_apply = f"pulid_apply2_{char_id}_{s}"

    from infra.storage.asset_tracker import comfyui_asset_name
    ref_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref_images[0])) if project_dir else os.path.basename(ref_images[0])
    wf[new_load] = {
        "class_type": "LoadImage",
        "inputs": {"image": ref_name}
    }

    apply_inputs = {
        "weight": weight,
        "start_at": pulid_config.get("start_at", 0.0),
        "end_at": pulid_config.get("end_at", 1.0),
        "fusion": pulid_config.get("fusion", "mean"),
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

    logger.info(f"链式注入第二角色 PuLID-Flux: {display} (weight={weight:.2f})")
    return wf


# ══════════════════════════════════════════════════════════
#  LoRA 查找与注入
# ══════════════════════════════════════════════════════════

def find_character_lora(builder: object, char_id: str) -> str | None:
    """查找已训练的角色 LoRA 文件。

    char_id: 角色名或 hash ID。自动通过 builder 的映射转换。

    搜索顺序：comfyui_asset_name 规范名 → 原始名 → 角色 lora 子目录。
    """
    # name → hash ID
    resolved_id = builder._char_name_to_id.get(char_id, char_id)
    lora_dir = builder._paths.loras_dir
    from infra.storage.asset_tracker import comfyui_asset_name
    lora_name = comfyui_asset_name(builder.project_dir, resolved_id, f"{resolved_id}_lora.safetensors")
    candidates = [
        lora_dir / lora_name,
        lora_dir / f"{resolved_id}_lora.safetensors",
        lora_dir / f"{resolved_id}.safetensors",
    ]
    char_dir = builder._paths.character_lora_dir(resolved_id)
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


def _rewire_clip_to_text_encoders(wf: dict, ksampler: str, source_node: str) -> None:
    """将 source_node 的 clip 输出连到 KSampler 引用的所有 CLIPTextEncode 节点

    KSampler 不接受 clip 输入（ComfyUI v0.24+），clip 应连到 CLIPTextEncode
    用于编码 prompt。此函数自动找到 KSampler positive/negative（或 XlabsSampler
    conditioning/neg_conditioning）引用的 CLIPTextEncode 节点并重定向其 clip 输入。
    """
    text_encoder_ids: set[str] = set()
    sampler_node = wf.get(ksampler, {})
    sampler_inputs = sampler_node.get("inputs", {})
    sampler_class = sampler_node.get("class_type", "")

    # KSampler: positive/negative; XlabsSampler: conditioning/neg_conditioning
    if sampler_class == "XlabsSampler":
        pos_key, neg_key = "conditioning", "neg_conditioning"
    else:
        pos_key, neg_key = "positive", "negative"

    for key in (pos_key, neg_key):
        ref = sampler_inputs.get(key, [])
        if isinstance(ref, list) and len(ref) >= 1:
            text_encoder_ids.add(str(ref[0]))
    # 也处理 DualCFGGuider 等节点引用的 CLIPTextEncode
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") == "DualCFGGuider":
            for key in ("negative", "cfg_cond2_negative"):
                ref = node.get("inputs", {}).get(key, [])
                if isinstance(ref, list) and len(ref) >= 1:
                    text_encoder_ids.add(str(ref[0]))
    for te_id in text_encoder_ids:
        if te_id in wf and wf[te_id].get("class_type") == "CLIPTextEncode":
            wf[te_id]["inputs"]["clip"] = [source_node, 1]


def inject_lora(wf: dict, lora_path: str, strength: float = 0.7,
                lora_name: str | None = None) -> dict:
    """向工作流注入 LoRA 加载节点

    在 UNETLoader/CheckpointLoader 之后、KSampler 之前插入 LoraLoader 节点。

    注意: 就地修改 wf，调用方需确保已 deepcopy。

    Args:
        lora_name: ComfyUI 服务端的 LoRA 文件名。由调用方决定命名策略：
            - 字符 LoRA: comfyui_asset_name()（带 project hash 防跨项目碰撞）
            - 风格 LoRA: os.path.basename()（用户手动放置，保持原名）
            - None: 回退到 os.path.basename()
    """

    ksampler = find_first_node(wf, "KSampler") or find_first_node(wf, "KSamplerAdvanced") or find_first_node(wf, "XlabsSampler")
    if not ksampler:
        logger.warning("未找到 KSampler / XlabsSampler 节点，无法注入 LoRA")
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
        # 沿 model_source 回溯 CLIP（CheckpointLoader/LoraLoader 都输出 model+clip）
        src_class = wf.get(model_source, {}).get("class_type", "")
        if src_class in ("CheckpointLoaderSimple", "LoraLoader"):
            clip_source, clip_output_idx = model_source, 1
        else:
            # UNETLoader 无 CLIP 输出，找独立的 CLIPLoader
            clip_source = (find_first_node(wf, "DualCLIPLoader")
                           or find_first_node(wf, "CLIPLoader"))
            clip_output_idx = 0
            if not clip_source:
                logger.error(f"inject_lora: 未找到 CLIP 来源节点（{lora_path}），跳过 LoRA 注入")
                return wf

    lora_node_id = f"lora_{Path(lora_path).stem}_{_next_suffix()}"
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

    # clip 输出连到 KSampler 引用的 CLIPTextEncode 节点（KSampler 自身不接受 clip）
    _rewire_clip_to_text_encoders(wf, ksampler, lora_node_id)

    logger.info(f"注入 LoRA 节点: {lora_node_id} (strength={strength})")
    return wf


# ══════════════════════════════════════════════════════════
#  ControlNet Depth 注入（Flux 全身结构一致性）
# ══════════════════════════════════════════════════════════

def inject_controlnet_depth(builder: object, wf: dict, char_names: list[str],
                            cn_config: dict) -> dict:
    """注入 ControlNet Depth 节点（Flux 全身结构一致性）

    从角色全身参考图生成 depth map，通过 ControlNet 强制身体结构一致。
    支持多角色：主角色 full strength，次要角色降权。

    需要 ComfyUI 安装：
    - comfyui_controlnet_aux（提供 MiDaS-DepthMapPreprocessor 深度估计节点）
    - x-flux-comfyui（XLabs 提供 LoadFluxControlNet / ApplyFluxControlNet 节点）

    注意: 就地修改 wf，调用方需确保已 deepcopy。
    """
    if not char_names:
        return wf

    strength = cn_config.get("strength", 0.8)
    if strength <= 0:
        logger.info(f"ControlNet Depth strength={strength}，跳过注入")
        return wf

    ksampler, model_source = _find_model_pipeline(wf)
    if not ksampler or not model_source:
        logger.warning("未找到 KSampler 或模型加载节点，无法注入 ControlNet Depth")
        return wf

    project_dir = getattr(builder, 'project_dir', '')
    cn_model = cn_config.get("model", "flux-depth-controlnet-v3.safetensors")
    base_model = cn_config.get("base_model", "flux-dev")

    injected_count = 0

    for idx, char_name in enumerate(char_names):
        # 获取角色全身参考图
        refs = builder._get_character_refs(char_name, _no_auto_gen=True)
        if not refs:
            logger.debug(f"角色 '{char_name}' 无参考图，跳过 ControlNet Depth")
            continue

        # 优先使用全身视图
        resolved_id = builder._char_name_to_id.get(char_name, char_name)
        full_body_ref = builder._paths.full_body_ref(resolved_id)
        if not full_body_ref:
            full_body_ref = Path(refs[0])

        if not full_body_ref.exists():
            logger.debug(f"角色 '{char_name}' 无全身参考图，跳过 ControlNet Depth")
            continue

        suffix = _next_suffix()
        resolved_id = builder._char_name_to_id.get(char_name, char_name)

        # 使用通用辅助函数创建参考图节点
        ref_node = _create_ref_nodes(wf, [str(full_body_ref)], "controlnet_ref", suffix, project_dir, resolved_id)

        # 上传全身参考图到 ComfyUI（ControlNet Depth 在工作流中引用它）
        _upload_controlnet_ref(builder, str(full_body_ref), project_dir, resolved_id)

        # 次要角色降权
        char_strength = strength if idx == 0 else max(0.3, strength * 0.6)

        # 获取当前模型连入 sampler 的源节点（可能已被 PuLID/IP-Adapter 改写）
        current_model_src = wf[ksampler]["inputs"].get("model", [None, 0])

        nodes = {
            f"depth_estimation_{suffix}": {
                "class_type": "MiDaS-DepthMapPreprocessor",
                "inputs": {
                    "image": [ref_node, 0],
                    "resolution": 512,
                }
            },
            f"controlnet_model_{suffix}": {
                "class_type": "LoadFluxControlNet",
                "inputs": {
                    "model_name": base_model,
                    "controlnet_path": cn_model,
                }
            },
            f"controlnet_apply_{suffix}": {
                "class_type": "ApplyFluxControlNet",
                "inputs": {
                    "strength": char_strength,
                    "model": current_model_src,
                    "controlnet": [f"controlnet_model_{suffix}", 0],
                    "image": [f"depth_estimation_{suffix}", 0],
                }
            },
        }

        wf.update(nodes)
        injected_count += 1
        logger.info(f"ControlNet Depth: {char_name} (strength={char_strength:.2f})")

    if injected_count:
        # ApplyFluxControlNet 返回 1 个输出:
        #   output 0: ControlNetCondition → KSampler.controlnet_condition
        # 多角色时仅最后一个生效（sampler 只有一个 controlnet_condition 槽位）
        sampler_type = wf[ksampler].get("class_type", "")

        if sampler_type not in ("XlabsSampler",):
            # KSampler / KSamplerAdvanced: 支持 controlnet_condition 输入
            # ApplyFluxControlNet 的 ControlNetCondition 直接注入，不影响模型链
            wf[ksampler]["inputs"]["controlnet_condition"] = [f"controlnet_apply_{suffix}", 0]
        else:
            # XlabsSampler: 既无 controlnet_condition 输入，ApplyFluxControlNet 的
            # ControlNetCondition 也无法用作 model（类型不匹配）。保持原模型链不变。
            logger.debug("XlabsSampler 不支持 controlnet_condition，跳过 ControlNet Depth 连接")

        # 修复 XlabsSampler image_to_image_strength=0.0 的 bug:
        # 公式 t_idx = int((1 - strength) * len(timesteps)):
        #   0.0 → t_idx=len 越界 → denoise_controlnet 崩溃
        #   0.0 → t_idx=27 (clip后) → sigma=0 → 无去噪 → 纯噪音输出
        # 1.0 → t_idx=0 → 完整去噪 ✅
        if wf[ksampler]["inputs"].get("image_to_image_strength", None) == 0.0:
            wf[ksampler]["inputs"]["image_to_image_strength"] = 1.0
            logger.debug("image_to_image_strength 0.0→1.0 (XlabsSampler: t_idx=0 完整去噪)")

    return wf
