"""视频构建 — 视频生成工作流"""

from __future__ import annotations

import copy
import logging
import math
import os

from engines.workflow.inject import (
    find_style_lora as _find_style_lora,
)
from engines.workflow.inject import (
    inject_lora as _inject_lora,
)
from engines.workflow.utils import (
    find_load_image_nodes,
    set_clip_text_prompts,
)

logger = logging.getLogger(__name__)

__all__ = ["build_video"]


def build_video(builder, frame_path: str, shot: dict | None = None,
                characters: dict | None = None,
                scenes: dict | None = None) -> dict:
    """构建视频生成工作流"""
    wf = copy.deepcopy(builder.video_wf)
    if not wf:
        logger.warning("build_video: video_wf 为空，无法构建视频工作流")
        return {}

    load_nodes = find_load_image_nodes(wf)
    if load_nodes:
        wf[load_nodes[0]]["inputs"]["image"] = os.path.basename(frame_path)

    if shot:
        style = builder.config.get("project", {}).get("style", "")
        genre = builder.config.get("project", {}).get("genre", "")
        _inject_video_prompt(builder, wf, shot, characters, scenes, style, genre)

    if shot:
        _apply_duration(builder, wf, shot)

    genre = builder.config.get("project", {}).get("genre", "")
    if genre:
        style_lora = _find_style_lora(builder, genre)
        if style_lora:
            style_strength = builder.models.get("style_lora_strength", 0.6)
            wf = _inject_lora(wf, style_lora, strength=style_strength,
                                   lora_name=os.path.basename(style_lora))

    from engines.workflow.builder import WorkflowBuilder
    WorkflowBuilder._randomize_seed(wf)

    # 工作流预检
    from engines.workflow.preflight import WorkflowPreflightChecker
    preflight = WorkflowPreflightChecker()
    result = preflight.check(wf)
    if not result.passed:
        for e in result.errors:
            logger.error(f"视频工作流预检失败: {e}")
    for w in result.warnings:
        logger.warning(f"视频工作流预检警告: {w}")
    logger.info(
        f"视频工作流预检: {result.checks_passed}/{result.checks_run} 项通过, "
        f"{len(result.errors)} error, {len(result.warnings)} warning"
    )

    return wf


def _inject_video_prompt(builder, wf: dict, shot: dict,
                          characters: dict | None = None,
                          scenes: dict | None = None,
                          style: str = "", genre: str = "") -> None:
    """构建并注入视频生成 prompt"""
    from engines.utils.shot import parse_char_names
    from infra.constants import CAMERA_MAP, EMOTION_MAP
    parts = []

    video_prompts_cfg = builder.registry.get_video_prompts() if builder.registry else {}
    style_map = video_prompts_cfg.get("style_map", {})
    suffix = video_prompts_cfg.get("suffix", "smooth cinematic motion, consistent appearance, natural movement")
    fallback = video_prompts_cfg.get("fallback", "smooth natural motion")
    negative_extra = video_prompts_cfg.get("negative_extra", "style change, art style shift, sudden style transition")

    char_names = parse_char_names(shot)
    if characters and char_names:
        shot_type = shot.get("shot_type", "")
        outfit_key = shot.get("outfit", "")
        for cid in char_names[:2]:
            char = characters.get(cid, {})
            if not char:
                continue
            from engines.prompt.view import get_view_appearance
            desc = get_view_appearance(char, shot_type)
            if desc:
                if outfit_key:
                    outfits = char.get("outfits", {})
                    if isinstance(outfits, dict):
                        outfit = outfits.get(outfit_key, {})
                        if isinstance(outfit, dict):
                            outfit_desc = outfit.get("description_en", "") or outfit.get("description", "")
                            if outfit_desc and outfit_desc.isascii():
                                desc = f"{desc}, wearing {outfit_desc}"
                parts.append(desc[:200])

        if len(char_names) > 1:
            from engines.utils.multi_char import MultiCharacterHandler
            char_dicts = [characters[cid] for cid in char_names[:2] if cid in characters]
            if char_dicts:
                multi = MultiCharacterHandler().generate_multi_char_prompt(char_dicts)
                if multi:
                    parts.append(multi[:200])

    if style:
        parts.append(style_map.get(style, f"{style} style"))
    if genre:
        parts.append(f"{genre} genre")

    scene_name = shot.get("scene_name", "")
    if scenes and scene_name:
        scene = scenes.get(scene_name, {})
        scene_en = scene.get("description_en") or scene.get("description", "")
        if scene_en and scene_en.isascii():
            lighting_en = scene.get("lighting_en") or scene.get("lighting", "")
            if lighting_en and lighting_en.isascii():
                scene_en = f"{scene_en}, {lighting_en}"
            parts.append(scene_en)

    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            from engines.utils.shot import strip_dialogue
            action = strip_dialogue(action)
    if action and action.isascii():
        parts.append(action)

    camera = shot.get("camera", "")
    if camera and camera in CAMERA_MAP:
        parts.append(CAMERA_MAP[camera])

    emotion = shot.get("emotion", "neutral")
    if emotion and emotion in EMOTION_MAP:
        parts.append(EMOTION_MAP[emotion])

    positive = ", ".join(parts) if parts else fallback

    if positive != fallback:
        positive = f"{positive}, {suffix}"

    video_backend = builder.models.get("video_backend", "cosmos-video")
    video_meta = builder.registry.get_backend("video", video_backend) if video_backend else {}
    negative = (video_meta or {}).get("negative_prompt",
        "static, frozen, no motion, glitch, distortion, watermark, text")
    negative += f", {negative_extra}"

    set_clip_text_prompts(wf, positive, negative)
    logger.info(f"视频 prompt: {positive[:120]}...")


def _apply_duration(builder, wf: dict, shot: dict) -> None:
    """根据镜头 duration 动态调整视频帧数"""
    from infra.constants import clip_duration
    duration = clip_duration(shot.get("duration"))

    video_backend = builder.models.get("video_backend", "cosmos-video")
    model_fps = 8
    if builder.registry:
        defaults = builder.registry.get_video_defaults(video_backend)
        if defaults.get("fps"):
            model_fps = defaults["fps"]

    min_frames = 8
    video_frames = max(min_frames, math.ceil(duration * model_fps))

    logger.info(
        f"视频帧数计算: duration={duration}s × fps={model_fps} → "
        f"video_frames={video_frames} (backend={video_backend})"
    )

    _set_video_frames(builder, wf, video_frames, video_backend)


def _set_video_frames(builder, wf: dict, frames: int, backend: str) -> None:
    """将帧数设置到工作流的正确节点"""
    frame_cfg = builder.registry.get_frame_params(backend)
    if not frame_cfg:
        logger.warning(f"视频后端 '{backend}' 未声明 frame_params，跳过帧数注入")
        return

    target_class = frame_cfg["node_class"]
    target_input = frame_cfg["input_name"]

    for nid, node in wf.items():
        if node.get("class_type") == target_class:
            node["inputs"][target_input] = frames
            logger.debug(f"  {backend}: {nid}.{target_input} = {frames}")
