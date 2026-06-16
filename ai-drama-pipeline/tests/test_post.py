"""后期处理模块单元测试 — post/production.py + post/vertical.py + post/subtitle.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════
#  post/subtitle.py
# ══════════════════════════════════════════════════════════

class TestSubtitle:
    """字幕生成测试"""

    def test_sanitize_dialogue_removes_newlines(self):
        from post.subtitle import _sanitize_dialogue
        assert _sanitize_dialogue("hello\nworld") == "hello world"
        assert _sanitize_dialogue("a\r\nb\rc") == "a b c"
        assert _sanitize_dialogue("  spaces  ") == "spaces"

    def test_build_subtitle_text_skips_empty(self):
        from post.subtitle import _build_subtitle_text
        assert _build_subtitle_text({"dialogue": ""}, False) == ""
        assert _build_subtitle_text({"dialogue": "......"}, False) == ""
        assert _build_subtitle_text({"dialogue": "……"}, False) == ""
        assert _build_subtitle_text({}, False) == ""

    def test_build_subtitle_text_normal(self):
        from post.subtitle import _build_subtitle_text
        assert _build_subtitle_text({"dialogue": "你好"}, False) == "你好"

    def test_build_subtitle_text_bilingual(self):
        from post.subtitle import _build_subtitle_text
        shot = {"dialogue": "你好", "dialogue_en": "Hello"}
        assert _build_subtitle_text(shot, True) == "你好\\NHello"

    def test_build_subtitle_text_bilingual_no_en(self):
        from post.subtitle import _build_subtitle_text
        # 无英文时只返回中文
        assert _build_subtitle_text({"dialogue": "你好"}, True) == "你好"

    def test_build_subtitle_text_bilingual_en_is_dots(self):
        from post.subtitle import _build_subtitle_text
        shot = {"dialogue": "你好", "dialogue_en": "......"}
        assert _build_subtitle_text(shot, True) == "你好"

    def test_format_srt_time(self):
        from post.subtitle import _format_srt_time
        assert _format_srt_time(0) == "00:00:00,000"
        assert _format_srt_time(61.5) == "00:01:01,500"
        assert _format_srt_time(3661.123) == "01:01:01,123"
        assert _format_srt_time(-1) == "00:00:00,000"  # 负数归零

    def test_generate_srt_basic(self, tmp_path):
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "你好", "duration": 3},
            {"dialogue": "世界", "duration": 4},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out)
        content = Path(out).read_text(encoding="utf-8")
        assert "你好" in content
        assert "世界" in content
        assert "00:00:00,000 --> 00:00:03,000" in content

    def test_generate_srt_skips_empty_dialogue(self, tmp_path):
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "你好", "duration": 3},
            {"dialogue": "......", "duration": 2},
            {"dialogue": "", "duration": 2},
            {"dialogue": "世界", "duration": 4},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out)
        content = Path(out).read_text(encoding="utf-8")
        assert "你好" in content
        assert "世界" in content
        assert "......" not in content
        # 只有 2 条字幕
        assert content.count("-->") == 2

    def test_generate_srt_transition_duration(self, tmp_path):
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "A", "duration": 4},
            {"dialogue": "B", "duration": 4},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out, transition_duration=0.5)
        content = Path(out).read_text(encoding="utf-8")
        # shot0: span=4.0 (第一条无转场扣减)
        # shot1 (last): span=3.5 (最后一条也参与转场，扣减 transition_duration)
        assert "00:00:04,000 --> 00:00:07,500" in content

    def test_generate_srt_bilingual(self, tmp_path):
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "你好", "dialogue_en": "Hello", "duration": 3},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out, bilingual=True)
        content = Path(out).read_text(encoding="utf-8")
        assert "你好" in content
        assert "Hello" in content

    def test_generate_srt_uses_video_durations(self, tmp_path):
        """video_durations 优先于 shot.duration"""
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "A", "duration": 4},
            {"dialogue": "B", "duration": 4},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out, video_durations=[3.7, 5.2])
        content = Path(out).read_text(encoding="utf-8")
        # shot0: 0.0 → 3.7
        assert "00:00:00,000 --> 00:00:03,700" in content
        # shot1: 3.7 → 3.7 + 5.2 = 8.9
        assert "00:00:03,700 --> 00:00:08,900" in content

    def test_generate_srt_video_durations_with_transition(self, tmp_path):
        """video_durations + 转场（最后一条用完整 duration）"""
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "A", "duration": 4},
            {"dialogue": "B", "duration": 4},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out, transition_duration=0.5, video_durations=[3.7, 5.2])
        content = Path(out).read_text(encoding="utf-8")
        # shot0: 0.0 → 3.7
        # shot1 (last): 3.7 → 3.7 + max(0.1, 5.2-0.5) = 8.4
        assert "00:00:03,700 --> 00:00:08,400" in content

    def test_generate_srt_transition_3_shots(self, tmp_path):
        """3 镜头转场：中间镜头扣转场，最后镜头不扣"""
        from post.subtitle import generate_srt
        shots = [
            {"dialogue": "A", "duration": 4},
            {"dialogue": "B", "duration": 4},
            {"dialogue": "C", "duration": 3},
        ]
        out = str(tmp_path / "test.srt")
        generate_srt(shots, out, transition_duration=0.5)
        content = Path(out).read_text(encoding="utf-8")
        # shot0: 0.0 → 4.0
        # shot1: 4.0 → 4.0 + max(0.1, 4-0.5) = 7.5
        # shot2 (last): 7.5 → 7.5 + max(0.1, 3-0.5) = 10.0
        assert "00:00:00,000 --> 00:00:04,000" in content
        assert "00:00:04,000 --> 00:00:07,500" in content
        assert "00:00:07,500 --> 00:00:10,000" in content


# ══════════════════════════════════════════════════════════
#  post/production.py
# ══════════════════════════════════════════════════════════

class TestProduction:
    """后期合成测试"""

    def test_collect_videos_empty(self, tmp_path):
        from post.production import _collect_videos
        assert _collect_videos(tmp_path) == []

    def test_collect_videos_sorts_numerically(self, tmp_path):
        from post.production import _collect_videos
        # 创建 s003, s001, s002 目录
        for sid in ("003", "001", "002"):
            d = tmp_path / f"s{sid}"
            d.mkdir()
            (d / "video.mp4").write_bytes(b"fake")
        videos = _collect_videos(tmp_path)
        names = [v.parent.name for v in videos]
        assert names == ["s001", "s002", "s003"]

    def test_collect_videos_prefers_synced(self, tmp_path):
        from post.production import _collect_videos
        d = tmp_path / "s001"
        d.mkdir()
        (d / "video.mp4").write_bytes(b"video")
        (d / "synced.mp4").write_bytes(b"synced")
        videos = _collect_videos(tmp_path)
        assert len(videos) == 1
        assert videos[0].name == "synced.mp4"

    def test_collect_videos_falls_back_to_video(self, tmp_path):
        from post.production import _collect_videos
        d = tmp_path / "s001"
        d.mkdir()
        (d / "video.mp4").write_bytes(b"video")
        videos = _collect_videos(tmp_path)
        assert len(videos) == 1
        assert videos[0].name == "video.mp4"

    def test_cleanup_intermediates(self, tmp_path):
        from post.production import _cleanup_intermediates
        # 创建中间文件
        for name in ["episode_01_concat.mp4", "episode_01_subtitled.mp4",
                      "episode_01_with_bgm.mp4", "episode_01_vertical.mp4"]:
            (tmp_path / name).write_bytes(b"tmp")
        _cleanup_intermediates(tmp_path, 1)
        assert list(tmp_path.iterdir()) == []

    def test_rename_final(self, tmp_path):
        from post.production import _rename_final
        src = tmp_path / "episode_01_concat.mp4"
        src.write_bytes(b"video")
        result = _rename_final(src, 1, tmp_path)
        assert result.name == "episode_01_final.mp4"
        assert result.exists()
        assert not src.exists()

    def test_rename_final_fallback_copy(self, tmp_path):
        """跨文件系统时 os.replace 失败，回退到 shutil.copy2"""
        from post.production import _rename_final
        src = tmp_path / "episode_01_concat.mp4"
        src.write_bytes(b"video")
        # 目标已存在（模拟跨文件系统场景）
        final = tmp_path / "episode_01_final.mp4"
        final.write_bytes(b"old")
        result = _rename_final(src, 1, tmp_path)
        assert result.name == "episode_01_final.mp4"
        assert result.read_bytes() == b"video"


# ══════════════════════════════════════════════════════════
#  post/music.py
# ══════════════════════════════════════════════════════════

class TestMusic:
    """配乐生成测试"""

    def test_music_generator_init(self):
        from post.music import MusicGenerator
        gen = MusicGenerator()
        assert gen._config == {}

    def test_music_generator_init_unknown_backend(self):
        from post.music import MusicGenerator
        gen = MusicGenerator(config={"test": True})
        assert gen._config == {"test": True}


# ══════════════════════════════════════════════════════════
#  post/vertical.py
# ══════════════════════════════════════════════════════════

class TestVertical:
    """横转竖测试"""

    def test_find_face_center_no_deps(self):
        """无 face_recognition 时返回 None"""
        from post.vertical import _find_face_center
        # 不存在的文件 → 返回 None（不崩溃）
        assert _find_face_center("/nonexistent.mp4") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
