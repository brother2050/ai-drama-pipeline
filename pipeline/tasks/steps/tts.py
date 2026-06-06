"""TTS 语音合成步骤 — 台词文本 → audio.wav"""
from __future__ import annotations

import logging
from pathlib import Path

from engines.shot_utils import parse_char_ids
from pipeline.tasks.helpers import _skip, _err, _done, _validate_output

logger = logging.getLogger(__name__)


# 文件变化时清除 TTS 角色缓存（YAML 修改后自动生效）
from infra.hooks import on_cache_invalidate  # noqa: E402

@on_cache_invalidate(priority=50)
def _clear_tts_char_cache():
    if hasattr(tts_core, "_chars"):
        tts_core._chars = {}
        tts_core._chars_dir = None  # 强制下次重新加载


def tts_core(shot_id: str, shot: dict, cfg, cont, out_dir: Path, *,
             force: bool = False, characters: dict | None = None) -> dict:
    """TTS 核心逻辑 — 合成台词为音频（带看门狗跟踪 + 并发组限流）"""
    dialogue = shot.get("dialogue", "").strip()
    if not dialogue or set(dialogue) <= {".", "…"}:
        return _skip(shot_id, "tts", "无台词")

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")

    if not force and Path(audio_path).exists():
        return _skip(shot_id, "tts", "音频已存在")

    char_ids = parse_char_ids(shot)
    if characters:
        char_data = characters.get(char_ids[0], {}) if char_ids else {}
    else:
        # 缓存角色数据（同一 Worker 进程内复用，避免每次 TTS 都重新加载 YAML）
        config_dir = str(cfg.paths.config_dir)
        if not hasattr(tts_core, "_chars") or tts_core._chars_dir != config_dir:
            from infra.config import load_yaml_entities
            tts_core._chars = {c["id"]: c for c in load_yaml_entities(cfg.paths.characters_dir, "character")}
            tts_core._chars_dir = config_dir
        char_data = tts_core._chars.get(char_ids[0], {}) if char_ids else {}

    if char_ids and not char_data:
        logger.warning(f"[{shot_id}] 角色 {char_ids[0]} 不存在，使用默认声音")
    core_traits = (char_data.get("bible") or {}).get("core_traits", "")
    voice_config = {"core_traits": core_traits} if core_traits else {}
    # 角色级 voice 参数覆盖（reference_audio/speaker/reference_id 等）
    char_voice = char_data.get("voice")
    if isinstance(char_voice, dict) and char_voice:
        voice_config = {**voice_config, **char_voice}
    emotion = shot.get("emotion", "neutral")
    language = shot.get("language", "zh")

    from infra.globals import get_watchdog, get_concurrency_groups
    from infra.safe_executor import safe_run
    wd = get_watchdog()
    groups = get_concurrency_groups()

    def _do_tts():
        with groups.acquire("tts"):
            with wd.track(f"{shot_id}:tts", backend="tts"):
                tts_inst, _ = cont.get_with_fallback("tts")
                tts_inst.synthesize(dialogue, audio_path, voice_config=voice_config,
                                    emotion=emotion, language=language)

    try:
        safe_run(_do_tts, retries=2, base_delay=1.0, task_id=f"{shot_id}:tts")
    except Exception as e:
        return _err(shot_id, "tts", f"TTS 合成失败: {e}")
    err = _validate_output(audio_path, "tts", min_size=1000)
    if err:
        return _err(shot_id, "tts", err)
    return _done(shot_id, "tts", audio_path)
