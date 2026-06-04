#!/usr/bin/env python3
"""
MusicGen 配乐生成服务 — FastAPI 封装

部署方式:
  1. pip install fastapi uvicorn transformers soundfile torch bitsandbytes accelerate
  2. python scripts/musicgen_server.py --model large --quantize --port 8000
  3. 项目配置 music.api_url = "http://你的IP:8000/generate"

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

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("musicgen-server")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan 事件处理（替代已弃用的 on_event）"""
    yield


app = FastAPI(title="MusicGen 配乐服务", version="1.1", lifespan=lifespan)

# 全局模型（启动时加载）
_model = None
_processor = None
_samplerate = 32000


class GenRequest(BaseModel):
    """MusicGen 生成请求"""
    prompt: str = Field(..., min_length=1, max_length=500, description="音乐描述")
    duration: int = Field(30, ge=5, le=120, description="生成时长（秒）")


def load_model(model_size: str = "medium", quantize: bool = False):
    """加载 MusicGen 模型

    Args:
        model_size: small / medium / large
        quantize: 是否使用 4-bit 量化（large 模型推荐开启）
    """
    global _model, _processor, _samplerate
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

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


@app.post("/generate")
def generate(req: GenRequest):
    """生成配乐 → 返回 WAV 音频"""
    if _model is None:
        raise HTTPException(503, "模型未加载")

    logger.info(f"生成: '{req.prompt}' ({req.duration}s)")
    t0 = time.time()

    try:
        inputs = _processor(text=[req.prompt], return_tensors="pt").to(_model.device)
        max_tokens = req.duration * (_samplerate // 256)  # 粗略: 每 token ≈ 256 samples
        max_tokens = min(max_tokens, 1500)  # 上限保护

        with torch.no_grad():
            audio = _model.generate(**inputs, max_new_tokens=max_tokens)

        audio_np = audio[0, 0].cpu().numpy()

        # 写入 WAV buffer
        buf = io.BytesIO()
        sf.write(buf, audio_np, _samplerate, format="WAV")
        buf.seek(0)

        elapsed = time.time() - t0
        logger.info(f"生成完成: {len(audio_np)/_samplerate:.1f}s 音频, 耗时 {elapsed:.1f}s")

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
        "model": f"musicgen-{args.model}",
        "quantized": args.quantize,
        "device": str(_model.device),
        "samplerate": _samplerate,
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
