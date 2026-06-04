"""Prompt 模板引擎 — Mustache 风格模板编译

- 模板和逻辑分离，非开发者也能调整 prompt 结构
- 支持 ${variable} 和 {{variable}} 两种语法
- 从 config/prompt_templates.yaml 加载模板
- 支持多语言模板（同一模板的中/英文版本）

用法:
    compiler = PromptCompiler()
    result = compiler.compile("first_frame_tag", {
        "style": "cinematic style",
        "genre": "urban atmosphere",
        "scene": "modern living room",
        "character": "a young woman with long hair",
        "action": "sitting on sofa",
        "emotion": "worried expression",
        "shot_type": "close-up shot",
        "camera": "slow zoom in",
    })
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from infra.constants import is_ascii_only

logger = logging.getLogger(__name__)

__all__ = ["PromptCompiler", "get_compiler"]

# 模板缓存
_compiler_lock = threading.Lock()
_compiler_instance: PromptCompiler | None = None


def get_compiler() -> PromptCompiler:
    """获取全局 PromptCompiler 单例（线程安全）"""
    global _compiler_instance
    if _compiler_instance is None:
        with _compiler_lock:
            if _compiler_instance is None:
                _compiler_instance = PromptCompiler()
    return _compiler_instance


def _build_first_frame_vars(style, genre, scene, character, action,
                            emotion, emotion_desc, shot_type, shot_type_desc,
                            camera, camera_desc) -> dict:
    """构建首帧 prompt 变量字典"""
    return {
        "style": f"{style} style" if style else "",
        "style_tag": f"{style} style" if style else "",
        "genre": f"{genre} atmosphere" if genre else "",
        "genre_tag": f"{genre} atmosphere" if genre else "",
        "scene": scene, "scene_desc": scene,
        "character": character, "character_desc": character,
        "action": action, "emotion": emotion, "emotion_desc": emotion_desc,
        "shot_type": shot_type, "shot_type_desc": shot_type_desc,
        "camera": camera, "camera_desc": camera_desc,
    }


class PromptCompiler:
    """Mustache 风格的 Prompt 模板编译器

    支持两种变量语法：
    - ${variable} — 从 prompt_templates.yaml 加载的模板使用
    - {{variable}} — 代码内嵌模板使用

    空值处理：变量值为空/None 时，整行或相关短语自动移除。
    """

    def __init__(self, templates_path: str | Path | None = None):
        """
        Args:
            templates_path: prompt_templates.yaml 路径（None 则自动查找）
        """
        if templates_path is None:
            templates_path = Path(__file__).resolve().parent.parent / "config" / "prompt_templates.yaml"
        self._path = Path(templates_path)
        self._templates: dict[str, str] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """从 YAML 文件加载模板"""
        if not self._path.exists():
            logger.warning(f"Prompt 模板文件不存在: {self._path}")
            return
        try:
            import yaml
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for key, val in data.items():
                if isinstance(val, dict) and "template" in val:
                    self._templates[key] = val["template"]
            logger.debug(f"加载 {len(self._templates)} 个 prompt 模板")
        except Exception as e:
            logger.warning(f"加载 prompt 模板失败: {e}")

    def get(self, template_id: str) -> str:
        """获取原始模板文本"""
        return self._templates.get(template_id, "")

    def list_templates(self) -> list[str]:
        """列出所有可用模板 ID"""
        return list(self._templates.keys())

    def compile(self, template_id: str, variables: dict[str, Any]) -> str:
        """编译模板（从模板 ID 加载 + 变量替换）

        Args:
            template_id: 模板 ID（如 "first_frame_tag"）
            variables: 变量字典 {"style": "cinematic style", ...}

        Returns:
            编译后的 prompt 文本
        """
        template = self._templates.get(template_id)
        if not template:
            logger.warning(f"模板 '{template_id}' 不存在，可用: {list(self._templates.keys())}")
            return ""
        return self.compile_text(template, variables)

    def compile_text(self, template: str, variables: dict[str, Any]) -> str:
        """编译模板文本（变量替换）

        支持 ${variable} 和 {{variable}} 两种语法。
        空值处理：替换为空字符串，然后清理产生的多余标点。

        Args:
            template: 模板文本
            variables: 变量字典

        Returns:
            编译后的文本
        """
        result = template

        # ${variable} 语法
        def _replace_dollar(m):
            key = m.group(1).strip()
            val = variables.get(key, "")
            return str(val) if val is not None else ""

        result = re.sub(r'\$\{(\w+)\}', _replace_dollar, result)

        # {{variable}} 语法
        def _replace_mustache(m):
            key = m.group(1).strip()
            val = variables.get(key, "")
            return str(val) if val is not None else ""

        result = re.sub(r'\{\{(\w+)\}\}', _replace_mustache, result)

        # 清理空值产生的多余标点
        result = self._clean_empty_values(result)

        # 清理多余空行
        result = re.sub(r'\n{3,}', '\n\n', result)

        return result.strip()

    def _clean_empty_values(self, text: str) -> str:
        """清理空值替换后产生的多余标点（循环直到无变化）"""
        prev = None
        while prev != text:
            prev = text
            # ", ," → ","
            text = re.sub(r',\s*,', ',', text)
            # "  " → " "
            text = re.sub(r'  +', ' ', text)
            # 行首/行尾的逗号和空格
            text = re.sub(r'^\s*[,.\s]+', '', text, flags=re.MULTILINE)
            text = re.sub(r'[,.\s]+\s*$', '', text, flags=re.MULTILINE)
            # ", ." → "."
            text = re.sub(r',\s*\.', '.', text)
            # ". ," → "."
            text = re.sub(r'\.\s*,', '.', text)
        return text

    # ══════════════════════════════════════════════════════════
    #  预定义编译方法（常用 prompt 的快捷入口）
    # ══════════════════════════════════════════════════════════

    def compile_first_frame(
        self,
        shot: dict,
        character_desc: str = "",
        scene_desc: str = "",
        style: str = "",
        genre: str = "",
        prompt_style: str = "tag",
        character_bible: str = "",
    ) -> str:
        """编译首帧生成 prompt"""
        from infra.constants import EMOTION_MAP, SHOT_TYPE_MAP, CAMERA_MAP

        full_character = character_desc
        if character_bible and character_desc:
            full_character = f"{character_desc} ({character_bible})"
        elif character_bible:
            full_character = character_bible

        action = shot.get("action_en", "").strip()
        if not action:
            action = shot.get("action", "")
            if action:
                from engines.shot_utils import strip_dialogue
                action = strip_dialogue(action)

        emotion = shot.get("emotion", "neutral")
        shot_type = shot.get("shot_type", "中景")
        camera = shot.get("camera", "固定")
        variables = _build_first_frame_vars(
            style, genre, scene_desc, full_character, action,
            emotion, EMOTION_MAP.get(emotion, EMOTION_MAP.get("neutral", "")),
            shot_type, SHOT_TYPE_MAP.get(shot_type, "medium shot"),
            camera, CAMERA_MAP.get(camera, "static camera"))

        if prompt_style == "natural":
            return self._compile_natural(variables)
        return self._compile_tag(variables)

    def _compile_tag(self, variables: dict) -> str:
        """编译 tag 风格 prompt（SD1.5/SDXL）"""
        # 尝试从模板编译
        template = self._templates.get("first_frame_tag")
        if template:
            result = self.compile_text(template, variables)
            if result:
                return self._clean_tag_prompt(result)

        # 回退：硬编码逻辑
        parts = []
        for key in ("style_tag", "genre_tag", "scene", "character", "action"):
            val = variables.get(key, "")
            if val:
                parts.append(val)
        parts.append(variables.get("emotion_desc", "neutral expression"))
        parts.append(variables.get("shot_type_desc", "medium shot"))
        parts.append(variables.get("camera_desc", "static camera"))
        return ", ".join(parts)

    def _compile_natural(self, variables: dict) -> str:
        """编译自然语言风格 prompt（Flux/Cosmos）"""
        # 尝试从模板编译
        template = self._templates.get("first_frame_natural")
        if template:
            result = self.compile_text(template, variables)
            if result:
                return result

        # 回退：硬编码逻辑
        sentences = []

        # 第一句：风格 + 场景
        style = variables.get("style_tag", "")
        genre = variables.get("genre_tag", "")
        scene = variables.get("scene", "")
        parts_1 = []
        if style and genre:
            parts_1.append(f"A {style} in {genre}")
        elif style:
            parts_1.append(f"A {style}")
        if scene:
            parts_1.append(f"Set in {scene}")
        if parts_1:
            sentences.append(". ".join(parts_1) + ".")

        # 第二句：角色 + 动作 + 情绪
        character = variables.get("character", "")
        action = variables.get("action", "")
        emotion = variables.get("emotion", "neutral")
        action_ok = action and is_ascii_only(action)
        parts_2 = []
        if character:
            parts_2.append(character[0].upper() + character[1:] if character else "")
        if action_ok:
            if parts_2:
                parts_2[0] += f" {action}"
            else:
                parts_2.append(action[0].upper() + action[1:] if action else "")
        if emotion and emotion != "neutral":
            if parts_2:
                if action_ok:
                    parts_2[0] += f", with a {emotion} expression"
                else:
                    parts_2[0] += f" has a {emotion} expression"
            else:
                parts_2.append(f"With a {emotion} expression")
        if parts_2:
            sentences.append(parts_2[0] + ".")

        # 第三句：镜头语言
        shot_type = variables.get("shot_type_desc", "medium shot")
        camera = variables.get("camera_desc", "static camera")
        camera_parts = [shot_type]
        if camera and camera != "static camera":
            camera_parts.append(camera)
        sentences.append(", ".join(camera_parts) + ".")

        return " ".join(sentences)

    def _clean_tag_prompt(self, prompt: str) -> str:
        """清理 tag 风格 prompt（移除空值产生的多余逗号/空格）"""
        # 移除连续逗号
        prompt = re.sub(r',\s*,', ',', prompt)
        # 移除首尾逗号和空格
        prompt = prompt.strip(', ')
        # 移除多余空格
        prompt = re.sub(r'\s+', ' ', prompt)
        # 再次清理连续逗号（首尾清理后可能暴露新的）
        prompt = re.sub(r',\s*,', ',', prompt)
        prompt = prompt.strip(', ')
        return prompt
