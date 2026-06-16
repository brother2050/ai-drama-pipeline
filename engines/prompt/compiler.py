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



logger = logging.getLogger(__name__)

__all__ = ["PromptCompiler", "get_compiler", "tpl"]

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


def tpl(key: str) -> str:
    """快捷获取模板文本（等价于 get_compiler().get(key)）"""
    return get_compiler().get(key)


def _build_first_frame_vars(style, genre, scene, character, action,
                            emotion, emotion_desc, shot_type, shot_type_desc,
                            camera, camera_desc) -> dict:
    """构建首帧 prompt 变量字典"""
    style_tag = f"{style} style" if style else ""
    genre_tag = f"{genre} atmosphere" if genre else ""
    return {
        "style": style_tag, "style_tag": style_tag,
        "genre": genre_tag, "genre_tag": genre_tag,
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
            from infra.config.core import PROMPT_TEMPLATES_PATH
            templates_path = PROMPT_TEMPLATES_PATH
        self._path = Path(templates_path)
        self._templates: dict[str, str] = {}
        self._mtime: float = 0.0
        self._load_templates()

    def _check_reload(self) -> None:
        """检测模板文件变化，自动重载"""
        try:
            mtime = self._path.stat().st_mtime
            if mtime != self._mtime:
                self._load_templates()
        except OSError:
            pass

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
            self._mtime = self._path.stat().st_mtime
            logger.debug(f"加载 {len(self._templates)} 个 prompt 模板")
        except Exception as e:
            logger.warning(f"加载 prompt 模板失败: {e}")

    def get(self, template_id: str) -> str:
        """获取原始模板文本（文件变化时自动重载）"""
        self._check_reload()
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

        # 变量替换（${variable} 和 {{variable}} 语法共用）
        def _replace_var(m):
            key = m.group(1).strip()
            val = variables.get(key, "")
            return str(val) if val is not None else ""

        result = re.sub(r'\$\{(\w+)\}', _replace_var, result)
        result = re.sub(r'\{\{(\w+)\}\}', _replace_var, result)

        # 清理空值产生的多余标点
        result = self._clean_empty_values(result)

        # 清理多余空行
        result = re.sub(r'\n{3,}', '\n\n', result)

        # 检测未替换的模板变量
        residual = re.findall(r'\$\{(\w+)\}|\{\{(\w+)\}\}', result)
        if residual:
            keys = [m[0] or m[1] for m in residual]
            logger.warning(f"模板变量未替换: {keys}")

        return result.strip()

    def _clean_empty_values(self, text: str) -> str:
        """清理空值替换后产生的多余标点（最多 3 轮收敛）

        对话占位符 "......" 是项目中的标准无台词标记，必须保留。
        先保护连续 3+ 点号，清理完再恢复。
        """
        # 保护对话占位符（3+ 连续点号，可能含空格如 ". . ."）
        _ELLIPSIS_PLACEHOLDER = "\x00ELLIPSIS\x00"
        text = re.sub(r'\.{3,}', _ELLIPSIS_PLACEHOLDER, text)
        text = re.sub(r'(?:\.\s){2,}\.', _ELLIPSIS_PLACEHOLDER, text)

        for _ in range(3):
            old = text
            text = re.sub(r',\s*,', ',', text)          # ", ," → ","
            text = re.sub(r'  +', ' ', text)            # "  " → " "
            text = re.sub(r'\.\s*\.', '.', text)         # ". ." → "."
            text = re.sub(r'^\s*[,.\s]+', '', text, flags=re.MULTILINE)
            text = re.sub(r'[,.\s]+\s*$', '', text, flags=re.MULTILINE)
            text = re.sub(r',\s*\.', '.', text)         # ", ." → "."
            text = re.sub(r'\.\s*,', '.', text)         # ". ," → "."
            if text == old:
                break

        # 恢复对话占位符
        text = text.replace(_ELLIPSIS_PLACEHOLDER, "......")
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
        scene_data: dict | None = None,
    ) -> str:
        """编译首帧生成 prompt"""
        from infra.constants import EMOTION_MAP, SHOT_TYPE_MAP, CAMERA_MAP

        full_character = character_desc
        if character_bible and character_desc:
            full_character = f"{character_desc} ({character_bible})"
        elif character_bible:
            full_character = character_bible

        # ── 注入场景光照 ──
        if scene_data:
            lighting_en = scene_data.get("lighting_en", "") or scene_data.get("lighting", "")
            if lighting_en and scene_desc:
                scene_desc = f"{scene_desc}, {lighting_en}"

        action = shot.get("action_en", "").strip()
        if not action:
            action = shot.get("action", "")
            if action:
                from engines.utils.shot import strip_dialogue
                action = strip_dialogue(action)

        emotion = shot.get("emotion", "neutral")
        shot_type = shot.get("shot_type", "中景")
        camera = shot.get("camera", "固定")
        # 无角色时清空 emotion/action — 避免 "neutral expression" 诱导生成人脸
        if not full_character:
            emotion = ""
            emotion_desc = ""
            action = ""
        else:
            # ── 优先使用角色专属情绪描述 ──
            char_emotional_range = shot.get("_char_emotional_range", {})
            emotion_desc = char_emotional_range.get(emotion, "") or EMOTION_MAP.get(emotion, EMOTION_MAP.get("neutral", ""))

            # ── 注入角色专属肢体语言到 action ──
            char_body_language = shot.get("_char_body_language", {})
            body_lang = char_body_language.get(emotion, "")
            if body_lang and action:
                action = f"{action}, {body_lang}"

        variables = _build_first_frame_vars(
            style, genre, scene_desc, full_character, action,
            emotion, emotion_desc,
            shot_type, SHOT_TYPE_MAP.get(shot_type, "medium shot"),
            camera, CAMERA_MAP.get(camera, "static camera"))

        if prompt_style == "natural":
            return self._compile_natural(variables)
        return self._compile_tag(variables)

    @staticmethod
    def _strip_character_sentence(text: str) -> str:
        """移除模板中角色/情绪相关残留（无角色镜头兜底清理）

        模板 literal "with a ${emotion} expression" 在 emotion 为空时
        变成 "with a expression"，此方法移除这类残留。
        """
        # 移除 "with a/an ... expression" 模式
        text = re.sub(r'\.\s*with an?\s+[\w\s]*expression\s*\.', '.', text)
        text = re.sub(r'\s*with an?\s+[\w\s]*expression\.?\s*', ' ', text)
        # 清理多余标点
        text = re.sub(r'\.\s*\.', '.', text)
        text = re.sub(r'  +', ' ', text)
        text = re.sub(r'\.\s*,', '.', text)
        text = re.sub(r',\s*\.', '.', text)
        text = re.sub(r'^\s*[,.\s]+', '', text)
        return text.strip()

    def _compile_tag(self, variables: dict) -> str:
        """编译 tag 风格 prompt（SD1.5/SDXL）"""
        template = self._templates.get("first_frame_tag")
        if not template:
            logger.error("first_frame_tag 模板缺失，请检查 config/prompt_templates.yaml")
            return ""
        result = self.compile_text(template, variables)
        return self._clean_tag_prompt(result) if result else ""

    def _compile_natural(self, variables: dict) -> str:
        """编译自然语言风格 prompt（Flux/Cosmos）"""
        template = self._templates.get("first_frame_natural")
        if not template:
            logger.error("first_frame_natural 模板缺失，请检查 config/prompt_templates.yaml")
            return ""
        result = self.compile_text(template, variables)
        if result and not variables.get("character"):
            result = self._strip_character_sentence(result)
        return result or ""

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
