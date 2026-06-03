"""镜头管理器 — 读取分镜表、构建 prompt、管理状态"""
from __future__ import annotations
import logging


logger = logging.getLogger(__name__)

__all__ = ["ShotManager"]


class ShotManager:
    """镜头管理器"""

    REQUIRED = ("episode", "shot_id", "scene_id", "characters", "action", "dialogue")

    def __init__(self, config_dir: str, config: dict | None = None):
        from infra.config import ProjectPaths
        self._paths = ProjectPaths(config_dir)
        self.config = config or {}
        self.shots: list[dict] = []
        self.characters: dict[str, dict] = {}
        self.scenes: dict[str, dict] = {}
        self._load_all()

    def _load_all(self):
        self._load_storyboard()
        self._load_characters()
        self._load_scenes()
        logger.info(f"加载: {len(self.characters)} 角色, {len(self.scenes)} 场景, {len(self.shots)} 镜头")

    def _load_storyboard(self):
        from engines.storyboard import load_storyboard
        episode = self.config.get("episode")
        try:
            self.shots = load_storyboard(episode=int(episode) if episode else None)
        except Exception as e:
            logger.debug(f"分镜加载跳过（DB 不可用？）: {e}")
            self.shots = []

    def _load_characters(self):
        from infra.config import load_yaml_entities
        for char in load_yaml_entities(self._paths.characters_dir, "character"):
            self.characters[char["id"]] = char

    def _load_scenes(self):
        from infra.config import load_yaml_entities
        for scene in load_yaml_entities(self._paths.scenes_dir, "scene"):
            self.scenes[scene["id"]] = scene

    def get_character(self, char_id: str) -> dict:
        return self.characters.get(char_id, {})

    def get_scene(self, scene_id: str) -> dict:
        return self.scenes.get(scene_id, {})

    def get_shots_for_episode(self, episode: int) -> list[dict]:
        result = []
        for s in self.shots:
            try:
                ep = int(s.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep == episode:
                result.append(s)
        return result

    def validate(self) -> list[str]:
        errors = []
        for i, shot in enumerate(self.shots):
            for field in self.REQUIRED:
                if not shot.get(field):
                    errors.append(f"镜头 {i}: 缺少 {field}")
        return errors
