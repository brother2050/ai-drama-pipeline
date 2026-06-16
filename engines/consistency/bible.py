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
    缓存带 mtime 检查，YAML 文件修改后自动重载。
    """

    def __init__(self, project_dir: str):
        from infra.config import ProjectPaths
        self._paths = ProjectPaths(project_dir)
        self._cache: dict[str, dict] = {}       # bible（中文）
        self._cache_en: dict[str, dict] = {}     # bible_en（英文）
        self._mtimes: dict[str, float] = {}      # 文件 mtime 缓存

    def _is_fresh(self, char_id: str) -> bool:
        """检查缓存是否仍然有效（文件未修改）"""
        char_file = self._paths.character_yaml(char_id)
        if not char_file.exists():
            return char_id in self._cache  # 文件不存在时，缓存空 dict 也是有效的
        try:
            mtime = char_file.stat().st_mtime
            return self._mtimes.get(char_id) == mtime
        except OSError:
            return False

    def _update_mtime(self, char_id: str) -> None:
        """更新缓存的 mtime"""
        char_file = self._paths.character_yaml(char_id)
        try:
            self._mtimes[char_id] = char_file.stat().st_mtime
        except OSError:
            self._mtimes.pop(char_id, None)

    def get_context(self, char_id: str) -> str:
        """获取中文圣经上下文（注入 LLM prompt）"""
        bible = self.load(char_id)
        if not bible:
            return ""

        parts = []
        _append_simple(bible, "core_traits", "核心性格", parts)
        _append_simple(bible, "speech_patterns", "说话风格", parts)
        _append_map(bible, "emotional_range", "情绪表达", "{key}时{val}", parts)
        _append_map(bible, "body_language", "肢体语言", "{key}时{val}", parts)
        _append_list(bible, "habits", "习惯", parts)
        _append_list(bible, "taboos", "禁忌", parts)
        return "。".join(parts) + "。" if parts else ""

    def get_tags(self, char_id: str) -> str:
        """获取英文圣经 tag 摘要（逗号分隔，注入 ComfyUI prompt）

        直接读取 bible_en（_en 后缀 key），不做中英文合并。
        """
        en = self.load_en(char_id)
        if not en:
            return ""

        tags: list[str] = []

        def _add(val: str) -> None:
            v = (val or "").strip()
            if v:
                tags.append(v)

        _add(en.get("core_traits_en", ""))
        _add(en.get("speech_patterns_en", ""))

        emo = en.get("emotional_range_en", {})
        for key in list(emo.keys())[:2]:
            _add(emo.get(key, ""))

        body = en.get("body_language_en", {})
        for key in list(body.keys())[:1]:
            _add(body.get(key, ""))

        return ", ".join(tags) if tags else ""

    def load(self, char_id: str) -> dict:
        """加载中文圣经数据，不存在返回空 dict。文件修改后自动重载。"""
        if char_id in self._cache and self._is_fresh(char_id):
            return self._cache[char_id]

        from infra.config import load_character
        char = load_character(self._paths, char_id)
        bible = char.get("bible", {})
        self._cache[char_id] = bible
        self._update_mtime(char_id)
        return bible

    def load_en(self, char_id: str) -> dict:
        """加载英文圣经数据，不存在返回空 dict。文件修改后自动重载。"""
        if char_id in self._cache_en and self._is_fresh(char_id):
            return self._cache_en[char_id]

        from infra.config import load_character
        char = load_character(self._paths, char_id)
        bible_en = char.get("bible_en", {})
        self._cache_en[char_id] = bible_en
        self._update_mtime(char_id)
        return bible_en

    def save(self, char_id: str, bible: dict) -> None:
        """保存中文圣经数据"""
        self._save_bible(char_id, "bible", bible, self._cache)

    def save_en(self, char_id: str, bible_en: dict) -> None:
        """保存英文圣经翻译数据"""
        self._save_bible(char_id, "bible_en", bible_en, self._cache_en)

    def _save_bible(self, char_id: str, key: str, data: dict, cache: dict) -> None:
        """通用圣经保存（消除 save/save_en 重复）"""
        from infra.config import load_yaml_full, save_yaml
        char_file = self._paths.character_yaml(char_id)
        if not char_file.exists():
            logger.warning(f"角色文件不存在: {char_file}")
            return
        try:
            file_data = load_yaml_full(char_file)
            file_data.setdefault("character", {})[key] = data
            save_yaml(char_file, file_data)
            cache[char_id] = data
            self._update_mtime(char_id)
            logger.info(f"角色圣经已保存: {char_id} ({key})")
        except Exception as e:
            logger.error(f"保存角色圣经失败 {char_id} ({key}): {e}")

    def get_all(self) -> dict[str, dict]:
        """获取所有角色的中文圣经数据"""
        from infra.config import load_yaml_entities
        chars = load_yaml_entities(self._paths.characters_dir, "character")
        return {c["id"]: c.get("bible", {}) for c in chars if c.get("id")}
