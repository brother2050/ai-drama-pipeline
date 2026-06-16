"""共享工具包

从 shot_utils.py, entity_utils.py, multi_char.py 整合而来。
"""
from engines.utils.shot import parse_char_names, strip_dialogue, postprocess_shots
from engines.utils.entity import generate_and_save, save_entities, build_entity_descriptions
from engines.utils.multi_char import MultiCharacterHandler

__all__ = [
    "parse_char_names", "strip_dialogue", "postprocess_shots",
    "generate_and_save", "save_entities", "build_entity_descriptions",
    "MultiCharacterHandler",
]
