"""ComfyUI 工作流工具函数 — 节点查找、参数注入"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    "find_character_load_image_nodes", "find_lora_nodes",
    "find_ip_adapter_nodes", "find_pulid_flux_nodes",
    "set_clip_text_prompts",
    "resolve_node_aliases",
]


def resolve_node_aliases(workflow: dict, available_nodes: set[str]) -> dict:
    if not available_nodes:
        return workflow
    aliases = workflow.pop("_node_aliases", {})
    for nid, node in workflow.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct in available_nodes:
            continue
        for alt in aliases.get(ct, []):
            if alt in available_nodes:
                node["class_type"] = alt
                logger.info(f"别名: [{nid}] {ct} → {alt}")
                break
    return workflow


def find_first_node(wf: dict, class_type: str) -> str | None:
    for nid, node in wf.items():
        if not nid.startswith("_") and node.get("class_type") == class_type:
            return nid
    return None


def find_nodes_by_class(wf: dict, class_type: str) -> list[str]:
    return [nid for nid, node in wf.items()
            if not nid.startswith("_") and node.get("class_type") == class_type]


def find_load_image_nodes(wf: dict) -> list[str]:
    types = {"LoadImage", "LoadImageFromPath", "ImageLoad"}
    return [nid for nid, node in wf.items()
            if not nid.startswith("_") and node.get("class_type") in types]


def find_character_load_image_nodes(wf: dict) -> list[str]:
    """查找角色参考图的 LoadImage 节点（IP-Adapter / PuLID 专用）

    区分角色参考图节点和场景图节点：
    - ipadapter_ref_*: IP-Adapter 主角色参考图
    - ipadapter_ref2_*: IP-Adapter 次要角色参考图
    - pulid_ref_*: PuLID 主角色参考图
    - pulid_ref2_*: PuLID 次要角色参考图

    不包含场景图的 LoadImage 节点。
    """
    all_nodes = find_load_image_nodes(wf)
    # 排除场景图节点，只保留角色参考图节点
    # 但如果只有纯模板（无一致性节点），返回全部 LoadImage
    char_nodes = [n for n in all_nodes
                  if n.startswith("ipadapter_ref") or n.startswith("pulid_ref")]
    if char_nodes:
        return char_nodes
    return all_nodes


def find_ip_adapter_nodes(wf: dict) -> dict[str, list[str]]:
    """查找所有 IP-Adapter 相关节点，按类型分组

    Returns:
        {
            "ipadapter": ["ipadapter_xxx", ...],
            "model_loader": ["ipadapter_model_xxx", ...],
            "clip_vision": ["ipadapter_clip_vision_xxx", ...],
            "ref_images": ["ipadapter_ref_xxx", ...],
        }
    """
    result = {"ipadapter": [], "model_loader": [], "clip_vision": [], "ref_images": []}
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct == "IPAdapterAdvanced":
            result["ipadapter"].append(nid)
        elif ct == "IPAdapterModelLoader":
            result["model_loader"].append(nid)
        elif ct == "CLIPVisionLoader" and nid.startswith("ipadapter_"):
            result["clip_vision"].append(nid)
        elif ct == "LoadImage" and nid.startswith("ipadapter_ref"):
            result["ref_images"].append(nid)
    return result


def find_pulid_flux_nodes(wf: dict) -> dict[str, list[str]]:
    """查找所有 PuLID-Flux 相关节点，按类型分组

    Returns:
        {
            "apply": ["pulid_apply_xxx", ...],
            "model_loader": ["pulid_model_xxx", ...],
            "insightface": ["pulid_insightface_xxx", ...],
            "eva_clip": ["pulid_eva_clip_xxx", ...],
            "ref_images": ["pulid_ref_xxx", ...],
        }
    """
    result = {"apply": [], "model_loader": [], "insightface": [], "eva_clip": [], "ref_images": []}
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct == "ApplyPulidFlux":
            result["apply"].append(nid)
        elif ct == "PulidFluxModelLoader":
            result["model_loader"].append(nid)
        elif ct == "PulidFluxInsightFaceLoader" and nid.startswith("pulid_"):
            result["insightface"].append(nid)
        elif ct == "PulidFluxEvaClipLoader" and nid.startswith("pulid_"):
            result["eva_clip"].append(nid)
        elif ct == "LoadImage" and nid.startswith("pulid_ref"):
            result["ref_images"].append(nid)
    return result


def find_lora_nodes(wf: dict) -> list[tuple[str, str]]:
    """查找工作流中所有 LoRA 加载节点，返回 [(node_id, lora_name), ...]

    支持 LoraLoader 及常见的别名节点类型。
    """
    lora_types = {"LoraLoader", "LoraLoaderModelOnly", "CR Lora Loader"}
    result = []
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") in lora_types:
            lora_name = node.get("inputs", {}).get("lora_name", "")
            if lora_name:
                result.append((nid, lora_name))
    return result


def set_clip_text_prompts(wf: dict, positive: str, negative: str = "") -> dict:
    # 先找出所有被当作 negative 输入使用的 CLIPTextEncode 节点 ID
    negative_node_ids: set[str] = set()
    for nid, node in wf.items():
        # 检查 guider/sampler 节点的 negative 引用
        ct = node.get("class_type", "")
        inp = node.get("inputs", {})
        if ct in ("KSampler", "KSamplerAdvanced"):
            neg_ref = inp.get("negative", [])
            if isinstance(neg_ref, list) and len(neg_ref) >= 1:
                negative_node_ids.add(str(neg_ref[0]))
        if ct == "DualCFGGuider":
            neg_ref = inp.get("negative", [])
            if isinstance(neg_ref, list) and len(neg_ref) >= 1:
                negative_node_ids.add(str(neg_ref[0]))
            neg2_ref = inp.get("cfg_cond2_negative", [])
            if isinstance(neg2_ref, list) and len(neg2_ref) >= 1:
                negative_node_ids.add(str(neg2_ref[0]))

    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") == "CLIPTextEncode":
            if nid in negative_node_ids:
                node["inputs"]["text"] = negative
            else:
                node["inputs"]["text"] = positive
    return wf
