"""分镜一致性校验 — 跨镜头/跨集

参考 Seedance2-Storyboard-Generator 的多集连贯性保障：
- 服装连续性：相邻镜头服装不应突变
- 角色存在性：引用的角色必须存在
- 场景存在性：引用的场景必须存在
- 时长合理性：每镜头 2-8 秒
- 情绪逻辑过渡：相邻镜头情绪不应剧烈跳变

用法:
    checker = ConsistencyChecker()
    errors = checker.check_episode(shots, characters, scenes)
    if errors:
        for e in errors:
            logger.error(f"初始化失败: {e}")
"""
from __future__ import annotations

import logging

from engines.shot_utils import parse_char_ids

logger = logging.getLogger(__name__)

__all__ = ["ConsistencyChecker", "check_consistency"]


def check_consistency(
    shots: list[dict],
    characters: list[dict] | None = None,
    scenes: list[dict] | None = None,
) -> list[str]:
    """快捷入口：检查分镜一致性

    Args:
        shots: 镜头列表
        characters: 角色列表（可选，不传则跳过角色存在性检查）
        scenes: 场景列表（可选，不传则跳过场景存在性检查）

    Returns:
        错误消息列表（空列表 = 全部通过）
    """
    checker = ConsistencyChecker()
    return checker.check_episode(shots, characters, scenes)


class ConsistencyChecker:
    """分镜一致性校验器"""

    def check_episode(
        self,
        shots: list[dict],
        characters: list[dict] | None = None,
        scenes: list[dict] | None = None,
    ) -> list[str]:
        """检查单集内的一致性

        Args:
            shots: 镜头列表
            characters: 角色列表
            scenes: 场景列表

        Returns:
            错误消息列表
        """
        errors: list[str] = []

        if not shots:
            return errors

        # 1. 服装连续性
        errors.extend(self._check_outfit_continuity(shots))

        # 1.5 服装存在性
        if characters:
            errors.extend(self._check_outfit_exists(shots, characters))

        # 2. 角色存在性
        if characters:
            errors.extend(self._check_character_exists(shots, characters))

        # 3. 场景存在性
        if scenes:
            errors.extend(self._check_scene_exists(shots, scenes))

        # 4. 时长合理性
        errors.extend(self._check_duration(shots))

        # 5. shot_id 唯一性
        errors.extend(self._check_shot_id_unique(shots))

        # 6. 情绪逻辑过渡
        errors.extend(self._check_emotion_transition(shots))

        return errors

    def _check_outfit_continuity(self, shots: list[dict]) -> list[str]:
        """检查服装连续性：同场景内相邻镜头服装不应突变"""
        errors = []
        for i in range(1, len(shots)):
            prev = shots[i - 1]
            curr = shots[i]
            prev_outfit = prev.get("outfit", "")
            curr_outfit = curr.get("outfit", "")
            if not prev_outfit or not curr_outfit:
                continue
            if prev_outfit == curr_outfit:
                continue
            # 同场景内服装变化 = 可能的问题
            if prev.get("scene_id") == curr.get("scene_id"):
                # 检查是否有角色变化（不同角色可以穿不同衣服）
                prev_chars = set(parse_char_ids(prev))
                curr_chars = set(parse_char_ids(curr))
                if prev_chars == curr_chars:
                    errors.append(
                        f"镜头 {curr.get('shot_id', '?')}: 同场景同角色内服装突变 "
                        f"({prev_outfit} → {curr_outfit})"
                    )
        return errors

    def _check_outfit_exists(self, shots: list[dict], characters: list[dict]) -> list[str]:
        """检查服装存在性：引用的 outfit 必须在角色的 outfits 字典中"""
        errors = []
        char_outfits: dict[str, set[str]] = {}
        for char in characters:
            cid = char.get("id", "")
            if not cid:
                continue
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict):
                char_outfits[cid] = set(outfits.keys())
            else:
                char_outfits[cid] = set()

        for shot in shots:
            outfit = shot.get("outfit", "").strip()
            if not outfit:
                continue
            for cid in parse_char_ids(shot):
                available = char_outfits.get(cid)
                if available is not None and outfit not in available:
                    errors.append(
                        f"镜头 {shot.get('shot_id', '?')}: 角色 '{cid}' 无服装 '{outfit}' "
                        f"(可用: {', '.join(sorted(available)) or '无'})"
                    )
        return errors

    def _check_character_exists(self, shots: list[dict], characters: list[dict]) -> list[str]:
        """检查角色存在性：引用的角色必须存在"""
        errors = []
        char_ids = {c.get("id", "") for c in characters}
        for shot in shots:
            sid = shot.get("shot_id", "?")
            for cid in parse_char_ids(shot):
                if cid not in char_ids:
                    errors.append(f"镜头 {sid}: 角色 '{cid}' 不存在")
        return errors

    def _check_scene_exists(self, shots: list[dict], scenes: list[dict]) -> list[str]:
        """检查场景存在性：引用的场景必须存在"""
        errors = []
        scene_ids = {s.get("id", "") for s in scenes}
        for shot in shots:
            sid = shot.get("shot_id", "?")
            scene_id = (shot.get("scene_id") or "").strip()
            if scene_id and scene_id not in scene_ids:
                errors.append(f"镜头 {sid}: 场景 '{scene_id}' 不存在")
        return errors

    def _check_duration(self, shots: list[dict]) -> list[str]:
        """检查时长合理性：每镜头 2-8 秒"""
        errors = []
        for shot in shots:
            sid = shot.get("shot_id", "?")
            try:
                d = round(float(shot.get("duration", 4)))
            except (ValueError, TypeError):
                errors.append(f"镜头 {sid}: 时长格式错误 ({shot.get('duration')})")
                continue
            if d < 2:
                errors.append(f"镜头 {sid}: 时长过短 ({d}s < 2s)")
            elif d > 8:
                errors.append(f"镜头 {sid}: 时长过长 ({d}s > 8s)")
        return errors

    def _check_shot_id_unique(self, shots: list[dict]) -> list[str]:
        """检查 shot_id 唯一性"""
        errors = []
        seen: dict[str, int] = {}
        for i, shot in enumerate(shots):
            sid = shot.get("shot_id", "")
            if not sid:
                errors.append(f"镜头索引 {i}: 缺少 shot_id")
                continue
            if sid in seen:
                errors.append(f"镜头 {sid}: 重复（首次出现在索引 {seen[sid]}）")
            else:
                seen[sid] = i
        return errors

    def _check_emotion_transition(self, shots: list[dict]) -> list[str]:
        """检查情绪逻辑过渡：相邻镜头情绪不应剧烈跳变"""
        from infra.constants import VALID_EMOTIONS
        errors = []

        # 情绪跳变黑名单（不合理的跳变，其余均允许）
        BLOCKED_TRANSITIONS = {
            ("happy", "fearful"), ("fearful", "happy"),
            ("romantic", "angry"), ("angry", "romantic"),
            ("calm", "angry"), ("angry", "calm"),
        }

        for i in range(len(shots)):
            emotion = shots[i].get("emotion", "neutral")
            # 校验情绪值合法性
            if emotion not in VALID_EMOTIONS:
                errors.append(
                    f"镜头 {shots[i].get('shot_id', '?')}: 无效情绪 '{emotion}'，"
                    f"合法值: {', '.join(sorted(VALID_EMOTIONS))}"
                )
                continue

            if i == 0:
                continue
            prev_emotion = shots[i - 1].get("emotion", "neutral")
            if prev_emotion == emotion:
                continue
            # 不同场景允许任意情绪变化
            if shots[i - 1].get("scene_id") != shots[i].get("scene_id"):
                continue
            transition = (prev_emotion, emotion)
            if transition in BLOCKED_TRANSITIONS:
                errors.append(
                    f"镜头 {shots[i].get('shot_id', '?')}: 情绪跳变 "
                    f"({prev_emotion} → {emotion})，建议添加过渡镜头"
                )
        return errors
