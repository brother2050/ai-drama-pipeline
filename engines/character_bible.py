"""角色圣经系统 — 跨镜头/跨集的角色一致性保障

bible 拆分为两个独立区域：
  - bible:    中文原始数据（用户/AI 生成）
  - bible_en: 英文翻译 prompt（prepare 阶段 AI 翻译）

用法:
    bible = CharacterBible(project_dir)
    context = bible.get_context("linxia")   # 中文，注入 LLM prompt
    tags = bible.get_tags("linxia")         # 英文，注入 ComfyUI prompt
"""
from __future__ import annotations

import logging

from engines.prompt_compiler import get_compiler

logger = logging.getLogger(__name__)

__all__ = ["CharacterBible"]


def _append_simple(data: dict, key: str, label: str, parts: list[str]) -> None:
    val = data.get(key, "")
    if val:
        parts.append(f"{label}: {val}")


def _append_map(data: dict, key: str, label: str, fmt: str, parts: list[str]) -> None:
    items = data.get(key, {})
    if items:
        texts = [fmt.format(key=k, val=v) for k, v in items.items() if v]
        if texts:
            parts.append(f"{label}: " + "；".join(texts))


def _append_list(data: dict, key: str, label: str, parts: list[str]) -> None:
    items = data.get(key, [])
    if items:
        parts.append(f"{label}: " + "、".join(items))


class CharacterBible:
    """角色圣经管理器

    bible（中文）和 bible_en（英文）独立读取，
    分别用于 LLM prompt 和 ComfyUI prompt 注入。
    """

    def __init__(self, project_dir: str):
        self._project_dir = project_dir
        self._cache: dict[str, dict] = {}       # bible（中文）
        self._cache_en: dict[str, dict] = {}     # bible_en（英文）

    def get_context(self, char_id: str) -> str:
        """获取中文圣经上下文（注入 LLM prompt）"""
        bible = self.load(char_id)
        if not bible:
            return ""

        parts = []
        _append_simple(bible, "core_traits", "核心性格", parts)
        _append_simple(bible, "speech_patterns", "说话风格", parts)
        _append_map(bible, "relationships", "人际关系", "与{key}", parts)
        _append_map(bible, "emotional_range", "情绪表达", "{key}时{val}", parts)
        _append_map(bible, "body_language", "肢体语言", "{key}时{val}", parts)
        _append_list(bible, "habits", "习惯", parts)
        _append_list(bible, "taboos", "禁忌", parts)
        return "。".join(parts) + "。" if parts else ""

    def get_tags(self, char_id: str) -> str:
        """获取英文圣经 tag 摘要（逗号分隔，注入 ComfyUI prompt）

        优先读 bible_en（英文），回退到 bible（中文）。
        """
        en = self.load_en(char_id)
        zh = self.load(char_id)
        source = en if en else zh
        if not source:
            return ""

        tags: list[str] = []

        core = source.get("core_traits", "")
        if core:
            tags.append(core)

        speech = source.get("speech_patterns", "")
        if speech:
            tags.append(speech)

        rels = source.get("relationships", {})
        for rid, desc in rels.items():
            if desc:
                tags.append(desc)

        emo = source.get("emotional_range", {})
        for key in list(emo.keys())[:2]:
            desc = emo.get(key, "")
            if desc:
                tags.append(desc)

        body = source.get("body_language", {})
        for key in list(body.keys())[:1]:
            desc = body.get(key, "")
            if desc:
                tags.append(desc)

        return ", ".join(tags) if tags else ""

    def load(self, char_id: str) -> dict:
        """加载中文圣经数据，不存在返回空 dict"""
        if char_id in self._cache:
            return self._cache[char_id]

        from infra.config import load_character, ProjectPaths
        paths = ProjectPaths(self._project_dir)
        char = load_character(paths, char_id)
        bible = char.get("bible", {})
        self._cache[char_id] = bible
        return bible

    def load_en(self, char_id: str) -> dict:
        """加载英文圣经数据，不存在返回空 dict"""
        if char_id in self._cache_en:
            return self._cache_en[char_id]

        from infra.config import load_character, ProjectPaths
        paths = ProjectPaths(self._project_dir)
        char = load_character(paths, char_id)
        bible_en = char.get("bible_en", {})
        self._cache_en[char_id] = bible_en
        return bible_en

    def save(self, char_id: str, bible: dict) -> None:
        """保存中文圣经数据"""
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

    def save_en(self, char_id: str, bible_en: dict) -> None:
        """保存英文圣经翻译数据"""
        from infra.config import ProjectPaths, load_yaml_full, save_yaml
        paths = ProjectPaths(self._project_dir)
        char_file = paths.character_yaml(char_id)
        if not char_file.exists():
            logger.warning(f"角色文件不存在: {char_file}")
            return

        try:
            data = load_yaml_full(char_file)
            data.setdefault("character", {})["bible_en"] = bible_en
            save_yaml(char_file, data)
            self._cache_en[char_id] = bible_en
            logger.info(f"角色圣经翻译已保存: {char_id}")
        except Exception as e:
            logger.error(f"保存角色圣经翻译失败 {char_id}: {e}")

    def get_all(self) -> dict[str, dict]:
        """获取所有角色的中文圣经数据"""
        from infra.config import ProjectPaths, load_yaml_entities
        paths = ProjectPaths(self._project_dir)
        chars = load_yaml_entities(paths.characters_dir, "character")
        return {c["id"]: c.get("bible", {}) for c in chars if c.get("id")}


# ══════════════════════════════════════════════════════════
#  LLM 生成角色圣经（中文原始数据）
# ══════════════════════════════════════════════════════════

def generate_bible(llm, character: dict, outline: str = "", other_chars: list[dict] = None) -> dict:
    """用 LLM 生成角色圣经（中文原始数据，不含 _en 字段）

    Args:
        llm: LLM 后端实例
        character: 角色数据
        outline: 剧情大纲（用于推断人际关系）
        other_chars: 其他角色列表（用于推断人际关系）

    Returns:
        角色圣经 dict（纯中文）
    """
    from infra.json_parse import parse_llm_json

    system = get_compiler().get("bible_generation_system")

    parts = [f"角色名: {character.get('name', '?')}"]
    parts.append(f"外貌: {character.get('appearance', '')}")
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
        raw = llm.chat(prompt, system=system, max_tokens=1024)
        result = parse_llm_json(raw)
        if result and isinstance(result, dict):
            # 过滤掉可能混入的 _en 字段
            return {k: v for k, v in result.items() if not k.endswith("_en")}
    except Exception as e:
        logger.warning(f"角色圣经生成失败: {e}")

    return {}
