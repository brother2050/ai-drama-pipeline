"""Celery 任务包 — 导出所有 Celery 任务函数 + preview/测试依赖的核心函数"""
from __future__ import annotations

# 管线编排
from pipeline.tasks.pipeline import shot_task, preview_task, produce_task, run_all_task

# 单步执行（Web 工作台「单步执行」按钮调用）
from pipeline.tasks.steps import step_tts, step_first_frame, step_video, step_lipsync

# 核心逻辑（测试复用）
from pipeline.tasks.steps import tts_core, first_frame_core, video_core, lipsync_core

# AI 生成
from pipeline.tasks.ai import (
    ai_storyboard_task, ai_entities_task, ai_characters_task, ai_scenes_task,
    ai_chat_edit_task,
)
from pipeline.tasks.prepare import ai_prepare_task

# 定妆照 / 场景图
from pipeline.tasks.portrait import (
    portraits_task, scene_images_task,
    portrait_single_task, outfit_single_task, outfits_batch_task,
    scene_image_single_task,
)

# TTS / 配乐 / 字幕 / 后期
from pipeline.tasks.media import (
    post_task, tts_single_task, music_task, subtitle_task,
)

# 训练 / 导入
from pipeline.tasks.training import train_lora_task, import_json_task

# Seko 导入
from pipeline.tasks.seko import seko_import_task

# 内部工具函数（preview.py / 测试使用）
from pipeline.tasks.helpers import (
    _load_shots, _find_shot, _shot_dir, _check_available,
    _db_record_step, _prepare,
)

__all__ = [
    # 管线
    "shot_task", "preview_task", "produce_task", "post_task", "run_all_task",
    # 单步
    "step_tts", "step_first_frame", "step_video", "step_lipsync",
    # 核心逻辑
    "tts_core", "first_frame_core", "video_core", "lipsync_core",
    # AI
    "ai_storyboard_task", "ai_entities_task", "ai_characters_task", "ai_scenes_task",
    "ai_chat_edit_task", "ai_prepare_task",
    # 杂项
    "portraits_task", "scene_images_task",
    "portrait_single_task", "outfit_single_task", "outfits_batch_task",
    "scene_image_single_task",
    "tts_single_task", "music_task", "subtitle_task",
    "train_lora_task", "import_json_task",
    # Seko
    "seko_import_task",
    # 内部工具
    "_load_shots", "_find_shot", "_shot_dir", "_check_available",
    "_db_record_step", "_prepare",
]
