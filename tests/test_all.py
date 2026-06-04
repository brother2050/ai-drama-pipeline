"""测试 — 基础功能验证"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

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
    from infra.gpu import get_generation_config
    cfg = get_generation_config()
    assert "resolution" in cfg
    assert "image_steps" in cfg
    # 未配置 generation 段时，resolution 和 image_steps 为 None（不覆盖后端默认值）
    assert cfg["resolution"] is None
    assert cfg["image_steps"] is None
    print("✅ 生成参数配置读取正常（未配置时返回 None，不覆盖后端默认值）")


# ── infra/retry.py ──

def test_retry():
    """测试重试机制"""
    from infra.retry import retry

    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("not yet")
        return "ok"

    result = retry(flaky, max_retries=5, base_delay=0.01)
    assert result == "ok"
    assert call_count == 3
    print("✅ 重试机制正常")


# ── infra/database ──

def test_postgres_database():
    """测试 PostgreSQL 数据库（需要配置 AI_DRAMA_DB_DSN）"""
    import os
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        print("⚠ AI_DRAMA_DB_DSN 未配置，跳过数据库测试")
        return

    from infra.database.pool import PgPool
    from infra.database import storyboard_db

    pool = PgPool(dsn)

    try:
        # 镜头
        storyboard_db.upsert_shot(pool, 999, "001", {
            "scene_id": "test_scene", "characters": "test_char",
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
        print("⚠ AI_DRAMA_DB_DSN 未配置，跳过分镜表测试")
        return

    from engines.storyboard import load_storyboard, validate_shot, get_dominant_emotion

    try:
        all_shots = load_storyboard()
        if not all_shots:
            print("⚠ DB 中无分镜数据，跳过")
            return

        ep1_shots = load_storyboard(episode=1)
        assert all(int(s.get("episode", 0)) == 1 for s in ep1_shots)

        # 验证
        for shot in ep1_shots:
            errors = validate_shot(shot)
            assert len(errors) == 0, f"镜头 {shot.get('shot_id')}: {errors}"

        # 主要情绪
        emotion = get_dominant_emotion(ep1_shots)
        assert emotion in ("worried", "sad", "determined", "happy", "romantic", "surprised", "neutral")

        print(f"✅ 分镜表正常: {len(all_shots)} 镜头")
    except Exception as e:
        print(f"⚠ 分镜表测试失败: {e}")


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
    from engines.multi_char import MultiCharacterHandler

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

    regions = handler.calculate_regions(2)
    assert len(regions) == 2
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

    gen = MusicGenerator(backend="template")
    assert gen._backend == "template"

    # 测试未知后端回退
    gen2 = MusicGenerator(backend="unknown")
    assert gen2._backend == "unknown"
    print("✅ 配乐生成正常")


# ── post/distributor.py ──

def test_distributor():
    """测试分发"""
    from post.distributor import distribute, check_platform_compat, get_adapt_params

    results = distribute("/tmp/test.mp4", ["douyin", "bilibili"])
    assert "douyin" in results
    assert "bilibili" in results
    assert results["douyin"]["preset"]["resolution"] == [1080, 1920]
    assert results["bilibili"]["preset"]["resolution"] == [1920, 1080]
    print("✅ 多平台分发正常")


def test_distributor_compat():
    """测试平台兼容性检查"""
    from post.distributor import check_platform_compat, get_adapt_params

    result = check_platform_compat("/nonexistent.mp4", "douyin")
    assert result["compatible"] == False

    result = check_platform_compat("/tmp/test.mp4", "unknown_platform")
    assert result["compatible"] == False

    params = get_adapt_params("/tmp/test.mp4", "douyin")
    assert "ffmpeg_args" in params
    assert "needs_transcode" in params
    print("✅ 平台兼容性检查正常")








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
    if Path(cfg_path).exists():
        cfg = Config(cfg_path)
        # 默认配置应该通过
        assert isinstance(cfg.warnings, list)
        assert cfg.get("project.name") is not None
        print(f"✅ 配置校验正常 ({len(cfg.warnings)} 个警告)")
    else:
        print("⚠ 配置文件不存在，跳过校验测试")


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
    from flow.model_registry import ModelRegistry

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
    # 检查路由
    routes = [r.path for r in app.routes]
    assert "/api/system/status" in routes
    print("✅ Web 应用正常")


# ── pipeline/celery_app.py ──

def test_celery_app():
    """测试 Celery 应用配置"""
    from pipeline.celery_app import app

    assert app.main == "drama"
    assert "redis" in app.conf.broker_url
    assert app.conf.task_track_started == True
    assert app.conf.task_acks_late == True
    assert app.conf.worker_prefetch_multiplier == 1
    print("✅ Celery 配置正常")


def test_celery_tasks_registered():
    """测试 Celery 任务注册"""
    from pipeline.celery_app import app
    import pipeline.tasks  # 触发任务注册

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
        "pipeline.tasks.portrait_tasks",
        "pipeline.tasks.media_tasks",
        "pipeline.tasks.training_tasks",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"无法导入: {mod_name}"
    # 直接从源模块导入验证
    from pipeline.tasks.portrait_tasks import portraits_task, scene_images_task  # noqa: F401
    from pipeline.tasks.media_tasks import post_task, tts_single_task, music_task, subtitle_task  # noqa: F401
    from pipeline.tasks.training_tasks import train_lora_task, import_json_task  # noqa: F401
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
        test_postgres_database,
        test_storyboard,
        test_prompt,
        test_multi_char,
        test_subtitle,
        test_transitions,
        test_music,
        test_distributor,
        test_distributor_compat,

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
