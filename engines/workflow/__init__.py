"""ComfyUI 工作流管理包

从 workflow_builder.py, workflow_inject.py, workflow.py 整合而来。
"""
from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
from engines.workflow.differ import WorkflowDiffer
from engines.workflow.graph import Node, NodeRef, WorkflowGraph
from engines.workflow.inject import (
    find_character_lora,
    find_style_lora,
    inject_character_refs,
    inject_controlnet_depth,
    inject_ip_adapter_chain,
    inject_ip_adapter_plus,
    inject_lora,
    inject_pulid_flux,
    inject_pulid_flux_chain,
)
from engines.workflow.node_graph import NodeGraphInjector, inject_from_registry
from engines.workflow.node_types import (
    ALL_CLIP_LOADERS,
    ALL_LORA_LOADERS,
    ALL_MODEL_LOADERS,
    ALL_SAMPLERS,
    get_negative_field,
    get_positive_field,
    get_seed_field,
)
from engines.workflow.upload import build_upload_map, group_ipa_ref_nodes
from engines.workflow.utils import (
    append_negative_prompt,
    find_character_load_image_nodes,
    find_first_node,
    find_load_image_nodes,
    find_nodes_by_class,
    resolve_model_source,
    resolve_node_aliases,
    set_clip_text_prompts,
)
from engines.workflow.validator import ValidationError, WorkflowValidator
from engines.workflow.video import build_video
from engines.workflow.preflight import WorkflowPreflightChecker, PreflightResult
from engines.workflow.schema_cache import ComfyUISchemaCache, NodeSchema, InputDef

__all__ = [
    "ALL_CLIP_LOADERS",
    "ALL_LORA_LOADERS",
    "ALL_MODEL_LOADERS",
    "ALL_SAMPLERS",
    "Node",
    "NodeGraphInjector",
    "NodeRef",
    "ValidationError",
    "WorkflowBuilder",
    "WorkflowBuilderConfig",
    "WorkflowDiffer",
    "WorkflowGraph",
    "WorkflowValidator",
    "append_negative_prompt",
    "build_upload_map",
    "build_video",
    "find_character_load_image_nodes",
    "find_character_lora",
    "find_first_node",
    "find_load_image_nodes",
    "find_nodes_by_class",
    "find_style_lora",
    "get_negative_field",
    "get_positive_field",
    "get_seed_field",
    "group_ipa_ref_nodes",
    "inject_character_refs",
    "inject_controlnet_depth",
    "inject_from_registry",
    "inject_ip_adapter_chain",
    "inject_ip_adapter_plus",
    "inject_lora",
    "inject_pulid_flux",
    "inject_pulid_flux_chain",
    "resolve_model_source",
    "resolve_node_aliases",
    "set_clip_text_prompts",
    "WorkflowPreflightChecker",
    "PreflightResult",
    "ComfyUISchemaCache",
    "NodeSchema",
    "InputDef",
]
