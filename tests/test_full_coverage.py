"""全项目功能全流程测试

覆盖所有模块的核心功能，mock 外部依赖（PostgreSQL/Redis/ComfyUI/TTS）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def project_dir(tmp_dir):
    """创建最小项目目录结构"""
    p = tmp_dir / "projects" / "test_project"
    (p / "config" / "characters").mkdir(parents=True)
    (p / "config" / "scenes").mkdir(parents=True)
    (p / "assets" / "characters").mkdir(parents=True)
    (p / "assets" / "scenes").mkdir(parents=True)
    (p / "output").mkdir(parents=True)
    (p / "workflows").mkdir(parents=True)
    # project.yaml
    from infra.config import save_yaml
    save_yaml(p / "config" / "project.yaml", {
        "project": {"name": "测试项目", "episodes": 1, "style": "cinematic", "genre": "urban"},
    })
    return p


@pytest.fixture
def sample_character(project_dir):
    """创建示例角色 YAML"""
    from infra.config import save_yaml
    char = {
        "character": {
            "id": "linxia",
            "name": "林夏",
            "gender": "female",
            "age": "22",
            "appearance": "22岁温柔女生，长发飘逸，眼睛明亮",
            "appearance_prompt_en": "1girl, 22 years old, long flowing hair, bright eyes, gentle expression",
            "body_features": "",
            "outfits": {
                "default": {"description": "白色连衣裙", "description_en": "white dress", "reference_images": []},
                "casual": {"description": "牛仔裤配T恤", "description_en": "jeans and t-shirt", "reference_images": []},
            },
            "bible": {"core_traits": "温柔但坚强"},
            "bible_en": {"core_traits": "gentle, resilient"},
            "voice_config": {"core_traits": "温柔"},
        }
    }
    save_yaml(project_dir / "config" / "characters" / "linxia.yaml", char)
    return char["character"]


@pytest.fixture
def sample_scene(project_dir):
    """创建示例场景 YAML"""
    from infra.config import save_yaml
    scene = {
        "scene": {
            "id": "living_room",
            "name": "客厅",
            "description": "现代简约客厅，阳光透过落地窗洒在米色沙发上",
            "description_en": "modern minimalist living room, sunlight through floor-to-ceiling windows on beige sofa",
            "lighting": "温暖自然光",
            "lighting_en": "warm natural lighting",
        }
    }
    save_yaml(project_dir / "config" / "scenes" / "living_room.yaml", scene)
    return scene["scene"]


# ══════════════════════════════════════════════════════════
#  1. Config 系统
# ══════════════════════════════════════════════════════════

class TestConfigSystem:
    """配置加载、合并、热重载"""

    def test_config_load_merge(self, project_dir):
        """Config 合并 system.yaml + project.yaml"""
        from infra.config import Config
        cfg = Config(str(project_dir / "config" / "project.yaml"))
        assert cfg.get("project.name") == "测试项目"
        assert cfg.get("project.style") == "cinematic"
        # system.yaml 的默认值
        assert cfg.get("server.port") == 8888

    def test_config_dot_get(self, project_dir):
        """Config.get 支持 dot notation"""
        from infra.config import Config
        cfg = Config(str(project_dir / "config" / "project.yaml"))
        assert cfg.get("models.image_backend") == "flux"
        assert cfg.get("nonexistent.key", "default") == "default"

    def test_config_save_reload(self, project_dir):
        """保存后重载能读到新值"""
        from infra.config import Config, save_yaml
        cfg_path = str(project_dir / "config" / "project.yaml")
        cfg = Config(cfg_path)
        assert cfg.get("project.name") == "测试项目"
        # 修改并保存
        data = cfg.data.copy()
        data["project"]["name"] = "新项目"
        save_yaml(cfg_path, data)
        # 重载
        cfg2 = Config(cfg_path)
        assert cfg2.get("project.name") == "新项目"

    def test_config_paths(self, project_dir):
        """ProjectPaths 统一路径管理"""
        from infra.config import ProjectPaths
        paths = ProjectPaths(project_dir)
        assert paths.characters_dir.exists()
        assert paths.scenes_dir.exists()
        assert paths.config_dir.exists()
        assert paths.character_yaml("test").name == "test.yaml"
        assert paths.shot_dir(1, "001").name == "s001"
        assert paths.episode_final(1).name == "episode_01_final.mp4"

    def test_config_validation(self, project_dir):
        """必填字段校验"""
        from infra.config import Config, save_yaml
        # 缺少 project.name
        bad_path = project_dir / "config" / "bad.yaml"
        save_yaml(str(bad_path), {"project": {"episodes": 1}})
        with pytest.raises(ValueError, match="缺少必填配置"):
            Config(str(bad_path))


# ══════════════════════════════════════════════════════════
#  2. YAML 实体 CRUD
# ══════════════════════════════════════════════════════════

class TestYAMLEntities:
    """角色/场景 YAML 读写"""

    def test_load_character(self, project_dir, sample_character):
        """加载角色配置"""
        from infra.config import load_character, ProjectPaths
        paths = ProjectPaths(project_dir)
        char = load_character(paths, "linxia")
        assert char["id"] == "linxia"
        assert char.get("name") == "林夏"
        assert "appearance_prompt_en" in char

    def test_load_scene(self, project_dir, sample_scene):
        """加载场景配置"""
        from infra.config import load_scene, ProjectPaths
        paths = ProjectPaths(project_dir)
        scene = load_scene(paths, "living_room")
        assert scene["id"] == "living_room"
        assert scene.get("name") == "客厅"

    def test_load_yaml_entities(self, project_dir, sample_character, sample_scene):
        """批量加载实体"""
        from infra.config import load_yaml_entities, ProjectPaths
        paths = ProjectPaths(project_dir)
        chars = load_yaml_entities(paths.characters_dir, "character")
        assert len(chars) == 1
        assert chars[0]["id"] == "linxia"
        scenes = load_yaml_entities(paths.scenes_dir, "scene")
        assert len(scenes) == 1
        assert scenes[0]["id"] == "living_room"

    def test_save_yaml_atomic(self, tmp_dir):
        """原子写入 YAML（不损坏已有文件）"""
        from infra.config import save_yaml, load_yaml_full
        path = tmp_dir / "test.yaml"
        save_yaml(str(path), {"key": "value1"})
        assert load_yaml_full(path)["key"] == "value1"
        save_yaml(str(path), {"key": "value2"})
        assert load_yaml_full(path)["key"] == "value2"

    def test_load_nonexistent(self, project_dir):
        """不存在的实体返回默认值"""
        from infra.config import load_character, load_scene
        char = load_character(project_dir, "nonexistent")
        assert char == {"id": "nonexistent"}
        scene = load_scene(project_dir, "nonexistent")
        assert scene == {"id": "nonexistent"}


# ══════════════════════════════════════════════════════════
#  3. LLM 生成引擎
# ══════════════════════════════════════════════════════════

class TestLLMGenerator:
    """分镜/角色/场景生成"""

    def test_generate_storyboard(self):
        """从大纲生成分镜"""
        from engines.content.llm import generate_storyboard, StoryboardGenParams

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return json.dumps([
                    {"shot_id": "001", "scene_name": "room", "characters": "alice",
                     "action": "Alice sits", "action_en": "Alice sits on sofa",
                     "dialogue": "你好", "dialogue_en": "Hello",
                     "camera": "固定", "shot_type": "中景", "duration": "4", "emotion": "happy"},
                ])

        shots, warnings = generate_storyboard(FakeLLM(), StoryboardGenParams(
            outline="Alice enters room", episode=1, target_duration=10))
        assert len(shots) == 1
        assert shots[0]["shot_id"] == "001"
        assert shots[0]["episode"] == 1

    def test_generate_characters(self):
        """从描述生成角色"""
        from engines.content.generator import generate_characters

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return json.dumps([{"name": "Alice", "gender": "female",
                                    "appearance": "young woman", "outfits": {"default": {"description": "dress"}},
                                    "bible": {"core_traits": "kind"}}])

        chars = generate_characters(FakeLLM(), ["name 必须为「Alice」"])
        assert len(chars) == 1
        assert chars[0]["name"] == "Alice"
        assert chars[0]["bible"]["core_traits"] == "kind"

    def test_generate_scenes(self):
        """从描述生成场景"""
        from engines.content.generator import generate_scenes

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return json.dumps([{"name": "客厅", "description": "modern room", "lighting": "bright"}])

        scenes = generate_scenes(FakeLLM(), ["name 必须为「客厅」"])
        assert len(scenes) == 1
        assert scenes[0]["name"] == "客厅"


# ══════════════════════════════════════════════════════════
#  4. Prompt 编译
# ══════════════════════════════════════════════════════════

class TestPromptCompiler:
    """Prompt 模板编译"""

    def test_compile_template(self):
        """模板变量替换"""
        from engines.prompt.compiler import get_compiler
        compiler = get_compiler()
        result = compiler.compile_text("${style} style, ${scene}", {"style": "cinematic", "scene": "living room"})
        assert "cinematic" in result
        assert "living room" in result

    def test_compile_empty_values(self):
        """空值清理"""
        from engines.prompt.compiler import get_compiler
        compiler = get_compiler()
        result = compiler.compile_text("${a}, ${b}, ${c}", {"a": "hello", "b": "", "c": "world"})
        assert ", ," not in result
        assert "hello" in result
        assert "world" in result

    def test_compile_first_frame(self):
        """首帧 prompt 编译"""
        from engines.prompt.compiler import get_compiler
        compiler = get_compiler()
        result = compiler.compile_first_frame(
            shot={"action_en": "sits on sofa", "emotion": "happy", "shot_type": "中景", "camera": "固定"},
            character_desc="young woman with long hair",
            scene_desc="modern living room",
            style="cinematic", genre="urban", prompt_style="tag")
        assert "young woman" in result
        assert "living room" in result

    def test_template_list(self):
        """模板列表非空"""
        from engines.prompt.compiler import get_compiler
        compiler = get_compiler()
        templates = compiler.list_templates()
        assert len(templates) > 0
        assert "first_frame_tag" in templates


# ══════════════════════════════════════════════════════════
#  5. Prompt 翻译
# ══════════════════════════════════════════════════════════

class TestPromptTranslation:
    """中英翻译"""

    def test_translate_to_english(self):
        """单条翻译"""
        from engines.prompt.translate import translate_to_english

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return "Hello world"

        result = translate_to_english("你好世界", llm=FakeLLM())
        assert result == "Hello world"

    def test_translate_ascii_passthrough(self):
        """已是英文直接返回"""
        from engines.prompt.translate import translate_to_english
        result = translate_to_english("Hello world", llm=None)
        assert result == "Hello world"

    def test_translate_none_llm(self):
        """llm=None 返回空串"""
        from engines.prompt.translate import translate_to_english
        result = translate_to_english("你好", llm=None)
        assert result == ""

    def test_batch_translate(self):
        """批量翻译（UID 格式）"""
        from engines.prompt.translate import translate_to_english, batch_translate_to_english

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                # 从输入中提取 UID 并返回 UID 格式的翻译
                import re as _re
                lines = prompt.strip().split("\n")
                results = []
                for i, line in enumerate(lines):
                    m = _re.match(r'^\[(t[a-fA-F0-9]{6})\]\s*(.+)', line)
                    if m:
                        uid = m.group(1)
                        results.append(f"[{uid}] trans_{i+1}")
                return "\n".join(results)

        results = batch_translate_to_english(["你好", "世界"], llm=FakeLLM())
        assert results[0] == "trans_1"
        assert results[1] == "trans_2"

    def test_batch_translate_mixed(self):
        """混合中英文批量翻译"""
        from engines.prompt.translate import translate_to_english, batch_translate_to_english

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                import re as _re
                lines = prompt.strip().split("\n")
                results = []
                for i, line in enumerate(lines):
                    m = _re.match(r'^\[(t[a-fA-F0-9]{6})\]\s*(.+)', line)
                    if m:
                        uid = m.group(1)
                        results.append(f"[{uid}] trans_{i+1}")
                return "\n".join(results)

        results = batch_translate_to_english(["你好", "already english"], llm=FakeLLM())
        assert results[1] == "already english"  # 已是英文，跳过翻译


# ══════════════════════════════════════════════════════════
#  6. 镜头工具
# ══════════════════════════════════════════════════════════

class TestShotUtils:
    """镜头后处理"""

    def test_postprocess_shots(self):
        """镜头后处理"""
        from engines.utils.shot import postprocess_shots
        shots = [
            {"shot_id": "001", "duration": "5", "emotion": "happy"},
            {"shot_id": "", "duration": "10", "emotion": "unknown"},
            {"shot_id": "001", "duration": "3"},  # 重复 ID
        ]
        result = postprocess_shots(shots, episode=1)
        assert len(result) == 3
        assert result[0]["shot_id"] == "001"
        assert result[0]["duration"] == 5
        assert result[0]["episode"] == 1
        # 空 ID 自动填充
        assert result[1]["shot_id"] != ""
        # 重复 ID 自动去重
        assert result[2]["shot_id"] != "001"
        # duration 截断
        assert result[1]["duration"] == 8  # max 8
        # 未知 emotion 回退
        assert result[1]["emotion"] == "neutral"

    def test_strip_dialogue(self):
        """清理 action 中的对话"""
        from engines.utils.shot import strip_dialogue
        assert "你好" not in strip_dialogue('她微笑着说："你好呀"')
        assert "你好" not in strip_dialogue('他说：你好')
        # 保留非对话内容
        result = strip_dialogue("墙上写着欢迎光临")
        assert "欢迎光临" in result

    def test_validate_shot(self):
        """镜头校验"""
        from engines.content.storyboard import validate_shot
        assert validate_shot({}) != []  # 空镜头有错误
        assert validate_shot({"episode": 1, "shot_id": "001", "scene_name": "s",
                              "characters": "c", "action": "a", "dialogue": "d"}) == []
        errors = validate_shot({"episode": 1, "shot_id": "001", "scene_name": "s",
                                "characters": "c", "action": "a", "dialogue": "d", "duration": -1})
        assert any("duration" in e.lower() or "正数" in e for e in errors)


# ══════════════════════════════════════════════════════════
#  7. 一致性检查
# ══════════════════════════════════════════════════════════

class TestConsistencyChecker:
    """分镜一致性校验"""

    def test_duration_check(self):
        """时长校验"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency([{"shot_id": "001", "duration": 10}])
        assert any("时长" in e for e in errors)

    def test_shot_id_unique(self):
        """shot_id 唯一性"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency([
            {"shot_id": "001", "duration": 4},
            {"shot_id": "001", "duration": 4},
        ])
        assert any("重复" in e for e in errors)

    def test_character_exists(self):
        """角色存在性检查"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency(
            [{"shot_id": "001", "characters": "nonexistent", "duration": 4}],
            characters=[{"id": "alice"}])
        assert any("nonexistent" in e for e in errors)

    def test_scene_exists(self):
        """场景存在性检查"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency(
            [{"shot_id": "001", "scene_name": "nonexistent", "duration": 4}],
            scenes=[{"id": "room"}])
        assert any("nonexistent" in e for e in errors)

    def test_outfit_continuity(self):
        """服装连续性检查"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency([
            {"shot_id": "001", "scene_name": "s", "characters": "c", "outfit": "a", "duration": 4},
            {"shot_id": "002", "scene_name": "s", "characters": "c", "outfit": "b", "duration": 4},
        ])
        assert any("服装突变" in e for e in errors)

    def test_all_pass(self):
        """全部通过时无错误"""
        from engines.consistency.checker import check_consistency
        errors = check_consistency([{"shot_id": "001", "duration": 4, "emotion": "happy"}])
        assert errors == []


# ══════════════════════════════════════════════════════════
#  8. 角色圣经
# ══════════════════════════════════════════════════════════

class TestCharacterBible:
    """角色圣经系统"""

    def test_load_bible(self, project_dir, sample_character):
        """加载角色圣经"""
        from engines.consistency.bible import CharacterBible
        bible = CharacterBible(str(project_dir))
        data = bible.load("linxia")
        assert data["core_traits"] == "温柔但坚强"

    def test_get_context(self, project_dir, sample_character):
        """获取角色上下文"""
        from engines.consistency.bible import CharacterBible
        bible = CharacterBible(str(project_dir))
        ctx = bible.get_context("linxia")
        assert "温柔" in ctx

    def test_get_tags(self, project_dir, sample_character):
        """获取角色标签"""
        from engines.consistency.bible import CharacterBible
        bible = CharacterBible(str(project_dir))
        tags = bible.get_tags("linxia")
        assert "gentle" in tags or "resilient" in tags

    def test_empty_bible(self, project_dir):
        """不存在的角色返回空"""
        from engines.consistency.bible import CharacterBible
        bible = CharacterBible(str(project_dir))
        assert bible.get_context("nonexistent") == ""
        assert bible.get_tags("nonexistent") == ""

    def test_save_bible(self, project_dir, sample_character):
        """保存角色圣经"""
        from engines.consistency.bible import CharacterBible
        bible = CharacterBible(str(project_dir))
        bible.save("linxia", {"core_traits": "新性格", "habits": ["喝茶"]})
        data = bible.load("linxia")
        assert data["core_traits"] == "新性格"
        assert "喝茶" in data["habits"]


# ══════════════════════════════════════════════════════════
#  9. 多人同框
# ══════════════════════════════════════════════════════════

class TestMultiCharacter:
    """多人同框处理"""

    def test_single_character(self):
        """单角色"""
        from engines.utils.multi_char import MultiCharacterHandler
        h = MultiCharacterHandler()
        result = h.generate_multi_char_prompt([{"appearance_prompt_en": "1girl, long hair"}])
        assert "1girl" in result

    def test_two_characters(self):
        """双角色左右分布"""
        from engines.utils.multi_char import MultiCharacterHandler
        h = MultiCharacterHandler()
        result = h.generate_multi_char_prompt([
            {"appearance_prompt_en": "1girl"},
            {"appearance_prompt_en": "1boy"},
        ])
        assert "on the left" in result
        assert "on the right" in result


# ══════════════════════════════════════════════════════════
#  10. 字幕生成
# ══════════════════════════════════════════════════════════

class TestSubtitle:
    """SRT 字幕生成"""

    def test_generate_srt(self, tmp_dir):
        """基本 SRT 生成"""
        from post.subtitle import generate_srt
        shots = [
            {"shot_id": "001", "dialogue": "你好", "duration": 4},
            {"shot_id": "002", "dialogue": "世界", "duration": 3},
            {"shot_id": "003", "dialogue": "......", "duration": 2},  # 无台词
        ]
        output = str(tmp_dir / "test.srt")
        result = generate_srt(shots, output)
        assert os.path.exists(result)
        content = open(result).read()
        assert "你好" in content
        assert "世界" in content
        assert "......" not in content  # 无台词不生成字幕

    def test_generate_srt_bilingual(self, tmp_dir):
        """双语字幕"""
        from post.subtitle import generate_srt
        shots = [{"shot_id": "001", "dialogue": "你好", "dialogue_en": "Hello", "duration": 4}]
        output = str(tmp_dir / "test_bi.srt")
        result = generate_srt(shots, output, bilingual=True)
        content = open(result).read()
        assert "你好" in content
        assert "Hello" in content

    def test_generate_srt_empty(self, tmp_dir):
        """空分镜生成空字幕"""
        from post.subtitle import generate_srt
        output = str(tmp_dir / "empty.srt")
        generate_srt([], output)
        assert os.path.exists(output)


# ══════════════════════════════════════════════════════════
#  11. 配乐生成
# ══════════════════════════════════════════════════════════

class TestMusic:
    """配乐生成"""

    def test_template_music(self, tmp_dir):
        """ffmpeg 模板配乐"""
        from post.music import MusicGenerator
        gen = MusicGenerator()
        output = str(tmp_dir / "bgm.wav")
        result = gen._template(10, output, "happy")
        assert os.path.exists(result)
        assert os.path.getsize(result) > 0

    def test_template_different_moods(self, tmp_dir):
        """不同情绪生成不同配乐"""
        from post.music import MusicGenerator
        gen = MusicGenerator()
        for mood in ["happy", "sad", "angry"]:
            output = str(tmp_dir / f"bgm_{mood}.wav")
            gen._template(5, output, mood)
            assert os.path.exists(output)


# ══════════════════════════════════════════════════════════
#  12. 平台分发
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
#  13. 质量门禁
# ══════════════════════════════════════════════════════════

class TestQualityGate:
    """质量门禁"""

    def test_after_prepare_no_chars(self, project_dir):
        """无角色时检查通过"""
        from engines.quality_gate import check_quality
        issues = check_quality("after_prepare", str(project_dir))
        # 无角色/场景 = 无翻译缺失
        assert isinstance(issues, list)

    def test_after_prepare_missing_translation(self, project_dir, sample_character):
        """角色缺英文 prompt 时警告"""
        from engines.quality_gate import check_quality
        from infra.config import save_yaml
        # 创建一个缺英文 prompt 的角色
        char = {"character": {"id": "test", "name": "测试", "appearance": "测试角色外观描述足够长"}}
        save_yaml(project_dir / "config" / "characters" / "test.yaml", char)
        issues = check_quality("after_prepare", str(project_dir))
        warnings = [i for i in issues if i["severity"] == "warning"]
        assert len(warnings) > 0

    def test_unknown_stage(self, project_dir):
        """未知阶段返回空"""
        from engines.quality_gate import check_quality
        issues = check_quality("unknown_stage", str(project_dir))
        assert issues == []


# ══════════════════════════════════════════════════════════
#  14. Web API 端点
# ══════════════════════════════════════════════════════════

class TestWebAPI:
    """Web API 端点测试"""

    def test_create_app(self):
        """应用创建"""
        from web.app import create_app
        app = create_app()
        assert app.title == "AI 短剧工作台 v2"

    def test_system_status(self):
        """系统状态端点"""
        from web.app import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data

    def test_characters_crud(self, tmp_dir):
        """角色 CRUD"""
        from web.app import create_app
        from fastapi.testclient import TestClient
        # 需要设置活动项目
        os.environ.setdefault("AI_DRAMA_DB_DSN", "")
        app = create_app()
        client = TestClient(app)
        # 列表
        resp = client.get("/api/characters")
        assert resp.status_code == 200

    def test_config_get(self):
        """配置读取"""
        from web.app import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════
#  15. 导入系统
# ══════════════════════════════════════════════════════════

class TestImportSystem:
    """剧本导入"""

    def test_import_plan_validation(self):
        """导入计划校验"""
        from infra.models import ImportPlan, ImportValidator
        plan = ImportPlan(
            characters=[{"id": "c1", "name": "Alice", "appearance": "young woman with long hair"}],
            scenes=[{"id": "s1", "name": "Room", "description": "a modern living room"}],
            shots=[{"shot_id": "001", "scene_name": "Room", "characters": "Alice", "action": "Alice walks in slowly"}],
        )
        errors = ImportValidator.validate_references(plan)
        assert errors == []

    def test_import_plan_missing_ref(self):
        """引用不存在的角色报错"""
        from infra.models import ImportPlan, ImportValidator
        plan = ImportPlan(
            characters=[],
            scenes=[],
            shots=[{"shot_id": "001", "scene_name": "nonexistent", "characters": "nonexistent", "action": "walks in slowly"}],
        )
        errors = ImportValidator.validate_references(plan)
        assert any("nonexistent" in e for e in errors)

    def test_import_plan_duplicate_shot_id(self):
        """重复 shot_id 报错"""
        from infra.models import ImportPlan, ImportValidator
        plan = ImportPlan(
            shots=[
                {"shot_id": "001", "scene_name": "s", "action": "walks in slowly"},
                {"shot_id": "001", "scene_name": "s", "action": "sits down"},
            ],
        )
        errors = ImportValidator.validate_references(plan)
        assert any("重复" in e for e in errors)

    def test_translation_status(self):
        """翻译状态检测"""
        from infra.models import ImportPlan, get_translation_status
        plan = ImportPlan(
            characters=[{"id": "c1", "name": "Alice", "appearance": "young woman with long hair",
                         "appearance_prompt_en": "1girl, young"}],
            scenes=[{"id": "s1", "name": "Room", "description": "a modern living room with sofa"}],
            shots=[{"shot_id": "001", "scene_name": "Room", "characters": "Alice", "action": "Alice walks in slowly"}],
        )
        status = get_translation_status(plan)
        assert status["complete"] is False  # 场景和镜头缺翻译
        assert len(status["missing"]["scenes"]) == 1
        assert len(status["missing"]["shots"]) == 1


# ══════════════════════════════════════════════════════════
#  16. 模型注册表
# ══════════════════════════════════════════════════════════

class TestModelRegistry:
    """模型注册表"""

    def test_registry_load(self):
        """注册表加载"""
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        assert reg.get_defaults()["image_backend"] == "flux"

    def test_registry_backends(self):
        """后端列表"""
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        tts = reg.list_backend_names("tts")
        assert "mimo-voicedesign" in tts
        img = reg.list_backend_names("image")
        assert "cosmos" in img
        assert "flux" in img

    def test_registry_workflow(self):
        """工作流映射"""
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        assert reg.get_image_workflow("cosmos") == "cosmos_predict2_2B_t2i.json"
        assert reg.get_image_workflow("sd15") == "01_first_frame_sd15.json"

    def test_registry_consistency(self):
        """一致性方案"""
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        assert reg.get_consistency_default("flux") == "pulid_flux"
        assert reg.get_consistency_default("sd15") == "ip_adapter"
        assert reg.get_consistency_default("cosmos") == "none"

    def test_registry_model_limits(self):
        """模型限制"""
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        limits = reg.get_model_limits("Qwen/Qwen2.5-7B-Instruct")
        assert limits["context_window"] == 32768


# ══════════════════════════════════════════════════════════
#  17. 后端注册表
# ══════════════════════════════════════════════════════════

class TestServiceRegistry:
    """服务注册表 + DI 容器"""

    def test_registry_singleton(self):
        """全局单例"""
        from api.registry import registry
        from api import _ensure_registered
        _ensure_registered()
        assert registry is not None
        tts_list = registry.list_by_type("tts")
        assert len(tts_list) > 0

    def test_registry_create(self):
        """后端创建"""
        from api.registry import registry
        from api import _ensure_registered
        _ensure_registered()
        config = {"models": {"tts_backend": "mimo-voicedesign"}, "timeouts": {}, "project_dir": ""}
        backend = registry.create("tts", "mimo-voicedesign", config)
        assert backend is not None


# ══════════════════════════════════════════════════════════
#  18. 基础设施
# ══════════════════════════════════════════════════════════

class TestInfrastructure:
    """基础设施组件"""

    def test_retry(self):
        """重试机制"""
        from infra.concurrency.executor import safe_run
        calls = {"count": 0}

        def flaky():
            calls["count"] += 1
            if calls["count"] < 3:
                raise ValueError("not yet")
            return "ok"

        result = safe_run(flaky, retries=3, base_delay=0.01)
        assert result == "ok"
        assert calls["count"] == 3

    def test_json_parse(self):
        """JSON 解析容错"""
        from infra.json_parse import parse_llm_json
        # 正常
        assert parse_llm_json('{"a": 1}') == {"a": 1}
        # markdown 代码块
        assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
        # 前后多余文字
        assert parse_llm_json('Here is the result: {"a": 1} done.') == {"a": 1}
        # 无效
        assert parse_llm_json("not json at all") is None

    def test_constants(self):
        """常量完整性"""
        from infra.constants import (
            VALID_EMOTIONS, VALID_SHOT_TYPES, VALID_CAMERAS,
            STATUS_DONE, STATUS_ERROR, EMOTION_MAP, SHOT_TYPE_MAP, CAMERA_MAP,
        )
        assert len(VALID_EMOTIONS) > 5
        assert len(VALID_SHOT_TYPES) > 5
        assert len(VALID_CAMERAS) > 3
        assert STATUS_DONE == "done"
        assert STATUS_ERROR == "error"
        assert "happy" in EMOTION_MAP
        assert "特写" in SHOT_TYPE_MAP
        assert "固定" in CAMERA_MAP


# ══════════════════════════════════════════════════════════
#  19. 前端静态资源
# ══════════════════════════════════════════════════════════

class TestFrontend:
    """前端静态资源"""

    def test_index_html(self):
        """index.html 存在且包含关键元素"""
        from pathlib import Path
        index = Path(__file__).parent.parent / "web" / "static" / "index.html"
        assert index.exists()
        content = index.read_text()
        assert "AI 短剧" in content
        assert "app.js" in content

    def test_js_files(self):
        """JS 文件存在"""
        from pathlib import Path
        js_dir = Path(__file__).parent.parent / "web" / "static" / "js"
        assert (js_dir / "app.js").exists()
        assert (js_dir / "core.js").exists()
        assert (js_dir / "i18n.js").exists()

    def test_css_file(self):
        """CSS 文件存在"""
        from pathlib import Path
        css = Path(__file__).parent.parent / "web" / "static" / "css" / "style.css"
        assert css.exists()
        content = css.read_text()
        # 深色主题 CSS 包含 :root 变量定义
        assert "--bg:" in content
        assert "--fg:" in content


# ══════════════════════════════════════════════════════════
#  20. 配置文件完整性
# ══════════════════════════════════════════════════════════

class TestConfigFiles:
    """配置文件完整性"""

    def test_system_yaml(self):
        """system.yaml 可加载"""
        from infra.config import load_config, SYSTEM_CONFIG_PATH
        data = load_config(SYSTEM_CONFIG_PATH)
        assert "comfyui" in data
        assert "models" in data
        assert "llm" in data

    def test_models_registry(self):
        """models_registry.yaml 可加载"""
        from infra.config import load_config, REGISTRY_PATH
        data = load_config(REGISTRY_PATH)
        assert "tts_backends" in data
        assert "image_backends" in data
        assert "defaults" in data

    def test_prompt_templates(self):
        """prompt_templates.yaml 可加载"""
        from infra.config import load_config, PROMPT_TEMPLATES_PATH
        data = load_config(PROMPT_TEMPLATES_PATH)
        assert "first_frame_tag" in data
        assert "storyboard_system" in data
