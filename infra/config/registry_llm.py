"""模型注册表扩展 — LLM 模型限制查询 + 错误驱动学习

从 registry.py 中提取 LLM 相关查询方法，通过 Mixin 方式保持 ModelRegistry 统一入口。
"""
from __future__ import annotations

import re
from typing import Any


class LLMRegistryMixin:
    """LLM 模型限制查询 + 运行时错误学习"""

    # 由 ModelRegistry 注入
    _data: dict[str, Any]
    _discovered_limits: dict[str, dict[str, int]]  # 类变量

    # ══════════════════════════════════════════════════════════
    #  LLM 模型限制查询
    # ══════════════════════════════════════════════════════════
    def is_thinking_model(self, model_name: str = "") -> bool:
        thinking_models = tuple(self._data.get("models_thinking", ()))
        return model_name.startswith(thinking_models)

    def get_model_limits(self, model_name: str) -> dict[str, int]:
        m = model_name.lower()
        if m in self._discovered_limits:
            discovered = self._discovered_limits[m]
            static = self._lookup_static_limits(model_name)
            return {
                "context_window": discovered.get("context_window", static["context_window"]),
                "max_output": discovered.get("max_output", static["max_output"]),
            }
        return self._lookup_static_limits(model_name)

    def _lookup_static_limits(self, model_name: str) -> dict[str, int]:
        models = self._data.get("llm_models", {})
        if not models:
            return {"context_window": 8192, "max_output": 4096}

        def _extract(entry: dict[str, Any]) -> dict[str, int]:
            result: dict[str, int] = {
                "context_window": int(entry.get("context_window", 8192)),
                "max_output": int(entry.get("max_output", 4096)),
            }
            if "max_items_per_batch" in entry:
                result["max_items_per_batch"] = int(entry["max_items_per_batch"])
            return result

        m = model_name
        if m in models:
            return _extract(models[m])

        m_lower = m.lower()
        sorted_keys = sorted((k for k in models if k != "_default"), key=len, reverse=True)

        # 1. 完整名称前缀匹配
        for key in sorted_keys:
            if m_lower.startswith(key.lower()):
                return _extract(models[key])

        # 2. 最后一段 / 尾部匹配（处理 "Pro/THUDM/glm-4-9b-chat" 等路径前缀）
        last_segment = m.rsplit("/", 1)[-1].lower()
        for key in sorted_keys:
            key_last = key.rsplit("/", 1)[-1].lower()
            if not key_last:  # 跳过 "deepseek-ai/" 等空尾键
                continue
            if last_segment.startswith(key_last):
                return _extract(models[key])

        return _extract(models.get("_default", {}))

    @classmethod
    def cache_discovered_limits(cls, model_name: str, limits: dict[str, int]) -> None:
        m = model_name.lower()
        cls._discovered_limits.setdefault(m, {}).update(limits)

    @staticmethod
    def parse_limits_from_error(error_text: str) -> dict[str, int] | None:
        result: dict[str, int] = {}

        m = re.search(r'valid\s+range.*?\[\s*\d+\s*,\s*(\d+)\s*\]', error_text, re.I)
        if m:
            result["max_output"] = int(m.group(1))
        else:
            m = re.search(r'max_tokens.*?(?:less than or equal to|<=|不超过|上限为?)\s*(\d{3,6})', error_text, re.I)
            if m:
                result["max_output"] = int(m.group(1))
            else:
                m = re.search(r'max_tokens.*?\b(\d{3,6})\b', error_text, re.I)
                if m:
                    result["max_output"] = int(m.group(1))

        m = re.search(r'context.*?length.*?(\d{4,7})', error_text, re.I)
        if m:
            result["context_window"] = int(m.group(1))
        else:
            m = re.search(r'maximum.*?(\d{4,7})\s*tokens', error_text, re.I)
            if m:
                result["context_window"] = int(m.group(1))

        return result or None
