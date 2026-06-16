"""引擎层 — 核心功能模块

模块结构:
- engines/workflow/: ComfyUI 工作流管理
- engines/prompt/: Prompt 工程
- engines/content/: 内容生成（定妆照、LLM、分镜）
- engines/consistency/: 角色一致性（检查、圣经）
- engines/utils/: 共享工具（镜头、实体、多角色）
"""
from engines.workflow import (
    WorkflowBuilder, WorkflowBuilderConfig,
    inject_character_refs, inject_ip_adapter_plus, inject_ip_adapter_chain,
    inject_pulid_flux, inject_pulid_flux_chain,
    inject_controlnet_depth,
    find_character_lora, find_style_lora, inject_lora,
    find_first_node, find_nodes_by_class, find_load_image_nodes,
)
from engines.prompt import (
    PromptBuildParams, batch_generate_appearance_prompts, build_prompt,
    translate_to_english, batch_translate_to_english,
    get_view_appearance, build_view_prompt,
)
from engines.content import (
    ensure_portrait, ViewGenParams,
    StoryboardGenParams, generate_storyboard,
)
from engines.consistency import (
    ConsistencyChecker, check_consistency,
    CharacterBible,
)
from engines.utils import (
    parse_char_names, strip_dialogue, postprocess_shots,
    generate_and_save, save_entities, build_entity_descriptions,
    MultiCharacterHandler,
)

__all__ = [
    # workflow
    "WorkflowBuilder", "WorkflowBuilderConfig",
    "inject_character_refs", "inject_ip_adapter_plus", "inject_ip_adapter_chain",
    "inject_pulid_flux", "inject_pulid_flux_chain",
    "inject_controlnet_depth",
    "find_character_lora", "find_style_lora", "inject_lora",
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    # prompt
    "PromptBuildParams", "batch_generate_appearance_prompts", "build_prompt",
    "translate_to_english", "batch_translate_to_english",
    "get_view_appearance", "build_view_prompt",
    # content
    "ensure_portrait", "ViewGenParams",
    "StoryboardGenParams", "generate_storyboard",
    # consistency
    "ConsistencyChecker", "check_consistency",
    "CharacterBible",
    # utils
    "parse_char_names", "strip_dialogue", "postprocess_shots",
    "generate_and_save", "save_entities", "build_entity_descriptions",
    "MultiCharacterHandler",
]
