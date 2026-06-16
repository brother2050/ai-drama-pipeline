"""内容生成包

从 portrait.py, llm.py, storyboard.py, episode.py, validator.py, generator.py 整合而来。
"""
from engines.content.portrait import ensure_portrait, ViewGenParams
from engines.content.llm import StoryboardGenParams, generate_storyboard
from engines.content.storyboard import (
    load_storyboard, save_storyboard, append_storyboard,
    get_episode_list, validate_shot,
)
from engines.content.episode import get_episode_status
from engines.content.validator import validate_character, validate_scene, check_entity_completeness
from engines.content.generator import generate_characters, generate_scenes

__all__ = [
    "ensure_portrait", "ViewGenParams",
    "StoryboardGenParams", "generate_storyboard",
    "load_storyboard", "save_storyboard", "append_storyboard",
    "get_episode_list", "validate_shot",
    "get_episode_status",
    "validate_character", "validate_scene", "check_entity_completeness",
    "generate_characters", "generate_scenes",
]
