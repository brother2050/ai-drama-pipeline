"""测试 — 对话解析 + WAV 拼接"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── parse_dialogue ──

class TestParseDialogue:
    def test_single_line(self):
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("林夏：你好吗")
        assert len(lines) == 1
        assert lines[0].speaker == "林夏"
        assert lines[0].text == "你好吗"

    def test_multi_line(self):
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("张老板：这玩意儿贵？\n林夏：确实有点贵。")
        assert len(lines) == 2
        assert lines[0].speaker == "张老板"
        assert lines[0].text == "这玩意儿贵？"
        assert lines[1].speaker == "林夏"
        assert lines[1].text == "确实有点贵。"

    def test_empty_marker(self):
        from engines.dialogue import parse_dialogue
        assert parse_dialogue("......") == []
        assert parse_dialogue("……") == []
        assert parse_dialogue("") == []

    def test_english_colon(self):
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("linxia:hello")
        assert len(lines) == 1
        assert lines[0].speaker == "linxia"
        assert lines[0].text == "hello"

    def test_no_colon_fallback(self):
        """无冒号时整行作为台词（降级兼容）"""
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("你好世界")
        assert len(lines) == 1
        assert lines[0].speaker == ""
        assert lines[0].text == "你好世界"

    def test_empty_speaker(self):
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("：你好")
        assert len(lines) == 1
        assert lines[0].speaker == ""
        assert lines[0].text == "你好"

    def test_empty_text_after_colon(self):
        """'林夏：' → speaker='林夏', text=''"""
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("林夏：")
        assert len(lines) == 1
        assert lines[0].speaker == "林夏"
        assert lines[0].text == ""

    def test_multi_line_with_empty(self):
        """多人对话中混有空行"""
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("林夏：你好\n\n顾辰：嗯")
        assert len(lines) == 2

    def test_immutable(self):
        from engines.dialogue import parse_dialogue, DialogueLine
        lines = parse_dialogue("林夏：你好")
        assert isinstance(lines[0], DialogueLine)
        with pytest.raises(AttributeError):
            lines[0].speaker = "changed"

    def test_whitespace_trimmed(self):
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("  林夏 ： 你好  ")
        assert lines[0].speaker == "林夏"
        assert lines[0].text == "你好"

    def test_dialogue_en_not_parsed(self):
        """dialogue_en 是纯英文翻译，不含角色名前缀"""
        from engines.dialogue import parse_dialogue
        lines = parse_dialogue("How are you?")
        assert len(lines) == 1
        assert lines[0].speaker == ""
        assert lines[0].text == "How are you?"


# ── concat_wav ──

def _make_wav(pcm: bytes, sr=24000, bits=16, ch=1) -> bytes:
    """构造最小 WAV"""
    byte_rate = sr * ch * bits // 8
    block_align = ch * bits // 8
    header = struct.pack("<4sI4s4sIHHIIHH4sI",
                         b"RIFF", 36 + len(pcm), b"WAVE",
                         b"fmt ", 16, 1, ch, sr, byte_rate, block_align, bits,
                         b"data", len(pcm))
    return header + pcm


class TestConcatWav:
    def test_single_file(self, tmp_path):
        from engines.dialogue import concat_wav
        pcm = b"\x00\x01" * 100
        wav = _make_wav(pcm)
        src = tmp_path / "a.wav"
        src.write_bytes(wav)
        out = tmp_path / "out.wav"
        concat_wav([src], out)
        assert out.read_bytes() == wav

    def test_two_files(self, tmp_path):
        from engines.dialogue import concat_wav
        pcm1 = b"\x00\x01" * 50
        pcm2 = b"\x02\x03" * 50
        (tmp_path / "a.wav").write_bytes(_make_wav(pcm1))
        (tmp_path / "b.wav").write_bytes(_make_wav(pcm2))
        out = tmp_path / "out.wav"
        concat_wav([tmp_path / "a.wav", tmp_path / "b.wav"], out)
        result = out.read_bytes()
        assert result[:4] == b"RIFF"
        # PCM 数据应为两段拼接
        idx = result.find(b"data")
        size = struct.unpack_from("<I", result, idx + 4)[0]
        assert size == len(pcm1) + len(pcm2)

    def test_preserves_params(self, tmp_path):
        from engines.dialogue import concat_wav
        pcm = b"\x00" * 100
        (tmp_path / "a.wav").write_bytes(_make_wav(pcm, sr=44100, bits=16, ch=2))
        (tmp_path / "b.wav").write_bytes(_make_wav(pcm, sr=44100, bits=16, ch=2))
        out = tmp_path / "out.wav"
        concat_wav([tmp_path / "a.wav", tmp_path / "b.wav"], out)
        result = out.read_bytes()
        sr = struct.unpack_from("<I", result, 24)[0]
        assert sr == 44100
