"""单镜头步骤 — 核心逻辑 + Celery 任务包装

按步骤拆分为独立模块:
  - tts.py      — TTS 语音合成
  - frame.py    — 首帧生成（ComfyUI）
  - video.py    — 视频生成（ComfyUI）
  - lipsync.py  — 口型同步

本文件提供:
  1. 向后兼容的 re-export（现有 import 无需改动）
  2. _run_* 包装函数（_prepare 防重复 + 核心逻辑）
  3. Celery step 任务定义
"""
from __future__ import annotations

import logging

from infra.constants import STATUS_DONE, STATUS_ERROR
from pipeline.tasks.helpers import (
    _db_record_step, _prepare, PrepareParams,
)

# ── re-export 核心逻辑（向后兼容）──
from pipeline.tasks.steps.tts import tts_core
from pipeline.tasks.steps.frame import FirstFrameParams, first_frame_core
from pipeline.tasks.steps.video import video_core
from pipeline.tasks.steps.lipsync import lipsync_core

logger = logging.getLogger(__name__)

__all__ = [
    "tts_core", "FirstFrameParams", "first_frame_core", "video_core", "lipsync_core",
    "_run_tts", "_run_first_frame", "_run_video", "_run_lipsync",
    "step_tts", "step_first_frame", "step_video", "step_lipsync",
]


# ══════════════════════════════════════════════════════════
#  _run_* 包装（_prepare + 核心逻辑）
# ══════════════════════════════════════════════════════════

def _run_tts(config_path: str, episode: int, shot_id: str, *,
             force: bool = False,
             cfg=None, cont=None, shot: dict | None = None,
             characters: dict | None = None, **kw) -> dict:
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="tts", tool="tts", force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return tts_core(shot_id, shot, cfg, cont, cfg.paths.shot_dir(episode, shot_id),
                    force=force, characters=characters)


def _run_first_frame(config_path: str, episode: int, shot_id: str, *,
                     force: bool = False,
                     cfg=None, cont=None, shot: dict | None = None,
                     characters: dict | None = None,
                     scenes: dict | None = None, **kw) -> dict:
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="first_frame", tool="comfyui", force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return first_frame_core(FirstFrameParams(
        shot_id=shot_id, shot=shot, cfg=cfg, cont=cont,
        out_dir=cfg.paths.shot_dir(episode, shot_id),
        force=force, characters=characters, scenes=scenes))


def _run_video(config_path: str, episode: int, shot_id: str, *,
               force: bool = False,
               cfg=None, cont=None, shot: dict | None = None, **kw) -> dict:
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="video", tool="comfyui", need_shot=True, force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return video_core(shot_id, cfg, cont, cfg.paths.shot_dir(episode, shot_id),
                      shot=shot, force=force)


def _run_lipsync(config_path: str, episode: int, shot_id: str, *,
                 force: bool = False,
                 cfg=None, cont=None, **kw) -> dict:
    cfg, cont, _, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="lipsync", tool="lipsync", need_shot=False, force=force, cfg=cfg, cont=cont))
    if err:
        return err
    return lipsync_core(shot_id, cont, cfg.paths.shot_dir(episode, shot_id), force=force)


# ══════════════════════════════════════════════════════════
#  Celery 步骤任务
# ══════════════════════════════════════════════════════════

from celery.exceptions import SoftTimeLimitExceeded
from pipeline.celery_app import app


def _step_task(self, step: str, fn, config_path: str, episode: int, shot_id: str, *, force: bool = False):
    """通用 Celery 步骤任务包装"""
    self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 10, "message": f"[{shot_id}] {step} 开始..."})
    try:
        result = fn(config_path, episode, shot_id, force=force)
    except SoftTimeLimitExceeded:
        logger.warning(f"[{shot_id}] {step} 超时（soft_time_limit）")
        _db_record_step(episode, shot_id, step, {"status": STATUS_ERROR, "reason": "执行超时"})
        return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": "执行超时"}
    except Exception as e:
        logger.error(f"[{shot_id}] {step} 异常: {e}", exc_info=True)
        _db_record_step(episode, shot_id, step, {"status": STATUS_ERROR, "reason": str(e)})
        return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": str(e)}
    _db_record_step(episode, shot_id, step, result)
    if result.get("status") == STATUS_DONE:
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 完成"})
    elif result.get("status") == STATUS_ERROR:
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 失败: {result.get('reason', '')}"})
    return result


@app.task(bind=True, name="pipeline_step_tts", soft_time_limit=120)
def step_tts(self, config_path, episode, shot_id, force=False):
    return _step_task(self, "tts", _run_tts, config_path, episode, shot_id, force=force)


@app.task(bind=True, name="pipeline_step_first_frame", soft_time_limit=300)
def step_first_frame(self, config_path, episode, shot_id, force=False):
    return _step_task(self, "first_frame", _run_first_frame, config_path, episode, shot_id, force=force)


@app.task(bind=True, name="pipeline_step_video", soft_time_limit=600)
def step_video(self, config_path, episode, shot_id, force=False):
    return _step_task(self, "video", _run_video, config_path, episode, shot_id, force=force)


@app.task(bind=True, name="pipeline_step_lipsync", soft_time_limit=300)
def step_lipsync(self, config_path, episode, shot_id, force=False):
    return _step_task(self, "lipsync", _run_lipsync, config_path, episode, shot_id, force=force)
