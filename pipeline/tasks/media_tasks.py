"""Celery 任务 — TTS / 配乐 / 字幕 / 后期合成"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR, STEP_TTS
import hashlib
import logging
import time
from pathlib import Path

from pipeline.celery_app import app
from pipeline.tasks.helpers import _build_ctx

logger = logging.getLogger(__name__)


def _run_subtitle(config_path: str, episode: int) -> dict:
    cfg, _ = _build_ctx(config_path)
    paths = cfg.paths
    from post.subtitle import generate_srt
    from engines.storyboard import load_storyboard
    shots = load_storyboard(episode=episode)
    if not shots:
        return {"status": STATUS_ERROR, "reason": f"第{episode}集没有镜头"}
    out_dir = paths.episode_dir(episode)
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = str(paths.episode_srt(episode))
    generate_srt(shots, srt, transition_duration=cfg.get("post_production.transition_duration", 0.5))
    return {"status": STATUS_DONE, "path": srt, "count": len(shots)}


def _run_post(config_path: str, episode: int, vertical: bool = False) -> None:
    # 绑定项目作用域，确保后期合成的 DB 写入到正确项目
    from pipeline.tasks.helpers import _project_scope_from_config, _build_ctx
    with _project_scope_from_config(config_path):
        from post.production import run_post
        cfg, _ = _build_ctx(config_path)
        run_post(config_path, episode, vertical, cfg=cfg)


@app.task(bind=True, name="pipeline_post", soft_time_limit=1200)
def post_task(self, config_path: str, episode: int, vertical: bool = False) -> dict:
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 10})
    try:
        _run_post(config_path, episode, vertical)
    except Exception as e:
        logger.error(f"后期合成失败: {e}", exc_info=True)
        return {"status": STATUS_ERROR, "episode": episode, "reason": str(e)}

    result = {"status": STATUS_DONE, "episode": episode, "vertical": vertical}

    # ── 质量门禁：后期后检查 ──
    try:
        from engines.quality_gate import check_quality
        from pipeline.tasks.helpers import _build_ctx
        cfg, _ = _build_ctx(config_path)
        issues = check_quality("after_post", str(cfg.paths.root), episode=episode)
        if issues:
            errors = [i for i in issues if i["severity"] == "error"]
            for e in errors:
                logger.error(f"❌ 质量检查: {e['name']} — {e['message']}")
            result["quality_issues"] = issues
    except Exception as e:
        logger.warning(f"质量门禁跳过: {e}")

    return result


@app.task(bind=True, name="pipeline_tts_single", soft_time_limit=120)
def tts_single_task(self, config_path: str, text: str, voice_config: dict | None = None,
                    emotion: str = "neutral", language: str = "zh"):
    cfg, cont = _build_ctx(config_path)
    self.update_state(state="PROGRESS", meta={"step": STEP_TTS, "progress": 20, "message": "TTS..."})
    paths = cfg.paths
    preview_dir = paths.tts_preview_dir
    preview_dir.mkdir(parents=True, exist_ok=True)
    tag = hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:8]
    output = str(preview_dir / f"preview_{tag}.wav")
    try:
        tts_backend, _ = cont.get_with_fallback("tts")
        result = tts_backend.synthesize(text, output, voice_config=voice_config or {}, emotion=emotion, language=language)
        rel_path = str(Path(result).relative_to(paths.root))
        return {"status": STATUS_DONE, "path": rel_path, "text": text}
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"TTS 合成失败: {e}", "text": text}


@app.task(bind=True, name="pipeline_music", soft_time_limit=120)
def music_task(self, config_path: str, duration: float, mood: str, output: str) -> dict:
    cfg, cont = _build_ctx(config_path)
    from post.music import MusicGenerator
    try:
        gen = MusicGenerator(config=cfg.data, container=cont)
        result = gen.generate(duration, output, mood=mood)
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"配乐生成失败: {e}", "mood": mood, "duration": duration}
    return {"status": STATUS_DONE, "path": result, "mood": mood, "duration": duration}


@app.task(bind=True, name="pipeline_subtitle", soft_time_limit=60)
def subtitle_task(self, config_path: str, episode: int):
    return _run_subtitle(config_path, episode)
