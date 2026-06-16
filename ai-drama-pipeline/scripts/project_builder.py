"""项目构建器 — 从 ImportPlan 构建/追加项目"""
from __future__ import annotations

from infra.constants import STATUS_DONE
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["ProjectBuilder", "ProjectAlreadyExists"]


class ProjectAlreadyExists(ValueError):
    """项目已存在（非 append 模式下，build() 时目录已存在）"""



class ProjectBuilder:
    """从 ImportPlan 构建项目 — 支持全量创建和增量追加"""

    def _write_characters(self, plan, paths) -> None:
        """写入角色 YAML"""
        from infra.config import save_yaml
        from infra.models import normalize_character
        for char in plan.characters:
            char_dict = char.model_dump(exclude_none=True)
            char_dict.pop("id", None)
            save_yaml(paths.character_yaml(char.id), {"character": normalize_character({**char_dict, "id": char.id})})

    def _write_scenes(self, plan, paths) -> None:
        """写入场景 YAML"""
        from infra.config import save_yaml
        from infra.models import normalize_scene
        for scene in plan.scenes:
            scene_dict = scene.model_dump(exclude_none=True)
            scene_dict.pop("id", None)
            save_yaml(paths.scene_yaml(scene.id), {"scene": normalize_scene({**scene_dict, "id": scene.id})})

    def _write_shots_by_episode(self, plan) -> None:
        """按集分组写入分镜"""
        from collections import defaultdict
        from engines.content.storyboard import save_storyboard
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
            raise ProjectAlreadyExists(f"项目 '{plan.project_name}' 已存在，请更换名称或删除已有项目")

        active_file = projects_dir(root) / ".active"
        prev_active = active_file.read_text(encoding="utf-8").strip() if active_file.exists() else ""
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

            # DB 写入使用 project_scope（线程本地隔离，不依赖 .active 文件）
            if plan.shots:
                from infra.database._db import project_scope
                with project_scope(project_dir.name):
                    self._write_shots_by_episode(plan)

            # 全部写入成功后才设置 .active（供后续非 DB 操作使用）
            active_file.write_text(str(project_dir), encoding="utf-8")
            from infra.database._db import _reset_project_cache
            _reset_project_cache()

            return project_dir

        except Exception:
            # 恢复之前的活动项目指针
            try:
                if prev_active:
                    active_file.write_text(prev_active, encoding="utf-8")
                elif active_file.exists():
                    active_file.unlink()
            except OSError:
                pass
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
        from infra.models import normalize_character
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
            save_yaml(paths.character_yaml(char.id), {"character": normalize_character({**char_dict, "id": char.id})})
            added += 1
        return added

    def _append_scenes(self, plan, paths) -> int:
        """追加场景（不存在则创建），返回新增数"""
        from infra.config import save_yaml, load_yaml_entities
        from infra.models import normalize_scene
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
            save_yaml(paths.scene_yaml(scene.id), {"scene": normalize_scene({**scene_dict, "id": scene.id})})
            added += 1
        return added

    def _append_shots(self, plan) -> tuple[int, int]:
        """追加分镜（DB 级 upsert 去重），返回 (写入数, plan 内重复数)

        去重由 PostgreSQL ON CONFLICT DO UPDATE 保证，不在应用层读 DB 做 TOCTOU 检查。
        plan 内部同 (episode, shot_id) 重复出现的计为 dupes，只写入一次。
        """
        from engines.content.storyboard import append_storyboard
        if not plan.shots:
            return 0, 0
        # 仅检测 plan 内部重复（不读 DB）
        seen: set[tuple[int, str]] = set()
        dupes = 0
        unique_shots: list[dict] = []
        for s in plan.shots:
            d = s.model_dump()
            ep = int(d.get("episode", 1) or 1)
            key = (ep, d.get("shot_id", ""))
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            unique_shots.append(d)
        if unique_shots:
            append_storyboard(unique_shots)
        return len(unique_shots), dupes

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
