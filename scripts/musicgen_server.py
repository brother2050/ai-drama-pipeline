#!/usr/bin/env python3
"""
MusicGen 配乐生成服务 — FastAPI 封装

部署方式:
  1. pip install fastapi uvicorn transformers soundfile torch bitsandbytes accelerate
  2. python scripts/musicgen_server.py --model large --quantize --port 8000
  3. 项目配置 music.api_url = "http://你的IP:8000/generate"

特性:
  - 自动分段生成: 超过 15s 自动切段，避免后半段质量退化
  - 4-bit 并行批处理: 量化模型显存低时自动并行生成多段，吞吐量翻倍
  - 交叉淡出拼接: 段间 1s fade，听感无缝
  - 支持 medium / large 两个模型

API:
  POST /generate  {"prompt": "sad piano", "duration": 30}  → WAV 音频
  GET  /health    → {"status": "ok", "model": "large", "quantized": true}
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("musicgen-server")

# 每段最大生成时长（秒），经验上 ≤15s 质量最稳定
_SEGMENT_SEC = 15
# 交叉淡入淡出时长（秒）
_CROSSFADE_SEC = 1.0


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="MusicGen 配乐服务", version="1.3", lifespan=lifespan)

# 全局模型
_model = None
_processor = None
_samplerate = 32000
_model_name = "medium"
_is_quantized = False
_vram_total_mb = 0


class GenRequest(BaseModel):
    """MusicGen 生成请求"""
    prompt: str = Field(..., min_length=1, max_length=500, description="音乐描述")
    duration: int = Field(30, ge=5, le=120, description="生成时长（秒）")


def _get_gpu_mem() -> tuple[int, int]:
    """返回 (used_mb, total_mb)，无 GPU 返回 (0, 0)"""
    if not torch.cuda.is_available():
        return 0, 0
    return (
        torch.cuda.memory_allocated() // 1024 // 1024,
        torch.cuda.get_device_properties(0).total_mem // 1024 // 1024,
    )


def _estimate_parallelism(model_mem_mb: int) -> int:
    """根据模型显存占用和总显存估算最大并行数"""
    if _vram_total_mb <= 0 or model_mem_mb <= 0:
        return 1
    free_mb = _vram_total_mb - model_mem_mb
    # 预留 1GB 给 CUDA overhead
    usable = max(0, free_mb - 1024)
    # 每个并行生成额外需要 ~模型大小 的 KV cache 空间
    n = 1 + usable // max(model_mem_mb, 1)
    return max(1, min(n, 4))  # 上限 4，避免过度并行


def load_model(model_size: str = "medium", quantize: bool = False):
    """加载 MusicGen 模型"""
    global _model, _processor, _samplerate, _model_name, _is_quantized, _vram_total_mb
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    _model_name = model_size
    _is_quantized = quantize
    model_name = f"facebook/musicgen-{model_size}"
    logger.info(f"加载模型: {model_name} (quantize={quantize}) ...")
    t0 = time.time()

    _processor = AutoProcessor.from_pretrained(model_name)

    if quantize:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )
        _model = MusicgenForConditionalGeneration.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map="auto",
        )
        logger.info("已启用 4-bit NF4 量化")
    else:
        _model = MusicgenForConditionalGeneration.from_pretrained(model_name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = _model.to(device)

    _samplerate = _model.config.sampling_rate

    used, total = _get_gpu_mem()
    _vram_total_mb = total
    logger.info(f"模型加载完成 ({time.time() - t0:.1f}s), 设备: {_model.device}, "
                f"显存: {used}/{total} MB")


def _generate_segment(prompt: str, duration: int) -> np.ndarray:
    """生成单段音频"""
    inputs = _processor(text=[prompt], return_tensors="pt").to(_model.device)
    max_tokens = duration * (_samplerate // 256)
    max_tokens = min(max_tokens, 1500)

    with torch.no_grad():
        audio = _model.generate(**inputs, max_new_tokens=max_tokens)

    arr = audio[0, 0].cpu().numpy()
    return arr.astype(np.float32) if arr.dtype == np.float16 else arr


def _generate_batch(prompts: list[str], durations: list[int]) -> list[np.ndarray]:
    """批量生成多段音频（单次 forward，吞吐更高）

    注意: MusicGen 的 generate() 支持 batch_size > 1，
    但所有 prompt 必须同时生成，长度取最长的 max_tokens。
    """
    inputs = _processor(text=prompts, return_tensors="pt", padding=True).to(_model.device)
    max_tokens = max(d * (_samplerate // 256) for d in durations)
    max_tokens = min(max_tokens, 1500)

    with torch.no_grad():
        audio = _model.generate(**inputs, max_new_tokens=max_tokens)

    results = []
    for i in range(len(prompts)):
        arr = audio[i, 0].cpu().numpy()
        results.append(arr.astype(np.float32) if arr.dtype == np.float16 else arr)
    return results


def _crossfade(a: np.ndarray, b: np.ndarray, fade_samples: int) -> np.ndarray:
    """两段音频交叉淡入淡出拼接"""
    fade_samples = min(fade_samples, len(a), len(b))
    if fade_samples <= 0:
        return np.concatenate([a, b])

    fade_out = np.linspace(1.0, 0.0, fade_samples)
    fade_in = np.linspace(0.0, 1.0, fade_samples)

    cross = a[-fade_samples:] * fade_out + b[:fade_samples] * fade_in
    return np.concatenate([a[:-fade_samples], cross, b[fade_samples:]])


def _split_segments(duration: int) -> list[int]:
    """将总时长拆分为多段，返回每段时长列表"""
    segments = []
    remaining = duration
    while remaining > 0:
        seg_len = min(remaining, _SEGMENT_SEC)
        segments.append(seg_len)
        remaining -= seg_len
    return segments


def _concat_segments(segments: list[np.ndarray]) -> np.ndarray:
    """交叉淡出拼接所有段"""
    fade = int(_samplerate * _CROSSFADE_SEC)
    result = segments[0]
    for seg in segments[1:]:
        result = _crossfade(result, seg, fade)
    return result


@app.post("/generate")
def generate(req: GenRequest):
    """生成配乐 → 返回 WAV 音频

    策略:
    - duration ≤ 15s: 直接生成
    - duration > 15s + 量化模型: 批量并行生成多段（利用剩余显存）
    - duration > 15s + 非量化: 逐段串行生成
    """
    if _model is None:
        raise HTTPException(503, "模型未加载")

    duration = req.duration
    logger.info(f"生成: '{req.prompt}' ({duration}s)")
    t0 = time.time()

    try:
        if duration <= _SEGMENT_SEC:
            # 短音频直接生成
            audio_np = _generate_segment(req.prompt, duration)
        else:
            segments_sec = _split_segments(duration)
            n_segments = len(segments_sec)

            # 计算并行度
            used, _ = _get_gpu_mem()
            parallel = _estimate_parallelism(used) if _is_quantized else 1
            parallel = min(parallel, n_segments)

            logger.info(f"  共 {n_segments} 段, 并行度: {parallel}")

            if parallel > 1:
                # 批量并行生成
                all_segments = []
                for batch_start in range(0, n_segments, parallel):
                    batch_end = min(batch_start + parallel, n_segments)
                    batch_durations = segments_sec[batch_start:batch_end]
                    batch_prompts = [req.prompt] * len(batch_durations)
                    logger.info(f"  批次 {batch_start//parallel + 1}: "
                                f"段 {batch_start+1}-{batch_end}")
                    batch_results = _generate_batch(batch_prompts, batch_durations)
                    all_segments.extend(batch_results)
                audio_np = _concat_segments(all_segments)
            else:
                # 串行生成
                seg_parts = []
                for i, seg_len in enumerate(segments_sec):
                    logger.info(f"  段 {i + 1}/{n_segments}: {seg_len}s")
                    seg = _generate_segment(req.prompt, seg_len)
                    seg_parts.append(seg)
                audio_np = _concat_segments(seg_parts)

        # 写入 WAV buffer
        buf = io.BytesIO()
        sf.write(buf, audio_np, _samplerate, format="WAV")
        buf.seek(0)

        elapsed = time.time() - t0
        actual_sec = len(audio_np) / _samplerate
        logger.info(f"生成完成: {actual_sec:.1f}s 音频, 耗时 {elapsed:.1f}s")

        return Response(content=buf.getvalue(), media_type="audio/wav")

    except Exception as e:
        logger.error(f"生成失败: {e}", exc_info=True)
        raise HTTPException(500, f"生成失败: {e}")


@app.get("/health")
def health():
    """健康检查"""
    if _model is None:
        return {"status": "loading", "model": None}
    used, total = _get_gpu_mem()
    parallel = _estimate_parallelism(used) if _is_quantized else 1
    return {
        "status": "ok",
        "model": f"musicgen-{_model_name}",
        "quantized": _is_quantized,
        "device": str(_model.device),
        "samplerate": _samplerate,
        "segment_sec": _SEGMENT_SEC,
        "vram_used_mb": used,
        "vram_total_mb": total,
        "max_parallel": parallel,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MusicGen 配乐生成服务")
    parser.add_argument("--model", default="medium", choices=["small", "medium", "large"],
                        help="模型大小 (default: medium)")
    parser.add_argument("--quantize", action="store_true",
                        help="启用 4-bit 量化（large 模型推荐，显存从 ~16GB 降到 ~4GB）")
    parser.add_argument("--port", type=int, default=8000, help="服务端口 (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (default: 0.0.0.0)")
    args = parser.parse_args()

    if args.model == "large" and not args.quantize:
        logger.info("提示: large 模型建议加 --quantize 参数，否则可能 OOM")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    load_model(args.model, quantize=args.quantize)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
