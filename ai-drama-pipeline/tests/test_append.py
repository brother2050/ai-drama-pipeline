"""ProjectBuilder.append() 端到端测试 — 纯本地（不需要 Redis/PostgreSQL）"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.models import ImportPlan  # noqa: E402
from infra.config import save_yaml, ProjectPaths, load_yaml_entities  # noqa: E402


def _make_project(tmp_path: Path) -> Path:
    """创建模拟项目目录（含已有角色/场景）"""
    project_dir = tmp_path / "test_project"
    paths = ProjectPaths(project_dir)
    paths.characters_dir.mkdir(parents=True, exist_ok=True)
    paths.scenes_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    save_yaml(paths.character_yaml("linxia"), {
        "character": {"id": "linxia", "name": "林夏", "appearance": "22岁长发温柔女生，身材娇小，皮肤白皙"}
    })
    save_yaml(paths.scene_yaml("living_room"), {
        "scene": {"id": "living_room", "name": "客厅", "description": "现代简约客厅，落地窗暖光木质地板"}
    })
    return project_dir


class TestAppendCharacters:
    """追加角色测试"""

    def test_append_new_character(self, tmp_path):
        from scripts.project_builder import ProjectBuilder
        project_dir = _make_project(tmp_path)
        paths = ProjectPaths(project_dir)

        plan = ImportPlan(
            append=True,
            characters=[{"id": "guchen", "name": "顾辰", "appearance": "25岁短发帅气男生，剑眉星目，身材高挑挺拔"}],
        )
        builder = ProjectBuilder()
        added = builder._append_characters(plan, paths)
        assert added == 1
        chars = load_yaml_entities(paths.characters_dir, "character")
        ids = {c["id"] for c in chars}
        assert "linxia" in ids
        assert "guchen" in ids

    def test_append_skips_existing_character(self, tmp_path):
        from scripts.project_builder import ProjectBuilder
        project_dir = _make_project(tmp_path)
        paths = ProjectPaths(project_dir)

        plan = ImportPlan(
            append=True,
            characters=[{"id": "linxia", "name": "林夏改名", "appearance": "全新的外貌描述内容，与原来不同"}],
        )
        builder = ProjectBuilder()
        added = builder._append_characters(plan, paths)
        assert added == 0  # 跳过已有
        char = load_yaml_entities(paths.characters_dir, "character")
        linxia = next(c for c in char if c["id"] == "linxia")
        assert linxia["name"] == "林夏"

    def test_append_empty_characters(self, tmp_path):
        from scripts.project_builder import ProjectBuilder
        project_dir = _make_project(tmp_path)
        paths = ProjectPaths(project_dir)

        plan = ImportPlan(append=True)
        builder = ProjectBuilder()
        assert builder._append_characters(plan, paths) == 0


class TestAppendScenes:
    """追加场景测试"""

    def test_append_new_scene(self, tmp_path):
        from scripts.project_builder import ProjectBuilder
        project_dir = _make_project(tmp_path)
        paths = ProjectPaths(project_dir)

        plan = ImportPlan(
            append=True,
            scenes=[{"id": "street", "name": "街道", "description": "繁华都市商业街，霓虹灯闪烁，人来人往"}],
        )
        builder = ProjectBuilder()
        added = builder._append_scenes(plan, paths)
        assert added == 1
        scenes = load_yaml_entities(paths.scenes_dir, "scene")
        ids = {s["id"] for s in scenes}
        assert "living_room" in ids
        assert "street" in ids

    def test_append_skips_existing_scene(self, tmp_path):
        from scripts.project_builder import ProjectBuilder
        project_dir = _make_project(tmp_path)
        paths = ProjectPaths(project_dir)

        plan = ImportPlan(
            append=True,
            scenes=[{"id": "living_room", "name": "客厅改名", "description": "全新的场景描述内容，与原来不同"}],
        )
        builder = ProjectBuilder()
        added = builder._append_scenes(plan, paths)
        assert added == 0


class TestAppendShots:
    """追加分镜测试（mock DB）"""

    def test_append_shots_no_db(self, tmp_path, monkeypatch):
        """无 DB 时 _append_shots 的 shot 去重检查安全降级，但写入会失败"""
        from scripts.project_builder import ProjectBuilder

        def mock_get_pool():
            raise RuntimeError("DB not available")
        monkeypatch.setattr("infra.database.pool.get_pool", mock_get_pool)

        plan = ImportPlan(
            append=True,
            shots=[{"shot_id": "001", "scene_name": "s", "characters": "c", "action": "测试动作描述内容"}],
        )
        builder = ProjectBuilder()
        # 无 DB 时 shot 去重检查跳过（existing_ids 为空），new_shots 有数据
        # 但 append_storyboard 内部调用 _pool() 会抛 RuntimeError
        with pytest.raises(RuntimeError, match="DB not available"):
            builder._append_shots(plan)


class TestSafeName:
    """项目名安全化测试"""

    def test_safe_name_chinese(self):
        from scripts.project_builder import ProjectBuilder
        assert ProjectBuilder._safe_name("都市恋歌") == "都市恋歌"

    def test_safe_name_special_chars(self):
        from scripts.project_builder import ProjectBuilder
        assert ProjectBuilder._safe_name("my project!") == "my_project"

    def test_safe_name_empty(self):
        from scripts.project_builder import ProjectBuilder
        assert ProjectBuilder._safe_name("") == "imported"

    def test_safe_name_slashes(self):
        from scripts.project_builder import ProjectBuilder
        # ../evil → _evil → strip(_) → evil
        result = ProjectBuilder._safe_name("../evil")
        assert result == "evil"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
