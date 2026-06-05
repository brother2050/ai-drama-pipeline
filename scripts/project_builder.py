"""项目构建器 — 从 ImportPlan 构建/追加项目"""
from __future__ import annotations

from infra.constants import STATUS_DONE
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["ProjectBuilder"]


class ProjectBuilder:
    """从 ImportPlan 构建项目 — 支持全量创建和增量追加"""

    def _write_characters(self, plan, paths) -> None:
        """写入角色 YAML"""
        from infra.config import save_yaml
        for char in plan.characters:
            char_dict = char.model_dump(exclude_none=True)
            char_dict.pop("id", None)
            save_yaml(paths.character_yaml(char.id), {"character": {**char_dict, "id": char.id}})

    def _write_scenes(self, plan, paths) -> None:
        """写入场景 YAML"""
        from infra.config import save_yaml
        for scene in plan.scenes:
            scene_dict = scene.model_dump(exclude_none=True)
            scene_dict.pop("id", None)
            save_yaml(paths.scene_yaml(scene.id), {"scene": {**scene_dict, "id": scene.id}})

    def _write_shots_by_episode(self, plan) -> None:
        """按集分组写入分镜"""
        from collections import defaultdict
        from engines.storyboard import save_storyboard
        shots_by_ep: dict[int, list[dict]] = defaultdict(list)
        for s in plan.shots:
            d = s.model_dump()
            try:
                ep = int(d.get("episode", 1) or 1)
            except (ValueError, TypeError):
                ep = 1
            shots_by_ep[ep].append(d)
        for ep, ep_shots in shots_by_ep.items():
            save_storyboard(ep_shots, episode=ep)

    def build(self, plan, root: Path) -> Path:
        """构建项目（全量模式）

        Args:
            plan: ImportPlan 实例（已通过 Schema 校验）
            root: 项目根目录（如 /path/to/ai-drama-pipeline-v2）

        Returns:
            创建的项目目录路径

        Raises:
            ValueError: 项目已存在（非 append 模式）
            Exception: 写入失败时自动回滚
        """
        from scripts.project_mgr import _ensure_project_dirs, _scaffold_default_config
        from infra.config import ProjectPaths, projects_dir

        project_dir = projects_dir(root) / self._safe_name(plan.project_name)
        if project_dir.exists():
            raise ValueError(f"项目 '{plan.project_name}' 已存在，请更换名称或删除已有项目")

        try:
            _ensure_project_dirs(project_dir)
            paths = ProjectPaths(project_dir)

            _scaffold_default_config(project_dir, plan.project_name,
                                     style=plan.style, genre=plan.genre)

            if plan.episodes_summary:
                from infra.config import load_config, save_config
                cfg_data = load_config(str(paths.project_yaml))
                cfg_data["project"]["episodes_summary"] = plan.episodes_summary
                save_config(str(paths.project_yaml), cfg_data)

            self._write_characters(plan, paths)
            self._write_scenes(plan, paths)

            # 设置活动项目（必须在 DB 写入前）
            active_file = projects_dir(root) / ".active"
            active_file.write_text(str(project_dir), encoding="utf-8")
            from infra.database._db import _reset_project_cache
            _reset_project_cache()

            if plan.shots:
                self._write_shots_by_episode(plan)

            return project_dir

        except Exception:
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            raise

    def append(self, plan, root: Path, project_dir: Path | None = None) -> dict:
        """追加模式 — 向已有项目补充 characters/scenes/shots

        Args:
            plan: ImportPlan 实例（append=True，已通过 Schema 校验）
            root: 项目根目录
            project_dir: 已解析的项目目录（可选，为空时从 plan.project_name 推导）

        Returns:
            {"status": STATUS_DONE, "project_dir": ..., "added_characters": N, "added_scenes": N, "added_shots": N}

        Raises:
            ValueError: 项目不存在
        """
        from infra.config import projects_dir

        if not project_dir:
            if plan.project_name:
                project_dir = projects_dir(root) / self._safe_name(plan.project_name)
            else:
                from infra.config import get_active_project_dir
                project_dir = get_active_project_dir(root)
        if not project_dir.exists():
            raise ValueError(f"项目 '{plan.project_name}' 不存在，无法追加。请先执行全量导入。")

        # 绑定项目作用域，确保 DB 写入到正确项目（不依赖 .active 全局状态）
        from infra.database._db import project_scope
        with project_scope(project_dir.name):
            return self._append_inner(plan, project_dir)

    def _append_characters(self, plan, paths) -> int:
        """追加角色（不存在则创建），返回新增数"""
        from infra.config import save_yaml, load_yaml_entities
        if not plan.characters:
            return 0
        char_dir = paths.characters_dir
        char_dir.mkdir(parents=True, exist_ok=True)
        existing = {e["id"] for e in load_yaml_entities(char_dir, "character")}
        added = 0
        for char in plan.characters:
            if char.id in existing:
                logger.info(f"  跳过已有角色: {char.id}")
                continue
            char_dict = char.model_dump(exclude_none=True)
            char_dict.pop("id", None)
            save_yaml(paths.character_yaml(char.id), {"character": {**char_dict, "id": char.id}})
            added += 1
        return added

    def _append_scenes(self, plan, paths) -> int:
        """追加场景（不存在则创建），返回新增数"""
        from infra.config import save_yaml, load_yaml_entities
        if not plan.scenes:
            return 0
        scene_dir = paths.scenes_dir
        scene_dir.mkdir(parents=True, exist_ok=True)
        existing = {e["id"] for e in load_yaml_entities(scene_dir, "scene")}
        added = 0
        for scene in plan.scenes:
            if scene.id in existing:
                logger.info(f"  跳过已有场景: {scene.id}")
                continue
            scene_dict = scene.model_dump(exclude_none=True)
            scene_dict.pop("id", None)
            save_yaml(paths.scene_yaml(scene.id), {"scene": {**scene_dict, "id": scene.id}})
            added += 1
        return added

    def _append_shots(self, plan) -> tuple[int, int]:
        """追加分镜（去重），返回 (新增数, 跳过数)"""
        from engines.storyboard import append_storyboard
        if not plan.shots:
            return 0, 0
        existing_ids: set[str] = set()
        try:
            from infra.database.pool import get_pool
            from infra.database.storyboard_db import get_all_episodes, get_episode_shots
            pool = get_pool()
            for ep in get_all_episodes(pool):
                for row in get_episode_shots(pool, ep):
                    sid = row.get("shot_id", "")
                    if sid:
                        existing_ids.add(sid)
        except Exception as e:
            logger.debug(f"读取已有镜头 ID 跳过: {e}")

        new_shots, skipped = [], 0
        for s in plan.shots:
            d = s.model_dump()
            if d.get("shot_id") in existing_ids:
                skipped += 1
                logger.info(f"  跳过重复镜头: {d['shot_id']}")
                continue
            existing_ids.add(d["shot_id"])
            new_shots.append(d)
        if new_shots:
            append_storyboard(new_shots)
        return len(new_shots), skipped

    def _append_inner(self, plan, project_dir: Path) -> dict:
        """追加核心逻辑（在 project_scope 内执行）"""
        from infra.config import ProjectPaths, load_config, save_config

        paths = ProjectPaths(project_dir)

        if plan.episodes_summary:
            cfg_data = load_config(str(paths.project_yaml))
            cfg_data["project"]["episodes_summary"] = plan.episodes_summary
            save_config(str(paths.project_yaml), cfg_data)

        added_chars = self._append_characters(plan, paths)
        added_scenes = self._append_scenes(plan, paths)
        added_shots, skipped = self._append_shots(plan)

        if skipped:
            logger.info(f"  跳过 {skipped} 个重复镜头")

        return {
            "status": STATUS_DONE,
            "project_dir": str(project_dir),
            "added_characters": added_chars,
            "added_scenes": added_scenes,
            "added_shots": added_shots,
        }

    @staticmethod
    def _safe_name(name: str) -> str:
        """项目名安全化"""
        import re
        safe = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", name).strip("_")
        return safe or "imported"
