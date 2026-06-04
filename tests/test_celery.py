"""Celery 任务测试 — Mock 模式

不依赖 Redis/Celery Worker，通过 mock 验证任务逻辑。
需要 PostgreSQL（AI_DRAMA_DB_DSN）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 配置 Celery eager 模式（不需要 Redis broker）
# 使用 fixture 级别设置，避免污染其他测试模块
from pipeline.celery_app import app as celery_app

_orig_eager = celery_app.conf.task_always_eager
_orig_propagate = celery_app.conf.task_eager_propagates
_orig_backend = celery_app.conf.result_backend


@pytest.fixture(autouse=True, scope="session")
def _celery_eager_mode():
    """Session 级别设置 Celery eager 模式，结束后恢复"""
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        result_backend="cache+memory://",
    )
    yield
    celery_app.conf.update(
        task_always_eager=_orig_eager,
        task_eager_propagates=_orig_propagate,
        result_backend=_orig_backend,
    )


@pytest.fixture
def test_project():
    """创建临时测试项目（需要 DB）"""
    import yaml
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        pytest.skip("需要 AI_DRAMA_DB_DSN")

    d = tempfile.mkdtemp(prefix="drama_celery_test_")
    os.makedirs(f"{d}/config", exist_ok=True)
    os.makedirs(f"{d}/output/e01/s001", exist_ok=True)

    with open(f"{d}/config/project.yaml", "w") as f:
        yaml.dump({"project": {"name": "测试"}, "models": {"tts_backend": "mimo-voicedesign"}}, f)

    # 写入测试分镜到 DB
    from infra.database.pool import PgPool
    from infra.database.storyboard_db import save_episode_shots
    pool = PgPool(dsn)
    save_episode_shots(pool, 1, [
        {"shot_id": "001", "scene_id": "客厅", "characters": "女主",
         "action": "坐", "dialogue": "你好世界", "camera": "固定",
         "shot_type": "中景", "duration": "4", "emotion": "neutral"},
        {"shot_id": "002", "scene_id": "厨房", "characters": "男主",
         "action": "做饭", "dialogue": "......", "camera": "固定",
         "shot_type": "中景", "duration": "3", "emotion": "calm"},
    ])
    pool.closeall()

    return d


# ── 辅助函数 ──

def test_load_shots(test_project):
    """测试分镜加载"""
    from pipeline.tasks import _load_shots
    cfg_path = f"{test_project}/config/project.yaml"
    shots = _load_shots(cfg_path, 1)
    assert len(shots) == 2
    assert shots[0]["shot_id"] == "001"
    assert shots[0]["dialogue"] == "你好世界"


def test_load_shots_empty(test_project):
    """测试空集加载"""
    from pipeline.tasks import _load_shots
    cfg_path = f"{test_project}/config/project.yaml"
    shots = _load_shots(cfg_path, 99)
    assert len(shots) == 0


def test_find_shot(test_project):
    """测试单镜头查找"""
    from pipeline.tasks import _find_shot
    cfg_path = f"{test_project}/config/project.yaml"
    shot = _find_shot(cfg_path, 1, "001")
    assert shot is not None
    assert shot["shot_id"] == "001"


def test_find_shot_not_found(test_project):
    """测试不存在的镜头"""
    from pipeline.tasks import _find_shot
    cfg_path = f"{test_project}/config/project.yaml"
    shot = _find_shot(cfg_path, 1, "999")
    assert shot is None


def test_shot_dir(test_project):
    """测试镜头输出目录"""
    from pipeline.tasks import _shot_dir
    cfg_path = f"{test_project}/config/project.yaml"
    d = _shot_dir(cfg_path, 1, "001")
    assert "e01" in str(d)
    assert "s001" in str(d)


# ── TTS 任务 Mock ──

def test_step_tts_no_dialogue(test_project):
    """TTS 任务: 无台词应跳过"""
    from pipeline.tasks import step_tts

    # shot_id=002 的台词是 "......"，应该跳过
    with patch("pipeline.tasks._check_available", return_value=(True, "")):
        result = step_tts.apply(args=[f"{test_project}/config/project.yaml", 1, "002"]).get()
        assert result["status"] == "skipped"
        assert "无台词" in result["reason"]


def test_step_tts_tool_unavailable(test_project):
    """TTS 任务: 工具不可用应跳过"""
    from pipeline.tasks import step_tts

    with patch("pipeline.tasks._check_available", return_value=(False, "MIMO_API_KEY 未配置")):
        result = step_tts.apply(args=[f"{test_project}/config/project.yaml", 1, "001"]).get()
        assert result["status"] == "skipped"
        assert "不可用" in result["reason"]


def test_step_tts_shot_not_found(test_project):
    """TTS 任务: 镜头不存在"""
    from pipeline.tasks import step_tts

    with patch("pipeline.tasks._check_available", return_value=(True, "")):
        result = step_tts.apply(args=[f"{test_project}/config/project.yaml", 1, "999"]).get()
        assert result["status"] == "error"
        assert "不存在" in result["reason"]


# ── 首帧任务 Mock ──

def test_step_first_frame_tool_unavailable(test_project):
    """首帧任务: ComfyUI 不可用"""
    from pipeline.tasks import step_first_frame

    with patch("pipeline.tasks._check_available", return_value=(False, "ComfyUI 不可达")):
        result = step_first_frame.apply(args=[f"{test_project}/config/project.yaml", 1, "001"]).get()
        assert result["status"] == "skipped"


# ── 视频任务 Mock ──

def test_step_video_no_frame(test_project):
    """视频任务: 首帧不存在应跳过"""
    from pipeline.tasks import step_video

    with patch("pipeline.tasks._check_available", return_value=(True, "")):
        result = step_video.apply(args=[f"{test_project}/config/project.yaml", 1, "001"]).get()
        assert result["status"] == "skipped"
        assert "首帧" in result["reason"]


# ── 口型同步任务 Mock ──

def test_step_lipsync_no_video(test_project):
    """口型任务: 视频不存在"""
    from pipeline.tasks import step_lipsync

    with patch("pipeline.tasks._check_available", return_value=(True, "")):
        result = step_lipsync.apply(args=[f"{test_project}/config/project.yaml", 1, "001"]).get()
        assert result["status"] == "skipped"
        assert "视频" in result["reason"]


def test_step_lipsync_no_audio(test_project):
    """口型任务: 音频不存在"""
    from pipeline.tasks import step_lipsync

    # 创建视频文件但不创建音频
    video_path = f"{test_project}/output/e01/s001/video.mp4"
    Path(video_path).touch()

    with patch("pipeline.tasks._check_available", return_value=(True, "")):
        result = step_lipsync.apply(args=[f"{test_project}/config/project.yaml", 1, "001"]).get()
        assert result["status"] == "skipped"
        assert "音频" in result["reason"]


# ── 字幕任务 ──

def test_subtitle_task(test_project):
    """字幕生成"""

    with patch("pipeline.tasks.subtitle_task.apply") as mock_apply:
        mock_apply.return_value.get.return_value = {"path": "test.srt", "count": 2}
        # 直接调用底层函数
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "你好", "duration": 3},
            {"dialogue": "世界", "duration": 4},
        ]
        out = f"{test_project}/output/e01/test.srt"
        generate_srt(shots, out)
        assert Path(out).exists()
        content = Path(out).read_text(encoding="utf-8")
        assert "你好" in content
        assert "世界" in content


# ── Celery 应用配置 ──

def test_celery_app_config():
    """Celery 配置正确"""
    from pipeline.celery_app import app, format_task_error

    assert app.main == "drama"
    assert app.conf.task_track_started == True
    assert app.conf.task_acks_late == True
    assert app.conf.worker_prefetch_multiplier == 1

    # 统一错误格式
    err = format_task_error(ValueError("测试错误"), "test_task", "abc-123")
    assert err["status"] == "error"
    assert err["error"] == "测试错误"
    assert err["error_type"] == "ValueError"
    assert err["task"] == "test_task"
    assert err["task_id"] == "abc-123"


def test_celery_tasks_registered():
    """任务注册"""
    from pipeline.celery_app import app
    import pipeline.tasks  # 触发任务注册

    expected = [
        "pipeline_step_tts", "pipeline_step_first_frame", "pipeline_step_video",
        "pipeline_step_lipsync", "pipeline_shot", "pipeline_preview",
        "pipeline_produce", "pipeline_post", "pipeline_portraits",
        "pipeline_tts_single", "pipeline_music", "pipeline_subtitle",
    ]
    registered = set(app.tasks.keys())
    for name in expected:
        assert name in registered, f"任务未注册: {name}"
