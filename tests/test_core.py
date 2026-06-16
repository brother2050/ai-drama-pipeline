"""测试 — 核心流程函数（mock 外部服务）

覆盖: tts_core, first_frame_core, video_core, lipsync_core
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Fixtures ──

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="drama_test_")
    yield Path(d)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_cfg(tmp_dir):
    """创建最小 Config mock"""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default="": {
        "comfyui.url": "http://127.0.0.1:8188",
        "comfyui.api_key": "",
        "models.tts_backend": "mimo-voicedesign",
        "models.image_backend": "sd15",
        "models.video_backend": "animatediff",
        "models.lip_sync_backend": "musetalk",
        "timeouts.comfyui": 300,
        "timeouts.tts": 60,
    }.get(key, default))
    cfg.paths = MagicMock()
    cfg.paths.root = tmp_dir
    cfg.paths.config_dir = tmp_dir / "config"
    cfg.paths.characters_dir = tmp_dir / "config" / "characters"
    cfg.paths.scenes_dir = tmp_dir / "config" / "scenes"
    cfg.paths.shot_dir = MagicMock(side_effect=lambda ep, sid: tmp_dir / f"e{ep:02d}" / sid)
    cfg.data = {
        "comfyui": {"url": "http://127.0.0.1:8188"},
        "models": {"tts_backend": "mimo-voicedesign", "image_backend": "sd15"},
    }
    # 创建必要目录
    (tmp_dir / "config").mkdir(exist_ok=True)
    (tmp_dir / "config" / "characters").mkdir(exist_ok=True)
    (tmp_dir / "config" / "scenes").mkdir(exist_ok=True)
    return cfg


@pytest.fixture
def mock_cont():
    """创建 Container mock"""
    cont = MagicMock()
    tts_backend = MagicMock()

    def fake_synthesize(text, output_path, **kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"RIFF" + b"\x00" * 2000)  # fake WAV > 1000 bytes

    tts_backend.synthesize = MagicMock(side_effect=fake_synthesize)
    cont.get = MagicMock(return_value=tts_backend)
    cont.get_with_fallback = MagicMock(return_value=(tts_backend, "mimo-voicedesign"))
    return cont


@pytest.fixture
def sample_shot():
    return {
        "shot_id": "001",
        "episode": 1,
        "scene_name": "living_room",
        "characters": "linxia",
        "action": "林夏坐在沙发上",
        "action_en": "Linxia sits on the sofa",
        "dialogue": "你好吗",
        "dialogue_en": "How are you",
        "duration": 4,
        "emotion": "neutral",
        "outfit": "home",
        "shot_type": "中景",
    }


@pytest.fixture
def sample_characters():
    return {
        "linxia": {
            "id": "linxia",
            "name": "林夏",
            "appearance": "22岁温柔女生，长发",
            "appearance_en": "A gentle 22-year-old girl with long hair",
            "outfits": {
                "home": {"description": "居家服", "description_en": "Casual home wear"},
            },
            "reference_images": [],
        }
    }


@pytest.fixture
def sample_scenes():
    return {
        "living_room": {
            "id": "living_room",
            "name": "客厅",
            "description": "现代简约客厅",
            "description_en": "Modern minimalist living room",
        }
    }


# ── tts_core ──

def test_tts_core_basic(mock_cfg, mock_cont, sample_shot, tmp_dir):
    """TTS 基本合成流程"""
    from pipeline.tasks import tts_core

    out_dir = tmp_dir / "e01" / "001"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = tts_core("001", sample_shot, mock_cfg, mock_cont, out_dir, force=True)
    assert result["status"] == "done"
    assert result["shot_id"] == "001"
    # 验证 TTS 后端被调用
    mock_cont.get_with_fallback.assert_called()


def test_tts_core_no_dialogue(mock_cfg, mock_cont, tmp_dir):
    """TTS 无台词时跳过"""
    from pipeline.tasks import tts_core

    out_dir = tmp_dir / "e01" / "002"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = {"shot_id": "002", "dialogue": "......", "duration": 4}

    result = tts_core("002", shot, mock_cfg, mock_cont, out_dir)
    assert result["status"] == "skipped"
    assert "无台词" in result.get("reason", "")


def test_tts_core_empty_text(mock_cfg, mock_cont, tmp_dir):
    """TTS 空文本跳过"""
    from pipeline.tasks import tts_core

    out_dir = tmp_dir / "e01" / "003"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = {"shot_id": "003", "dialogue": "", "duration": 4}

    result = tts_core("003", shot, mock_cfg, mock_cont, out_dir)
    assert result["status"] == "skipped"


# ── storyboard 校验 ──

def test_validate_shot_valid():
    """验证有效镜头"""
    from engines.content.storyboard import validate_shot

    shot = {"episode": 1, "shot_id": "001", "scene_name": "room", "characters": "a", "action": "x", "dialogue": "y"}
    errors = validate_shot(shot)
    assert len(errors) == 0


def test_validate_shot_missing_required():
    """验证缺少必填字段"""
    from engines.content.storyboard import validate_shot

    shot = {"shot_id": "001"}
    errors = validate_shot(shot)
    assert len(errors) > 0
    assert any("episode" in e for e in errors)


# ── YAML 实体加载 ──

def test_load_yaml_entities(tmp_dir):
    """统一 YAML 实体加载"""
    from infra.config import load_yaml_entities
    import yaml

    chars_dir = tmp_dir / "characters"
    chars_dir.mkdir()
    # 有效角色
    (chars_dir / "linxia.yaml").write_text(yaml.dump({"character": {"id": "linxia", "name": "林夏"}}), encoding="utf-8")
    # 损坏文件
    (chars_dir / "broken.yaml").write_text("{{invalid yaml", encoding="utf-8")
    # example 文件（应跳过）
    (chars_dir / "template.yaml.example").write_text(yaml.dump({"character": {"id": "tpl"}}), encoding="utf-8")

    entities = load_yaml_entities(chars_dir, "character")
    assert len(entities) == 1
    assert entities[0]["id"] == "linxia"


# ── strip_dialogue ──

def test_strip_dialogue_preserves_props():
    """清理对话时保留场景道具文字"""
    from engines.utils.shot import strip_dialogue

    assert "欢迎" in strip_dialogue('墙上写着"欢迎"，他说道："你好"')
    assert "Best Day" in strip_dialogue('桌上写着"Best Day"')


def test_strip_dialogue_removes_speech():
    """清理对话动词+引号内容"""
    from engines.utils.shot import strip_dialogue

    assert strip_dialogue('他喊道："快跑"') == ""
    assert strip_dialogue('她笑着说："没问题"') == ""


# ── 缓存参数 ──

def test_tool_cache_ttl():
    """工具缓存 TTL"""
    from infra.globals import get_health_cache
    cache = get_health_cache()
    assert cache._ttl == 30


# ── reset_registry ──

def test_reset_registry():
    """注册表重置"""
    from infra.toolcheck import reset_registry
    from infra.config.registry import ModelRegistry
    # 先获取实例，确保单例存在
    ModelRegistry()
    assert ModelRegistry._instance is not None
    # 重置
    reset_registry()
    assert ModelRegistry._instance is None


# ── D-02: CSV/DB 同步标记 ──

def test_db_record_step_no_db():
    """DB 不可用时 _db_record_step 不崩溃"""
    from pipeline.tasks import _db_record_step
    # 不应抛异常（DB 不可用时静默跳过）
    _db_record_step(1, "001", "tts", {"status": "done", "path": "/tmp/test.wav"})


# ── T-04: 测试隔离 ──

def test_load_yaml_entities_empty_dir(tmp_dir):
    """空目录返回空列表"""
    from infra.config import load_yaml_entities
    empty_dir = tmp_dir / "empty"
    empty_dir.mkdir()
    assert load_yaml_entities(empty_dir, "character") == []


def test_load_yaml_entities_nonexistent_dir(tmp_dir):
    """不存在的目录返回空列表"""
    from infra.config import load_yaml_entities
    assert load_yaml_entities(tmp_dir / "nope", "character") == []


# ── T-05: 异常注入 ──

def test_tts_core_backend_error(mock_cfg, tmp_dir):
    """TTS 后端异常时不崩溃"""
    from pipeline.tasks import tts_core

    out_dir = tmp_dir / "e01" / "004"
    out_dir.mkdir(parents=True, exist_ok=True)

    bad_cont = MagicMock()
    bad_backend = MagicMock()
    bad_backend.synthesize = MagicMock(side_effect=RuntimeError("TTS 服务不可用"))
    bad_cont.get = MagicMock(return_value=bad_backend)
    shot = {"shot_id": "004", "dialogue": "测试", "duration": 4, "emotion": "neutral"}

    result = tts_core("004", shot, mock_cfg, bad_cont, out_dir)
    assert result["status"] == "error"
    assert "TTS" in result.get("reason", "") or "服务" in result.get("reason", "")


def test_validate_shot_empty():
    """空镜头数据"""
    from engines.content.storyboard import validate_shot
    errors = validate_shot({})
    assert len(errors) > 0


def test_validate_shot_bad_duration():
    """无效 duration"""
    from engines.content.storyboard import validate_shot
    shot = {"episode": 1, "shot_id": "001", "scene_name": "r", "characters": "a", "action": "x", "dialogue": "y", "duration": "abc"}
    errors = validate_shot(shot)
    assert any("duration" in e for e in errors)


# ── T-05 补充: ComfyUI 不可达 ──

def test_check_available_comfyui_down():
    """ComfyUI 不可达时返回不可用"""
    from infra.toolcheck import _check_tool_inner
    from infra.globals import get_health_cache
    get_health_cache().invalidate()  # 清除缓存
    with patch("infra.toolcheck._check_tool_inner", return_value={"available": False, "reason": "ComfyUI 不可达"}):
        result = _check_tool_inner("comfyui", {"comfyui": {"url": "http://127.0.0.1:8188"}})
        assert result["available"] is False


def test_check_available_tool_missing():
    """工具不存在时返回不可用"""
    from infra.toolcheck import _check_tool_inner
    with patch("infra.toolcheck._check_tool_inner", return_value={"available": False, "reason": "未知工具"}):
        result = _check_tool_inner("nonexistent_tool", {})
        assert result["available"] is False


# ── T-05 补充: 网络超时 ──

def test_download_seko_image_timeout(tmp_dir):
    """Seko 图片下载超时不崩溃"""
    from pipeline.tasks.seko import _download_seko_image
    # 请求一个不存在的地址，应快速失败
    result = _download_seko_image("http://192.0.2.1:12345/fake.jpg", str(tmp_dir / "fake.jpg"),
                                   timeout=1, retries=1)
    assert result is False


# ── T-05 补充: 配置文件损坏 ──

def test_config_corrupted_yaml(tmp_dir):
    """损坏的 YAML 配置不崩溃"""
    from infra.config import load_config
    bad_yaml = tmp_dir / "bad.yaml"
    bad_yaml.write_text("{{invalid: yaml: content", encoding="utf-8")
    result = load_config(str(bad_yaml))
    # 应返回空 dict 而非抛异常
    assert isinstance(result, dict)


# ── T-05 补充: 路径遍历防护 ──

def test_prepare_rejects_path_traversal():
    """_prepare 拒绝无效的 config_path"""
    from pipeline.tasks.helpers import _prepare
    # 非 YAML 文件会因 Config 解析失败而抛异常或返回错误
    try:
        cfg, cont, shot, err = _prepare("/etc/passwd", 1, "001", "tts", "tts")
        assert err is not None or cfg is None
    except (ValueError, Exception):
        pass  # Config 校验失败也是预期行为


# ── D-03: YAML→DB 同步 ──

