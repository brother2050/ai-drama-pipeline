"""角色圣经系统 — 跨镜头/跨集的角色一致性保障

为每个角色建立结构化的"圣经"，确保行为/台词/情绪在不同镜头中保持一致。

用法:
    bible = CharacterBible(project_dir)
    context = bible.get_context("linxia")
    # → "核心性格: 温柔但坚强。说话风格: 语速较慢，常用'嗯...'开头。..."
"""
from __future__ import annotations

import logging

from engines.prompt_compiler import get_compiler

logger = logging.getLogger(__name__)

__all__ = ["CharacterBible"]


def _append_simple(bible: dict, key: str, label: str, parts: list[str]) -> None:
    val = bible.get(key, "")
    if val:
        parts.append(f"{label}: {val}")


def _append_map(bible: dict, key: str, label: str, fmt: str, parts: list[str]) -> None:
    data = bible.get(key, {})
    if data:
        items = [fmt.format(key=k, val=v) for k, v in data.items() if v]
        if items:
            parts.append(f"{label}: " + "；".join(items))


class CharacterBible:
    """角色圣经管理器

    从角色 YAML 的 bible 段读取结构化角色信息，
    生成可注入 LLM prompt 的上下文文本。
    """

    def __init__(self, project_dir: str):
        self._project_dir = project_dir
        self._cache: dict[str, dict] = {}

    def get_context(self, char_id: str) -> str:
        """获取角色圣经上下文（可注入 LLM prompt）"""
        bible = self.load(char_id)
        if not bible:
            return ""

        parts = []
        _append_simple(bible, "core_traits", "核心性格", parts)
        _append_simple(bible, "speech_patterns", "说话风格", parts)
        _append_map(bible, "relationships", "人际关系", "与{key}", parts)
        _append_map(bible, "emotional_range", "情绪表达", "{key}时{val}", parts)
        _append_map(bible, "body_language", "肢体语言", "{key}时{val}", parts)
        return "。".join(parts) + "。" if parts else ""

    def load(self, char_id: str) -> dict:
        """加载角色圣经数据

        Returns:
            bible 段 dict，不存在返回空 dict
        """
        if char_id in self._cache:
            return self._cache[char_id]

        from infra.config import load_character, ProjectPaths
        paths = ProjectPaths(self._project_dir)
        char = load_character(paths, char_id)
        bible = char.get("bible", {})
        self._cache[char_id] = bible
        return bible

    def save(self, char_id: str, bible: dict) -> None:
        """保存角色圣经数据

        Args:
            char_id: 角色 ID
            bible: 角色圣经数据
        """
        from infra.config import ProjectPaths, load_yaml_full, save_yaml
        paths = ProjectPaths(self._project_dir)
        char_file = paths.character_yaml(char_id)
        if not char_file.exists():
            logger.warning(f"角色文件不存在: {char_file}")
            return

        try:
            data = load_yaml_full(char_file)
            data.setdefault("character", {})["bible"] = bible
            save_yaml(char_file, data)
            self._cache[char_id] = bible
            logger.info(f"角色圣经已保存: {char_id}")
        except Exception as e:
            logger.error(f"保存角色圣经失败 {char_id}: {e}")

    def get_tags(self, char_id: str) -> str:
        """获取角色圣经的 tag 风格摘要（英文逗号分隔，适配 SD1.5 CLIP）

        优先读 _en 字段（英文短标签），回退到中文字段。
        """
        bible = self.load(char_id)
        if not bible:
            return ""

        tags: list[str] = []

        # 核心性格
        core = bible.get("core_traits_en") or bible.get("core_traits", "")
        if core:
            tags.append(core)

        # 说话风格
        speech = bible.get("speech_patterns_en") or bible.get("speech_patterns", "")
        if speech:
            tags.append(speech)

        # 人际关系
        rels_en = bible.get("relationships_en", {})
        rels = bible.get("relationships", {})
        for rid in set(list(rels_en.keys()) + list(rels.keys())):
            desc = rels_en.get(rid) or rels.get(rid, "")
            if desc:
                tags.append(desc)

        # 情绪表达（取 1-2 个典型）
        emo_en = bible.get("emotional_range_en", {})
        emo = bible.get("emotional_range", {})
        for key in list(emo_en.keys())[:2] or list(emo.keys())[:2]:
            desc = emo_en.get(key) or emo.get(key, "")
            if desc:
                tags.append(desc)

        # 肢体语言（取 1 个典型）
        body_en = bible.get("body_language_en", {})
        body = bible.get("body_language", {})
        for key in list(body_en.keys())[:1] or list(body.keys())[:1]:
            desc = body_en.get(key) or body.get(key, "")
            if desc:
                tags.append(desc)

        return ", ".join(tags) if tags else ""

    def get_all(self) -> dict[str, dict]:
        """获取所有角色的圣经数据

        Returns:
            {char_id: bible_dict} 映射
        """
        from infra.config import ProjectPaths, load_yaml_entities
        paths = ProjectPaths(self._project_dir)
        chars = load_yaml_entities(paths.characters_dir, "character")

        result = {}
        for char in chars:
            cid = char.get("id", "")
            if cid:
                result[cid] = char.get("bible", {})
        return result


# ══════════════════════════════════════════════════════════
#  LLM 生成角色圣经
# ══════════════════════════════════════════════════════════

BIBLE_GENERATION_SYSTEM = get_compiler().get("bible_generation_system")


def generate_bible(llm, character: dict, outline: str = "", other_chars: list[dict] = None) -> dict:
    """用 LLM 生成角色圣经

    Args:
        llm: LLM 后端实例
        character: 角色数据
        outline: 剧情大纲（用于推断人际关系）
        other_chars: 其他角色列表（用于推断人际关系）

    Returns:
        角色圣经 dict
    """
    from infra.json_parse import parse_llm_json

    parts = [f"角色名: {character.get('name', '?')}"]
    parts.append(f"外貌: {character.get('appearance', '')}")
    # 优先读 bible 已有的 core_traits
    existing_traits = ""
    bible_section = character.get("bible", {})
    if isinstance(bible_section, dict):
        existing_traits = bible_section.get("core_traits", "")
    parts.append(f"性格: {existing_traits}")

    if other_chars:
        others = [f"{c.get('id', '?')}({c.get('name', '?')})" for c in other_chars if c.get('id') != character.get('id')]
        if others:
            parts.append(f"其他角色: {', '.join(others)}")

    if outline:
        parts.append(f"剧情大纲: {outline[:500]}")

    prompt = "\n".join(parts)

    try:
        raw = llm.chat(prompt, system=BIBLE_GENERATION_SYSTEM, max_tokens=1024)
        result = parse_llm_json(raw)
        if result and isinstance(result, dict):
            return result
    except Exception as e:
        logger.warning(f"角色圣经生成失败: {e}")

    return {}
