"""多人同框处理 — prompt 拼接、位置分配、token 管理"""
from __future__ import annotations

import logging
from infra.batch_processor import estimate_tokens

logger = logging.getLogger(__name__)

__all__ = ["MultiCharacterHandler"]

# CLIP tokenizer 限制：超过此长度的 prompt 会被截断，多人场景容易超
_DEFAULT_CLIP_TOKEN_LIMIT = 75

# 有意义的位置标签（"position N" 对 AI 绘图模型无引导作用）
_POSITION_LABELS = {
    "side_by_side": ["on the left", "on the right"],
    "group": ["in the center", "on the left", "on the right", "in the background"],
}


class MultiCharacterHandler:
    """多人同框场景处理器"""

    def generate_multi_char_prompt(
        self,
        characters: list[dict],
        layout: str = "side_by_side",
        clip_token_limit: int = _DEFAULT_CLIP_TOKEN_LIMIT,
    ) -> str:
        """生成多人同框 prompt。

        超过 CLIP 限制时截断并警告（而非仅警告，避免 ComfyUI 静默截断导致不可控结果）。
        """
        if not characters:
            return ""
        if len(characters) <= 1:
            char = characters[0] if characters else {}
            return char.get("appearance_prompt_en", char.get("appearance", ""))

        parts = []
        for i, char in enumerate(characters):
            desc = char.get("appearance_prompt_en", char.get("appearance", ""))
            if not desc:
                continue
            pos = _position_label(i, layout, len(characters))
            parts.append(f"{pos}, {desc}")
        prompt = ", ".join(parts)

        # token 超限时截断（从最后一个角色开始移除，优先保证主角色质量）
        est_tokens = estimate_tokens(prompt)
        if est_tokens > clip_token_limit:
            prompt = self._truncate_to_fit(parts, clip_token_limit)
            logger.warning(
                f"多人 prompt 超过 CLIP 限制 {clip_token_limit} tokens，已截断至 {estimate_tokens(prompt)} tokens。"
                f"建议减少角色数量或缩短外貌描述。"
            )
        return prompt

    def merge_character_bibles(self, characters: list[dict]) -> str:
        """合并多个角色的 character_bible 标签（用于多角色场景的 prompt 注入）

        每个角色取核心特征，避免 prompt 过长。
        """
        if not characters:
            return ""
        parts = []
        for char in characters:
            name = char.get("name", char.get("id", ""))
            bible = char.get("bible", {})
            if not bible:
                continue
            traits = bible.get("core_traits", "")
            if traits:
                parts.append(f"{name}: {traits}")
        return "; ".join(parts)

    def calculate_regions(self, count: int, layout: str = "side_by_side") -> list[dict]:
        """计算多人场景的区域分配"""
        if not count or count <= 1:
            return [{"position": "center", "x": 0.5, "y": 0.5}]
        regions = []
        for i in range(count):
            pos = _position_label(i, layout, count)
            if layout == "side_by_side":
                x = 0.25 + 0.5 * (i % 2)
            else:
                x = (i + 0.5) / count
            regions.append({"position": pos, "x": x, "y": 0.5})
        return regions

    @staticmethod
    def _truncate_to_fit(parts: list[str], token_limit: int) -> str:
        """从最后一个角色开始移除，直到 token 数在限制内"""
        for n in range(len(parts), 0, -1):
            candidate = ", ".join(parts[:n])
            if estimate_tokens(candidate) <= token_limit:
                return candidate
        return parts[0] if parts else ""


def _position_label(index: int, layout: str, total: int = 2) -> str:
    """统一的位置标签生成（prompt 和 region 共用）"""
    labels = _POSITION_LABELS.get(layout, _POSITION_LABELS["side_by_side"])
    if index < len(labels):
        return labels[index]
    # 超出预定义标签时，用有意义的描述替代 "position N"
    return f"in the background, character {index + 1}"
