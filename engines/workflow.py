"""ComfyUI 工作流工具函数 — 节点查找、参数注入"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    "find_character_load_image_nodes", "find_lora_nodes",
    "set_clip_text_prompts", "resolve_node_aliases",
    "resolve_model_source",
]


def resolve_model_source(wf: dict, ksampler: str) -> str | None:
    """追踪 KSampler.model 的实际来源节点 ID。

    KSampler.model 可能已被 LoRA 等中间节点改写，直接找 UNETLoader
    会绕过 LoRA。本函数沿当前连线回溯，返回真正连接到 KSampler 的节点。

    Args:
        wf: ComfyUI 工作流 dict
        ksampler: KSampler 节点 ID

    Returns:
        模型来源节点 ID（如 lora_xxx 或 UNETLoader），找不到返回兜底值
    """
    model_ref = wf.get(ksampler, {}).get("inputs", {}).get("model")
    if isinstance(model_ref, list) and len(model_ref) == 2:
        return model_ref[0]
    return (find_first_node(wf, "UNETLoader")
            or find_first_node(wf, "CheckpointLoaderSimple"))


def resolve_node_aliases(workflow: dict, available_nodes: set[str]) -> dict:
    if not available_nodes:
        return workflow
    aliases = workflow.get("_node_aliases", {})
    workflow.pop("_node_aliases", None)
    for nid, node in list(workflow.items()):
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
    # 收集 negative 和 positive 引用的 CLIPTextEncode 节点 ID
    negative_node_ids: set[str] = set()
    positive_node_ids: set[str] = set()
    for nid, node in wf.items():
        ct = node.get("class_type", "")
        inp = node.get("inputs", {})
        if ct in ("KSampler", "KSamplerAdvanced"):
            neg_ref = inp.get("negative", [])
            if isinstance(neg_ref, list) and len(neg_ref) >= 1:
                negative_node_ids.add(str(neg_ref[0]))
            pos_ref = inp.get("positive", [])
            if isinstance(pos_ref, list) and len(pos_ref) >= 1:
                positive_node_ids.add(str(pos_ref[0]))
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
            elif nid in positive_node_ids:
                node["inputs"]["text"] = positive
            # 未被 KSampler 引用的 CLIPTextEncode 不修改（避免覆盖第三方节点）
    return wf
