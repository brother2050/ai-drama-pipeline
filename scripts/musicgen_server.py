#!/usr/bin/env python3
"""
MusicGen 配乐生成服务 — FastAPI 封装

部署方式:
  1. pip install fastapi uvicorn transformers soundfile torch
  2. python scripts/musicgen_server.py --model medium --port 8000
  3. 项目配置 music.api_url = "http://你的IP:8000/generate"

特性:
  - 自动分段生成: 超过 15s 自动切段拼接，避免后半段质量退化
  - 支持 medium / large 模型，large 可选 --quantize 4-bit 量化
  - T4 (15GB) 推荐 medium; A10/4090/A100 推荐 large

API:
  POST /generate  {"prompt": "sad piano", "duration": 30}  → WAV 音频
  GET  /health    → {"status": "ok", "model": "medium"}
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import time

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("musicgen-server")

# 每段最大生成时长（秒），超过此值会分段。经验上 ≤15s 质量最稳定
_SEGMENT_SEC = 15


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan 事件处理（替代已弃用的 on_event）"""
    yield


app = FastAPI(title="MusicGen 配乐服务", version="1.2", lifespan=lifespan)

# 全局模型（启动时加载）
_model = None
_processor = None
_samplerate = 32000
_model_name = "medium"
_is_quantized = False


class GenRequest(BaseModel):
    """MusicGen 生成请求"""
    prompt: str = Field(..., min_length=1, max_length=500, description="音乐描述")
    duration: int = Field(30, ge=5, le=120, description="生成时长（秒）")


def load_model(model_size: str = "medium", quantize: bool = False):
    """加载 MusicGen 模型"""
    global _model, _processor, _samplerate, _model_name, _is_quantized
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
    logger.info(f"模型加载完成 ({time.time() - t0:.1f}s), 设备: {_model.device}")


def _generate_segment(prompt: str, duration: int) -> np.ndarray:
    """生成单段音频（≤_SEGMENT_SEC 秒）"""
    inputs = _processor(text=[prompt], return_tensors="pt").to(_model.device)
    max_tokens = duration * (_samplerate // 256)
    max_tokens = min(max_tokens, 1500)

    with torch.no_grad():
        audio = _model.generate(**inputs, max_new_tokens=max_tokens)

    return audio[0, 0].cpu().numpy()


def _crossfade(a: np.ndarray, b: np.ndarray, fade_samples: int) -> np.ndarray:
    """两段音频交叉淡入淡出拼接"""
    fade_samples = min(fade_samples, len(a), len(b))
    if fade_samples <= 0:
        return np.concatenate([a, b])

    # a 尾部淡出, b 头部淡入
    fade_out = np.linspace(1.0, 0.0, fade_samples)
    fade_in = np.linspace(0.0, 1.0, fade_samples)

    a_tail = a[-fade_samples:] * fade_out
    b_head = b[:fade_samples] * fade_in

    # 交叉区域叠加
    cross = a_tail + b_head
    return np.concatenate([a[:-fade_samples], cross, b[fade_samples:]])


@app.post("/generate")
def generate(req: GenRequest):
    """生成配乐 → 返回 WAV 音频

    自动分段逻辑:
    - duration ≤ 15s: 直接生成
    - duration > 15s: 切成 N 段 × 15s + 余段，逐段生成后交叉淡出拼接
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
            # 分段生成 + 交叉淡出拼接
            segments = []
            remaining = duration
            seg_idx = 0
            while remaining > 0:
                seg_len = min(remaining, _SEGMENT_SEC)
                logger.info(f"  段 {seg_idx + 1}: {seg_len}s")
                seg = _generate_segment(req.prompt, seg_len)
                segments.append(seg)
                remaining -= seg_len
                seg_idx += 1

            # 交叉淡出拼接（1 秒淡入淡出区）
            fade_samples = _samplerate  # 1 秒
            audio_np = segments[0]
            for seg in segments[1:]:
                audio_np = _crossfade(audio_np, seg, fade_samples)

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
    return {
        "status": "ok",
        "model": f"musicgen-{_model_name}",
        "quantized": _is_quantized,
        "device": str(_model.device),
        "samplerate": _samplerate,
        "segment_sec": _SEGMENT_SEC,
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
