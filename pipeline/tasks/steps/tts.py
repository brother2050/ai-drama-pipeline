"""TTS 语音合成步骤 — 台词文本 → audio.wav"""
from __future__ import annotations

import logging
from pathlib import Path

from engines.dialogue import DialogueLine, parse_dialogue, concat_wav
from pipeline.tasks.helpers import _skip, _err, _done, _validate_output

logger = logging.getLogger(__name__)


def _build_voice_config(char_data: dict) -> dict:
    """从角色数据构建 voice_config"""
    core_traits = (char_data.get("bible") or {}).get("core_traits", "")
    voice_config = {"core_traits": core_traits} if core_traits else {}
    # 角色级 voice 参数覆盖（reference_audio/speaker/reference_id 等）
    char_voice = char_data.get("voice")
    if isinstance(char_voice, dict) and char_voice:
        voice_config = {**voice_config, **char_voice}
    # 声音特征描述（角色配置中的 voice_description）
    voice_desc = char_data.get("voice_description", "")
    if voice_desc and "voice_description" not in voice_config:
        voice_config["voice_description"] = voice_desc
    return voice_config


def _resolve_char(speaker: str, all_chars: dict[str, dict]) -> dict:
    """按角色名查找角色数据。speaker 可以是 name 或 id。"""
    if not speaker:
        return {}
    # 先按 id 查
    if speaker in all_chars:
        return all_chars[speaker]
    # 再按 name 查
    for c in all_chars.values():
        if c.get("name") == speaker:
            return c
    return {}


def tts_core(shot_id: str, shot: dict, cfg, cont, out_dir: Path, *,
             force: bool = False, characters: dict | None = None) -> dict:
    """TTS 核心逻辑 — 合成台词为音频（带看门狗跟踪 + 并发组限流）"""
    lines = parse_dialogue(shot.get("dialogue", ""))
    if not lines:
        return _skip(shot_id, "tts", "无台词")

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")

    if not force and Path(audio_path).exists():
        return _skip(shot_id, "tts", "音频已存在")

    # 加载角色数据（带缓存）
    if characters:
        all_chars = characters
    else:
        config_dir = str(cfg.paths.config_dir)
        if not hasattr(tts_core, "_chars") or tts_core._chars_dir != config_dir:
            from infra.config import load_yaml_entities
            tts_core._chars = {c["id"]: c for c in load_yaml_entities(cfg.paths.characters_dir, "character")}
            tts_core._chars_dir = config_dir
        all_chars = tts_core._chars

    from infra.globals import get_watchdog, get_concurrency_groups
    from infra.safe_executor import safe_run
    wd = get_watchdog()
    groups = get_concurrency_groups()

    # 单条台词：直接合成
    if len(lines) == 1:
        line = lines[0]
        char_data = _resolve_char(line.speaker, all_chars)
        if line.speaker and not char_data:
            logger.warning(f"[{shot_id}] 角色 '{line.speaker}' 不存在，使用默认声音")
        voice_config = _build_voice_config(char_data)
        emotion = shot.get("emotion", "neutral")
        language = shot.get("language", "zh")

        def _do_tts():
            with groups.acquire("tts"):
                with wd.track(f"{shot_id}:tts", backend="tts"):
                    tts_inst, _ = cont.get_with_fallback("tts")
                    tts_inst.synthesize(line.text, audio_path, voice_config=voice_config,
                                        emotion=emotion, language=language)

        try:
            safe_run(_do_tts, retries=2, base_delay=1.0, task_id=f"{shot_id}:tts")
        except Exception as e:
            return _err(shot_id, "tts", f"TTS 合成失败: {e}")

    # 多条台词：逐条合成 → 拼接
    else:
        seg_paths: list[str] = []
        emotion = shot.get("emotion", "neutral")
        language = shot.get("language", "zh")

        for i, line in enumerate(lines):
            char_data = _resolve_char(line.speaker, all_chars)
            if line.speaker and not char_data:
                logger.warning(f"[{shot_id}] 角色 '{line.speaker}' 不存在，使用默认声音")
            voice_config = _build_voice_config(char_data)
            seg_path = str(out_dir / f"seg_{i:03d}.wav")

            def _do_seg(seg=seg_path, text=line.text, vc=voice_config):
                with groups.acquire("tts"):
                    with wd.track(f"{shot_id}:tts_{i}", backend="tts"):
                        tts_inst, _ = cont.get_with_fallback("tts")
                        tts_inst.synthesize(text, seg, voice_config=vc,
                                            emotion=emotion, language=language)

            try:
                safe_run(_do_seg, retries=2, base_delay=1.0, task_id=f"{shot_id}:tts_{i}")
            except Exception as e:
                return _err(shot_id, "tts", f"TTS 合成失败 (line {i}): {e}")
            seg_paths.append(seg_path)

        concat_wav(seg_paths, audio_path)
        # 清理临时分段文件
        for p in seg_paths:
            Path(p).unlink(missing_ok=True)

    err = _validate_output(audio_path, "tts", min_size=1000)
    if err:
        return _err(shot_id, "tts", err)
    return _done(shot_id, "tts", audio_path)


# 文件变化时清除 TTS 角色缓存（YAML 修改后自动生效）
from infra.hooks import on_cache_invalidate  # noqa: E402

@on_cache_invalidate(priority=50)
def _clear_tts_char_cache():
    if hasattr(tts_core, "_chars"):
        tts_core._chars = {}
        tts_core._chars_dir = None  # 强制下次重新加载
