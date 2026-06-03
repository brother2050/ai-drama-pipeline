"""MiMo TTS 共享工具 — PCM→WAV 转换 + 情绪映射

从 mimo_voicedesign.py 和 mimo_voiceclone.py 提取的公共代码。
"""
from __future__ import annotations

import struct
from pathlib import Path

# ── PCM→WAV 转换 ──

# MiMo TTS 输出为 24kHz 16bit 单声道 PCM
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_BITS_PER_SAMPLE = 16
DEFAULT_CHANNELS = 1


def write_wav_or_pcm(raw: bytes, output: str, *,
                     sample_rate: int = DEFAULT_SAMPLE_RATE,
                     bits_per_sample: int = DEFAULT_BITS_PER_SAMPLE,
                     channels: int = DEFAULT_CHANNELS) -> str:
    """将原始音频数据写入 WAV 文件。

    如果 raw 已是 WAV 格式（RIFF header），直接写入。
    否则包装为 WAV 格式后写入。

    Args:
        raw: 原始音频数据（WAV 或 PCM）
        output: 输出文件路径
        sample_rate: 采样率（PCM 模式使用）
        bits_per_sample: 位深（PCM 模式使用）
        channels: 声道数（PCM 模式使用）

    Returns:
        输出文件路径
    """
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as f:
        if raw[:4] == b"RIFF":
            f.write(raw)
        else:
            byte_rate = sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + len(raw)))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample))
            f.write(b"data")
            f.write(struct.pack("<I", len(raw)))
            f.write(raw)
    return output


# ── 情绪映射 ──

# 情绪标签 → 自然语言风格描述（V2.5 导演模式，放在 user 消息）
EMOTION_STYLE = {
    "happy": "用开心愉悦的语调，声音明亮有活力",
    "sad": "用悲伤低沉的语调，声音压抑",
    "angry": "用愤怒生气的语调，声音有力",
    "worried": "用担忧焦虑的语调，声音紧张不安",
    "surprised": "用惊讶意外的语调，声音高扬",
    "smug": "用得意傲慢的语调",
    "serious": "用严肃认真的语调",
    "calm": "用平静从容的语调",
    "determined": "用坚定果断的语调",
    "fearful": "用害怕恐惧的语调",
    "romantic": "用温柔深情的语调",
    "action": "用紧张激烈的语调",
    "neutral": "",
}

# 情绪标签 → V2 风格标签（放在 assistant 消息文本开头 <style>标签</style>）
EMOTION_STYLE_V2 = {
    "happy": "开心",
    "sad": "悲伤",
    "angry": "生气",
    "worried": "担忧",
    "surprised": "惊讶",
    "smug": "得意",
    "serious": "严肃",
    "calm": "平静",
    "determined": "坚定",
    "fearful": "恐惧",
    "romantic": "温柔",
    "action": "紧张",
    "neutral": "",
}
