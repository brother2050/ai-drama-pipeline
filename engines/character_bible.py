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

        合并 bible + bible_en：en 覆盖 zh，未翻译字段回退中文。
        """
        zh = self.load(char_id)
        en = self.load_en(char_id)
        # 合并：中文打底，英文覆盖已翻译字段
        source = {**zh, **en} if en else zh
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
