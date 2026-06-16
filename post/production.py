"""后期合成 — 拼接、转场、字幕、配乐、横转竖"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from infra.config import Config
from infra.compute.ffmpeg import FFmpeg

logger = logging.getLogger(__name__)

__all__ = ["run_post"]


def _cleanup_intermediates(out_dir: Path, episode: int) -> None:
    """清理上次遗留的中间文件"""
    patterns = [
        f"episode_{episode:02d}_concat.mp4",
        f"episode_{episode:02d}_subtitled.mp4",
        f"episode_{episode:02d}_with_bgm.mp4",
        f"episode_{episode:02d}_vertical.mp4",
    ]
    for name in patterns:
        p = out_dir / name
        if p.exists():
            try:
                p.unlink()
                logger.debug(f"清理遗留中间文件: {p.name}")
            except OSError as e:
                logger.debug(f"{type(e).__name__}: {e}")


def _collect_videos(out_dir: Path) -> list[Path]:
    """收集所有镜头视频（按 shot_id 数值排序，优先 synced.mp4）"""
    def _shot_sort_key(p: Path) -> int:
        m = re.search(r'\d+', p.name)
        return int(m.group()) if m else 0
    videos = []
    for shot_dir in sorted(out_dir.glob("s*"), key=_shot_sort_key):
        synced = shot_dir / "synced.mp4"
        video = shot_dir / "video.mp4"
        if synced.exists():
            videos.append(synced)
        elif video.exists():
            videos.append(video)
    return videos


def _concat_videos(videos: list[Path], concat_out: Path, transition: str, duration: float) -> tuple[bool, bool]:
    """拼接视频，失败时回退到简单拼接。返回 (成功, 是否使用了转场)"""
    # 单视频无需转场，直接复制
    if len(videos) == 1:
        shutil.copy2(str(videos[0]), str(concat_out))
        logger.info(f"单视频直接复制: {concat_out}")
        return True, False
    try:
        FFmpeg.concat([str(v) for v in videos], str(concat_out),
                      transition=transition, duration=duration)
        logger.info(f"拼接完成: {concat_out}")
        return True, True
    except RuntimeError as e:
        logger.error(f"拼接失败: {e}", exc_info=True)
    # 回退：简单拼接（无转场）
    try:
        FFmpeg.concat([str(v) for v in videos], str(concat_out), transition="none")
        logger.info(f"简单拼接完成: {concat_out}")
        return True, False
    except RuntimeError as e2:
        logger.error(f"简单拼接也失败: {e2}，跳过后期合成", exc_info=True)
        return False, False


def _add_subtitles(concat_out: Path, srt_path: Path, episode: int, out_dir: Path) -> Path:
    """添加字幕，失败则跳过"""
    if not srt_path.exists():
        return concat_out
    subtitled_out = out_dir / f"episode_{episode:02d}_subtitled.mp4"
    try:
        FFmpeg.add_subtitle(str(concat_out), str(srt_path), str(subtitled_out))
        logger.info(f"字幕添加完成: {subtitled_out}")
        return subtitled_out
    except RuntimeError as e:
        logger.warning(f"字幕添加失败（跳过）: {e}")
        return concat_out


def _generate_and_mix_bgm(concat_out: Path, shots: list[dict], cfg: Config,
                          episode: int, out_dir: Path, cont: object = None,
                          video_durations: list[float] | None = None) -> Path:
    """自动生成配乐并混合，失败则跳过"""
    bgm_path = out_dir / "bgm.wav"
    if not bgm_path.exists():
        try:
            from post.music import MusicGenerator
            from infra.compute.ffmpeg import probe as ffprobe
            try:
                total_dur = float(ffprobe(str(concat_out)).get("format", {}).get("duration", 0))
            except Exception:
                total_dur = 0
            if total_dur <= 0:
                # 优先用已探测的视频时长，回退到分镜预期时长
                if video_durations:
                    total_dur = sum(video_durations)
                else:
                    total_dur = sum(float(s.get("duration", 4)) for s in shots)
            emotions = [s.get("emotion", "neutral") for s in shots if s.get("emotion")]
            mood = max(set(emotions), key=emotions.count) if emotions else "neutral"
            music_gen = MusicGenerator(config=dict(cfg.data), container=cont)
            music_gen.generate(total_dur, str(bgm_path), mood=mood)
            logger.info(f"配乐自动生成: {bgm_path} (时长 {total_dur:.1f}s, 情绪 {mood})")
        except Exception as e:
            logger.warning(f"配乐自动生成失败（跳过）: {e}")
    if not bgm_path.exists():
        return concat_out
    bgm_out = out_dir / f"episode_{episode:02d}_with_bgm.mp4"
    bgm_volume = cfg.get("post_production.bgm_volume", 0.15)
    try:
        FFmpeg.mix_audio(str(concat_out), str(bgm_path), str(bgm_out),
                         video_vol=1.0, audio_vol=bgm_volume)
        logger.info(f"配乐混合完成: {bgm_out}")
        return bgm_out
    except RuntimeError as e:
        logger.warning(f"配乐混合失败（跳过）: {e}")
        return concat_out


def _to_vertical(concat_out: Path, episode: int, out_dir: Path) -> Path:
    """横转竖，失败则跳过"""
    from post.vertical import to_vertical
    vertical_out = out_dir / f"episode_{episode:02d}_vertical.mp4"
    try:
        to_vertical(str(concat_out), str(vertical_out), mode="face_track")
        logger.info(f"横转竖完成: {vertical_out}")
        return vertical_out
    except Exception as e:
        logger.error(f"横转竖失败: {e}", exc_info=True)
        return concat_out


def _rename_final(concat_out: Path, episode: int, out_dir: Path) -> Path:
    """重命名为 final.mp4（跨文件系统自动回退到 copy2）"""
    final_out = out_dir / f"episode_{episode:02d}_final.mp4"
    try:
        os.replace(str(concat_out), str(final_out))
    except OSError:
        shutil.copy2(str(concat_out), str(final_out))
        try:
            os.unlink(str(concat_out))
        except OSError as e:
            logger.warning(f"清理源文件失败: {concat_out} ({e})")
    logger.info(f"最终输出: {final_out}")
    return final_out


def _cleanup_and_update_db(out_dir: Path, episode: int, final_out: Path) -> None:
    """清理中间文件"""
    if final_out.exists():
        for name in ["_concat.mp4", "_subtitled.mp4", "_with_bgm.mp4", "_vertical.mp4"]:
            intermediate = out_dir / f"episode_{episode:02d}{name}"
            if intermediate.exists() and intermediate != final_out:
                try:
                    intermediate.unlink()
                except OSError as e:
                    logger.debug(f"{type(e).__name__}: {e}")
        # 清理 bgm.wav 中间文件（下次运行会重新生成，避免复用过期 BGM）
        bgm = out_dir / "bgm.wav"
        if bgm.exists():
            try:
                bgm.unlink()
            except OSError as e:
                logger.debug(f"{type(e).__name__}: {e}")
    # episodes 表已移除，集状态由 shots 表实时聚合


def run_post(config_path: str, episode: int, vertical: bool = False, cfg=None) -> dict:
    """后期合成：拼接所有镜头视频 → 添加字幕/配乐 → 可选横转竖

    Returns:
        {"status": "done", "path": str} 或 {"status": "error", "reason": str}
    """
    from infra.constants import STATUS_DONE, STATUS_ERROR
    if cfg is None:
        cfg = Config(config_path)
    paths = cfg.paths
    logger.info(f"后期合成 第{episode}集{'（竖屏）' if vertical else ''}")

    out_dir = paths.episode_dir(episode)
    if not out_dir.exists():
        return {"status": STATUS_ERROR, "reason": f"输出目录不存在: {out_dir}"}

    _cleanup_intermediates(out_dir, episode)
    videos = _collect_videos(out_dir)
    if not videos:
        return {"status": STATUS_ERROR, "reason": "没有视频文件"}

    # 加载分镜（用于 SRT + 配乐）
    from engines.content.storyboard import load_storyboard
    shots = load_storyboard(episode=episode)

    # 探测各镜头视频实际时长（供 SRT 和 BGM 使用）
    from infra.compute.ffmpeg import probe as ffprobe
    video_durations: list[float] = []
    for v in videos:
        try:
            info = ffprobe(str(v))
            dur = float(info.get("format", {}).get("duration", 0))
            video_durations.append(dur if dur > 0 else 4.0)
        except Exception:
            video_durations.append(4.0)

    # 重新生成 SRT
    srt_path = paths.episode_srt(episode)
    if shots:
        try:
            from post.subtitle import generate_srt
            bilingual = cfg.get("post_production.bilingual_subtitle", False)
            td = cfg.get("post_production.transition_duration", 0.5)
            generate_srt(shots, str(srt_path), transition_duration=td,
                         bilingual=bilingual, video_durations=video_durations)
            logger.info(f"SRT 已重新生成: {srt_path}" + ("（双语）" if bilingual else ""))
        except Exception as e:
            logger.warning(f"SRT 重新生成失败（使用已有文件）: {e}")

    # 拼接
    concat_out = out_dir / f"episode_{episode:02d}_concat.mp4"
    transition = cfg.get("post_production.transition", "crossfade")
    td = cfg.get("post_production.transition_duration", 0.5)
    ok, used_transition = _concat_videos(videos, concat_out, transition, td)
    if not ok:
        return {"status": STATUS_ERROR, "reason": "视频拼接失败"}

    # 转场回退后重新生成 SRT（无转场时视频总时长不同，SRT 时序需同步）
    if not used_transition and shots and srt_path.exists():
        try:
            from post.subtitle import generate_srt
            bilingual = cfg.get("post_production.bilingual_subtitle", False)
            generate_srt(shots, str(srt_path), transition_duration=0,
                         bilingual=bilingual, video_durations=video_durations)
            logger.info("SRT 已按无转场模式重新生成")
        except Exception as e:
            logger.warning(f"SRT 重新生成失败: {e}")

    # 字幕 → 配乐 → 横转竖 → 重命名
    concat_out = _add_subtitles(concat_out, srt_path, episode, out_dir)
    try:
        from api.registry import Container
        cont = Container(cfg.data)
    except Exception:
        cont = None
    concat_out = _generate_and_mix_bgm(concat_out, shots, cfg, episode, out_dir, cont=cont,
                                       video_durations=video_durations)
    if vertical:
        concat_out = _to_vertical(concat_out, episode, out_dir)
    final_out = _rename_final(concat_out, episode, out_dir)

    logger.info("后期合成完成")
    _cleanup_and_update_db(out_dir, episode, final_out)
    return {"status": STATUS_DONE, "path": str(final_out)}
