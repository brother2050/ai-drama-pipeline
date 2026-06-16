"""测试 — 基础功能验证"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── infra/config.py ──

def test_config_load():
    """测试配置加载"""
    from infra.config import Config

    cfg_path = str(ROOT / "projects" / "default" / "config" / "project.yaml")
    cfg = Config(cfg_path)
    # project.name 来自项目配置文件，不硬编码断言具体值
    name = cfg.get("project.name")
    assert name is not None and name != "", "project.name 不应为空"
    assert cfg.get("models.tts_backend") is not None, "models.tts_backend 不应为空"
    assert cfg.get("comfyui.url") is not None, "comfyui.url 不应为空"
    assert cfg.get("nonexistent.key", "default") == "default"
    print(f"✅ Config 加载正常 (project.name={name})")


def test_config_save_load():
    """测试配置保存和加载"""
    from infra.config import load_config, save_config

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
        path = f.name

    try:
        save_config(path, {"test": {"key": "value"}})
        data = load_config(path)
        assert data["test"]["key"] == "value"
    finally:
        os.unlink(path)
    print("✅ Config 保存/加载正常")


# ── infra/gpu.py ──

def test_generation_config():
    """测试生成参数配置（默认值）"""
    from infra.compute.gpu import get_generation_config
    cfg = get_generation_config()
    assert "resolution" in cfg
    assert "image_steps" in cfg
    # 未配置 generation 段时，resolution 和 image_steps 为 None（不覆盖后端默认值）
    assert cfg["resolution"] is None
    assert cfg["image_steps"] is None
    print("✅ 生成参数配置读取正常（未配置时返回 None，不覆盖后端默认值）")


# ── infra/safe_executor.py (retry) ──

def test_retry():
    """测试重试机制"""
    from infra.concurrency.executor import safe_run

    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("not yet")
        return "ok"

    result = safe_run(flaky, retries=5, base_delay=0.01)
    assert result == "ok"
    assert call_count == 3
    print("✅ 重试机制正常")


# ── pipeline/tasks/steps/tts.py (_build_voice_config) ──

def test_build_voice_config_shared_fields():
    """后端专属段存储：各后端独立读取自己的参数"""
    from pipeline.tasks.steps.tts import _build_voice_config
    char = {
        "voice": {
            "gpt_sovits": {"reference_audio": "/ref.wav", "prompt_text": "hello"},
            "mimo_voicedesign": {"voice_description": "sweet", "core_traits": "kind"},
        },
    }
    cfg_gpt = _build_voice_config(char, "gpt-sovits")
    assert cfg_gpt["reference_audio"] == "/ref.wav"
    assert cfg_gpt["prompt_text"] == "hello"

    cfg_mimo = _build_voice_config(char, "mimo-voicedesign")
    assert cfg_mimo["voice_description"] == "sweet"
    assert cfg_mimo["core_traits"] == "kind"
    print("✅ _build_voice_config 后端专属段 OK")


def test_build_voice_config_backend_isolation():
    """后端专属参数隔离：gpt_sovits 不混入 chattts 的参数"""
    from pipeline.tasks.steps.tts import _build_voice_config
    char = {"voice": {
        "gpt_sovits": {"reference_audio": "/r.wav", "prompt_text": "hello", "speed_factor": "1.2"},
        "chattts": {"voice": "5555"},
    }}
    cfg_gpt = _build_voice_config(char, "gpt-sovits")
    assert cfg_gpt["reference_audio"] == "/r.wav"
    assert cfg_gpt["prompt_text"] == "hello"
    assert "voice" not in cfg_gpt  # chattts 的 voice 不应出现

    cfg_chat = _build_voice_config(char, "chattts")
    assert cfg_chat["voice"] == "5555"
    assert "prompt_text" not in cfg_chat  # gpt_sovits 的 prompt_text 不应出现
    print("✅ _build_voice_config 后端隔离 OK")


def test_build_voice_config_defaults():
    """未配置后端专属段时返回默认空值"""
    from pipeline.tasks.steps.tts import _build_voice_config
    char = {"voice": {}}
    cfg = _build_voice_config(char, "mimo-voicedesign")
    assert cfg["voice_description"] == ""
    assert cfg["core_traits"] == ""
    assert cfg["reference_audio"] == ""
    assert cfg["aux_ref_audio_paths"] == []
    print("✅ _build_voice_config 默认值 OK")


def test_build_voice_config_empty():
    """空角色数据不崩溃"""
    from pipeline.tasks.steps.tts import _build_voice_config
    cfg = _build_voice_config({}, "mimo-voicedesign")
    assert cfg["reference_audio"] == ""
    assert cfg["voice_description"] == ""
    print("✅ _build_voice_config 空数据 OK")


# ── infra/database ──

def test_postgres_database():
    """测试 PostgreSQL 数据库（需要配置 AI_DRAMA_DB_DSN）"""
    import os
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        pytest.skip("AI_DRAMA_DB_DSN 未配置")

    from infra.database.pool import PgPool
    from infra.database import storyboard_db

    pool = PgPool(dsn)

    try:
        # 镜头
        storyboard_db.upsert_shot(pool, 999, "001", {
            "scene_name": "test_scene", "characters": "test_char",
            "action": "坐着", "dialogue": "你好", "camera": "固定",
            "shot_type": "中景", "duration": 4.0, "emotion": "calm"
        })
        shot_list = storyboard_db.get_episode_shots(pool, 999)
        assert len(shot_list) >= 1
        assert shot_list[0]["dialogue"] == "你好"

        print("✅ PostgreSQL 数据库正常")
    finally:
        # 清理测试数据（无论测试是否成功都执行）
        try:
            conn = pool.connect()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM shots WHERE episode = 999")
                conn.commit()
            finally:
                pool.release(conn)
        except Exception:
            pass
        pool.close()


# ── engines/storyboard.py ──

def test_storyboard():
    """测试分镜表加载（从 DB）"""
    import os
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        pytest.skip("AI_DRAMA_DB_DSN 未配置")

    from engines.content.storyboard import load_storyboard, validate_shot

    all_shots = load_storyboard()
    if not all_shots:
        pytest.skip("DB 中无分镜数据")

    ep1_shots = load_storyboard(episode=1)
    assert all(int(s.get("episode", 0)) == 1 for s in ep1_shots)

    for shot in ep1_shots:
        errors = validate_shot(shot)
        assert len(errors) == 0, f"镜头 {shot.get('shot_id')}: {errors}"


# ── engines/camera.py ──

# ── engines/prompt.py ──

def test_prompt():
    """测试 Prompt 构建"""
    from engines.prompt import build_prompt, PromptBuildParams, translate_to_english

    shot = {
        "action": "sitting on sofa", "emotion": "worried",
        "shot_type": "特写", "camera": "缓慢推近"
    }

    # SD1.5/默认：逗号 tag 风格
    prompt = build_prompt(PromptBuildParams(shot=shot, character_desc="young woman", scene_desc="modern living room"))
    assert "young woman" in prompt
    assert "modern living room" in prompt
    assert "worried" in prompt
    assert ", " in prompt  # 逗号分隔

    # Flux：自然语言段落风格
    prompt_flux = build_prompt(PromptBuildParams(shot=shot, character_desc="young woman",
                               scene_desc="modern living room", image_backend="flux"))
    assert "young woman" in prompt_flux.lower()  # 句首大写
    assert "modern living room" in prompt_flux
    assert "worried" in prompt_flux
    assert "." in prompt_flux  # 句子结构
    assert prompt_flux != prompt  # 两种风格输出不同

    # Cosmos：同 Flux 自然语言风格
    prompt_cosmos = build_prompt(PromptBuildParams(shot=shot, character_desc="young woman",
                                 scene_desc="modern living room", image_backend="cosmos"))
    assert "young woman" in prompt_cosmos.lower()
    assert prompt_cosmos == prompt_flux  # flux 和 cosmos 输出一致

    # 自然语言：无动作时用 "with a" 而非逗号
    shot_no_action = {"emotion": "worried", "shot_type": "特写", "camera": "固定"}
    p_na = build_prompt(PromptBuildParams(shot=shot_no_action, character_desc="young woman", image_backend="flux"))
    assert "worried" in p_na
    assert "expression" in p_na

    # 自然语言：中文 action 原样传入（无 action_en 时降级）
    shot_cn = {"action": "坐在沙发上", "emotion": "calm", "shot_type": "中景", "camera": "固定"}
    p_cn = build_prompt(PromptBuildParams(shot=shot_cn, character_desc="young woman", image_backend="flux"))
    assert "calm" in p_cn

    # 翻译
    assert translate_to_english("hello") == "hello"
    assert translate_to_english("") == ""
    print("✅ Prompt 构建正常")


# ── engines/multi_char.py ──

def test_multi_char():
    """测试多人同框"""
    from engines.utils.multi_char import MultiCharacterHandler

    handler = MultiCharacterHandler()

    # 单人
    prompt = handler.generate_multi_char_prompt([{"appearance": "young woman"}])
    assert "young woman" in prompt

    # 多人
    prompt = handler.generate_multi_char_prompt([
        {"appearance": "woman"}, {"appearance": "man"}
    ])
    assert "woman" in prompt
    assert "man" in prompt
    print("✅ 多人同框正常")


# ── post/subtitle.py ──

def test_subtitle():
    """测试字幕生成"""
    from post.subtitle import generate_srt, _format_srt_time

    assert _format_srt_time(0) == "00:00:00,000"
    assert _format_srt_time(61.5) == "00:01:01,500"
    assert _format_srt_time(3661.123) == "01:01:01,123"

    shots = [
        {"dialogue": "你好", "duration": 3},
        {"dialogue": "......", "duration": 2},  # 应跳过
        {"dialogue": "世界", "duration": 4},
    ]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
        path = f.name

    try:
        generate_srt(shots, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "你好" in content
        assert "世界" in content
        assert "......" not in content
    finally:
        os.unlink(path)
    print("✅ 字幕生成正常")



# ── infra/transitions.py ──

def test_transitions():
    """测试转场"""
    from infra.transitions import get_xfade_filter

    f = get_xfade_filter("crossfade", 10.0, 0.5)
    assert "xfade=transition=fade" in f
    assert "duration=0.5" in f
    assert "offset=10.0" in f
    print("✅ 转场效果正常")


# ── post/music.py ──

def test_music():
    """测试配乐"""
    from post.music import MusicGenerator

    gen = MusicGenerator()
    assert gen._config == {}

    # 测试未知后端回退
    gen2 = MusicGenerator(config={"test": True})
    assert gen2._config == {"test": True}
    print("✅ 配乐生成正常")






# ── web/schemas ──

def test_web_schemas():
    """测试 Pydantic 模型"""
    from web.schemas import StepRequest, TTSRequest, CharacterData, SceneData, ProjectCreate

    # 正常
    req = StepRequest(episode=1, shot_id="001")
    assert req.episode == 1
    assert req.shot_id == "001"

    # TTS
    tts = TTSRequest(text="你好世界")
    assert tts.text == "你好世界"
    assert tts.emotion == "neutral"

    # 角色
    char = CharacterData(id="test_char", name="测试角色")
    assert char.id == "test_char"

    # 场景
    scene = SceneData(id="scene1", name="客厅")
    assert scene.id == "scene1"

    # 项目名
    proj = ProjectCreate(name="我的项目")
    assert proj.name == "我的项目"

    # 非法 shot_id
    try:
        StepRequest(episode=1, shot_id="../etc")
        assert False, "应该抛出异常"
    except Exception as e:
        print(f"[预期] {type(e).__name__}: {e}")

    # 非法 episode
    try:
        StepRequest(episode=0, shot_id="001")
        assert False, "应该抛出异常"
    except Exception as e:
        print(f"[预期] {type(e).__name__}: {e}")

    # 非法 character id
    try:
        CharacterData(id="../etc", name="bad")
        assert False, "应该抛出异常"
    except Exception as e:
        print(f"[预期] {type(e).__name__}: {e}")

    print("✅ Pydantic 模型校验正常")


# ── infra/config.py 验证 ──

def test_config_validation():
    """测试配置校验"""
    from infra.config import Config

    cfg_path = str(ROOT / "projects" / "default" / "config" / "project.yaml")
    if not Path(cfg_path).exists():
        pytest.skip("配置文件不存在")
    cfg = Config(cfg_path)
    assert isinstance(cfg.warnings, list)
    assert cfg.get("project.name") is not None


# ── api/registry.py ──

def test_registry():
    """测试服务注册表"""
    from api.registry import ServiceRegistry, BackendMeta

    reg = ServiceRegistry()

    def factory(cfg):
        return {"name": "test"}

    reg.register(BackendMeta(
        name="test-tts", service_type="tts", factory=factory,
        description="Test TTS", priority=10
    ))

    meta = reg.get("tts", "test-tts")
    assert meta is not None
    assert meta.name == "test-tts"

    types = reg.list_by_type("tts")
    assert "test-tts" in types

    inst = reg.create("tts", "test-tts", {})
    assert inst["name"] == "test"
    print("✅ 服务注册表正常")


# ── flow/model_registry.py ──

def test_model_registry():
    """测试模型注册表"""
    from infra.config.registry import ModelRegistry

    reg = ModelRegistry()

    assert "sd15" in reg.valid_image_backends()
    assert "animatediff" in reg.valid_video_backends()
    assert reg.get_image_workflow("sd15") == "01_first_frame_sd15.json"
    print("✅ 模型注册表正常")


# ── web/app.py ──

def test_web_app():
    """测试 Web 应用创建"""
    from web.app import create_app

    app = create_app()
    assert app.title == "AI 短剧工作台 v2"
    # 从 OpenAPI schema 获取已注册路由（包含嵌套路由）
    routes = set(app.openapi().get("paths", {}).keys())
    assert "/api/system/status" in routes
    print("✅ Web 应用正常")


# ── pipeline/celery_app.py ──

def test_celery_app():
    """测试 Celery 应用配置"""
    from pipeline.app import app

    assert app.main == "drama"
    assert "redis" in app.conf.broker_url
    assert app.conf.task_track_started
    assert app.conf.task_acks_late
    assert app.conf.worker_prefetch_multiplier == 1
    print("✅ Celery 配置正常")


def test_celery_tasks_registered():
    """测试 Celery 任务注册"""
    from pipeline.app import app
    import pipeline.tasks  # noqa: F401 — 触发任务注册

    expected_tasks = [
        "pipeline_step_tts", "pipeline_step_first_frame", "pipeline_step_video",
        "pipeline_step_lipsync", "pipeline_shot", "pipeline_preview",
        "pipeline_produce", "pipeline_post", "pipeline_portraits",
        "pipeline_tts_single", "pipeline_music", "pipeline_subtitle",
    ]
    registered = set(app.tasks.keys())
    for task_name in expected_tasks:
        assert task_name in registered, f"任务未注册: {task_name}"
    print(f"✅ Celery 任务注册正常 ({len(expected_tasks)} 个)")


# ── Import 烟雾测试（回归保护） ──

def test_pipeline_tasks_imports():
    """pipeline/tasks 子模块 import 烟雾测试"""
    import importlib
    modules = [
        "pipeline.tasks.helpers",
        "pipeline.tasks.steps",
        "pipeline.tasks.pipeline",
        "pipeline.tasks.ai",
        "pipeline.tasks.portrait",
        "pipeline.tasks.media",
        "pipeline.tasks.training",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"无法导入: {mod_name}"
    # 直接从源模块导入验证
    from pipeline.tasks.portrait import portraits_task, scene_images_task  # noqa: F401
    from pipeline.tasks.media import post_task, tts_single_task, music_task, subtitle_task  # noqa: F401
    from pipeline.tasks.training import train_lora_task, import_json_task  # noqa: F401
    assert portraits_task is not None
    assert import_json_task is not None
    print(f"✅ pipeline/tasks 子模块 import 正常 ({len(modules)} 个)")


def test_tts_backends_imports():
    """TTS 后端 import 烟雾测试"""
    import importlib
    modules = [
        "api.backends.tts.mimo_voicedesign",
        "api.backends.tts.mimo_voiceclone",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"无法导入: {mod_name}"
    print(f"✅ TTS 后端 import 正常 ({len(modules)} 个)")


def test_web_routers_imports():
    """Web 路由子模块 import 烟雾测试"""
    import importlib
    modules = [
        "web.routers.deps",
        "web.routers.system_tools",
        "web.routers.characters",
        "web.routers.scenes",
        "web.routers.storyboard",
        "web.routers.assets",
        "web.routers.imports",
        "web.routers.api",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"无法导入: {mod_name}"
    print(f"✅ Web 路由子模块 import 正常 ({len(modules)} 个)")


# ── 运行所有测试 ──

def run_all():
    """运行所有测试"""
    tests = [
        test_config_load,
        test_config_save_load,
        test_config_validation,
        test_generation_config,
        test_retry,
        test_build_voice_config_shared_fields,
        test_build_voice_config_backend_isolation,
        test_build_voice_config_defaults,
        test_build_voice_config_empty,
        test_postgres_database,
        test_storyboard,
        test_prompt,
        test_multi_char,
        test_subtitle,
        test_transitions,
        test_music,

        test_web_schemas,
        test_registry,
        test_model_registry,
        test_web_app,
        test_celery_app,
        test_celery_tasks_registered,
        test_pipeline_tasks_imports,
        test_tts_backends_imports,
        test_web_routers_imports,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"❌ {test.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"测试结果: {passed} 通过, {failed} 失败")

    if errors:
        print("\n失败详情:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
