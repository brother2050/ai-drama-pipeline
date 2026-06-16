"""ComfyUI 工作流管理包

从 workflow_builder.py, workflow_inject.py, workflow.py 整合而来。
"""
from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
from engines.workflow.inject import (
    inject_character_refs, inject_ip_adapter_plus, inject_ip_adapter_chain,
    inject_pulid_flux, inject_pulid_flux_chain,
    inject_controlnet_depth,
    find_character_lora, find_style_lora, inject_lora,
)
from engines.workflow.node_graph import NodeGraphInjector, inject_from_registry
from engines.workflow.utils import (
    find_first_node, find_nodes_by_class, find_load_image_nodes,
    find_character_load_image_nodes, set_clip_text_prompts,
    resolve_node_aliases, resolve_model_source, append_negative_prompt,
)
from engines.workflow.video import build_video
from engines.workflow.upload import build_upload_map, group_ipa_ref_nodes

__all__ = [
    "WorkflowBuilder", "WorkflowBuilderConfig",
    "NodeGraphInjector", "inject_from_registry",
    "inject_character_refs", "inject_ip_adapter_plus", "inject_ip_adapter_chain",
    "inject_pulid_flux", "inject_pulid_flux_chain",
    "inject_controlnet_depth",
    "find_character_lora", "find_style_lora", "inject_lora",
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    "find_character_load_image_nodes", "set_clip_text_prompts",
    "resolve_node_aliases", "resolve_model_source", "append_negative_prompt",
    "build_video", "build_upload_map", "group_ipa_ref_nodes",
]
