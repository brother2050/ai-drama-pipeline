"""对话解析 — 台词文本 → 结构化对话行 + WAV 拼接

台词格式约定：
  单人："角色名：台词内容"
  多人："角色名A：台词A\n角色名B：台词B"
  无台词："......"
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["DialogueLine", "parse_dialogue", "EMPTY_DIALOGUE", "concat_wav"]


def _extract_wav_data_chunk(raw: bytes) -> bytes | None:
    """从 WAV 文件中精确提取 data chunk 的 PCM 数据。

    按 RIFF chunk 结构遍历（每个 chunk: 4字节ID + 4字节长度 + 数据），
    不依赖 find(b"data") 的字节搜索，避免误匹配。
    """
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return None
    pos = 12  # 跳过 RIFF header
    while pos + 8 <= len(raw):
        chunk_id = raw[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", raw, pos + 4)[0]
        if chunk_id == b"data":
            data_start = pos + 8
            data_end = min(data_start + chunk_size, len(raw))
            return raw[data_start:data_end]
        # 跳过非 data chunk（+8 是 ID + size 字段，chunk 数据按偶数对齐）
        pos += 8 + chunk_size
        if chunk_size % 2 == 1:
            pos += 1  # RIFF chunk 偶数对齐填充
    return None

# 无台词标记
EMPTY_DIALOGUE = {".", "…"}


@dataclass(frozen=True, slots=True)
class DialogueLine:
    """一条对话"""
    speaker: str    # 角色名（冒号左侧）
    text: str       # 纯台词内容（冒号右侧）


def _is_empty_text(text: str) -> bool:
    """判断台词内容是否等同于无台词（纯省略号/空白/标点）"""
    return not text.strip() or set(text.strip()) <= EMPTY_DIALOGUE


def parse_dialogue(raw: str) -> list[DialogueLine]:
    """解析台词文本为结构化对话行列表。

    格式：每行 "角色名：台词"，多人用换行分隔。
    无台词（"......" 等）返回空列表。
    """
    raw = raw.strip()
    if not raw or set(raw) <= EMPTY_DIALOGUE:
        return []

    lines: list[DialogueLine] = []
    for part in raw.split("\n"):
        part = part.strip()
        if not part or set(part) <= EMPTY_DIALOGUE:
            continue
        speaker, sep, text = part.partition("：")
        if not sep:
            # 兼容英文冒号
            speaker, sep, text = part.partition(":")
        if sep:
            # text 是纯省略号 → 视同无台词（LLM 有时写 "角色名：......"）
            if _is_empty_text(text) and text.strip():
                continue
            lines.append(DialogueLine(speaker=speaker.strip(), text=text.strip()))
        else:
            # 无冒号 → 整行作为台词（降级兼容）
            lines.append(DialogueLine(speaker="", text=part))
    return lines


def concat_wav(parts: list[str | Path], output: str | Path) -> str:
    """拼接多个 WAV 文件为一个。

    所有文件必须是相同采样率/位深/声道的 WAV。
    返回输出路径。
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not parts:
        raise ValueError("concat_wav: parts 不能为空")
    if len(parts) == 1:
        # 单文件：直接复制，无需解析
        data = Path(parts[0]).read_bytes()
        output.write_bytes(data)
        return str(output)

    # 读取所有文件的 PCM 数据（跳过 WAV header）
    pcm_chunks: list[bytes] = []
    sample_rate = bits_per_sample = channels = 0
    for p in parts:
        raw = Path(p).read_bytes()
        if raw[:4] == b"RIFF":
            # 解析 WAV header 提取参数（取第一个文件的参数）
            if not sample_rate and len(raw) >= 44:
                sample_rate = struct.unpack_from("<I", raw, 24)[0]
                bits_per_sample = struct.unpack_from("<H", raw, 34)[0]
                channels = struct.unpack_from("<H", raw, 22)[0]
            elif len(raw) >= 44:
                # 校验后续文件参数一致性
                sr = struct.unpack_from("<I", raw, 24)[0]
                bps = struct.unpack_from("<H", raw, 34)[0]
                ch = struct.unpack_from("<H", raw, 22)[0]
                if sr != sample_rate or bps != bits_per_sample or ch != channels:
                    logger.warning(
                        f"WAV 参数不一致: {Path(p).name} "
                        f"(sr={sr}/bps={bps}/ch={ch}) vs 首文件 "
                        f"(sr={sample_rate}/bps={bits_per_sample}/ch={channels})，跳过")
                    continue
            # 按 chunk 结构定位 data chunk（跳过 fmt/JUNK 等非 data chunk）
            pcm = _extract_wav_data_chunk(raw)
            if pcm is not None:
                pcm_chunks.append(pcm)
            else:
                logger.warning(f"WAV 文件无有效 data chunk: {Path(p).name}，跳过")
        else:
            pcm_chunks.append(raw)

    # 合并 PCM 并写入 WAV
    combined = b"".join(pcm_chunks)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    with open(output, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(combined)))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample))
        f.write(b"data")
        f.write(struct.pack("<I", len(combined)))
        f.write(combined)
    return str(output)
