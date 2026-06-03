"""多人同框处理"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["MultiCharacterHandler"]

# CLIP tokenizer 限制：超过此长度的 prompt 会被截断，多人场景容易超
# 默认 CLIP token 限制（SD1.5/SDXL）。Flux 使用 T5 无此限制。
# 可通过构造函数或配置覆盖。
_DEFAULT_CLIP_TOKEN_LIMIT = 75


class MultiCharacterHandler:
    """多人同框场景处理器"""

    def generate_multi_char_prompt(self, characters: list[dict], layout: str = "side_by_side",
                                     clip_token_limit: int = _DEFAULT_CLIP_TOKEN_LIMIT) -> str:
        """生成多人同框 prompt。超过 CLIP 限制时记录警告。"""
        if not characters:
            return ""
        if len(characters) <= 1:
            char = characters[0] if characters else {}
            return char.get("appearance_prompt_en", char.get("appearance", ""))

        parts = []
        for i, char in enumerate(characters):
            desc = char.get("appearance_prompt_en", char.get("appearance", ""))
            if layout == "side_by_side":
                pos = "on the left" if i % 2 == 0 else "on the right"
            else:
                pos = f"position {i+1}"
            parts.append(f"{desc}, {pos}")
        prompt = ", ".join(parts)

        # 粗略估算 token 数（英文约 1 token/4 字符）
        est_tokens = len(prompt) // 4
        if est_tokens > clip_token_limit:
            logger.warning(
                f"多人 prompt 约 {est_tokens} tokens，超过 CLIP 限制 {clip_token_limit}，"
                f"画面可能丢失细节。建议减少角色数量或缩短外貌描述。"
            )
        return prompt

    def calculate_regions(self, count: int, layout: str = "side_by_side") -> list[dict]:
        if not count or count <= 1:
            return [{"position": "center", "x": 0.5, "y": 0.5}]
        return [{"position": "left" if i % 2 == 0 else "right",
                 "x": 0.25 + 0.5 * (i % 2), "y": 0.5} for i in range(count)]
