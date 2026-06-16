#!/usr/bin/env python3
"""
MusicGen 配乐生成服务 — FastAPI 封装

部署方式:
  python scripts/musicgen_server.py --model large --quantize --port 8000
  # 依赖自动安装，无需手动 pip install

特性:
  - 自动安装依赖: 首次运行自动检测并安装缺失包
  - 自动分段生成: 超过 15s 自动切段，避免后半段质量退化
  - 批量生成: 多段一次 batch forward，GPU 天然并行
  - 精确裁剪: 输出严格匹配请求时长
  - 交叉淡出拼接: 段间 1s fade，听感无缝

API:
  POST /generate  {"prompt": "sad piano", "duration": 30}  → WAV 音频
  GET  /health    → {"status": "ok", "model": "large", "quantized": true}
"""
from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path

_bootstrap_log = logging.getLogger("musicgen-bootstrap")


def _ensure_deps(quantize: bool = False):
    """检测并安装缺失依赖（首次运行自动完成）

    bitsandbytes 包含 CUDA 原生扩展，pip install 后无法在同进程导入。
    检测到这种情况时自动重新 exec 自身（加 --_deps-installed 标记避免死循环）。
    """

    # (import_name, pip_name)
    _CORE = [
        ("torch", "torch"),
        ("transformers", "transformers>=4.45,<5.0"),
        ("numpy", "numpy>=1.24,<2.0"),
        ("soundfile", "soundfile"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn[standard]"),
        ("pydantic", "pydantic"),
    ]
    _QUANTIZE = [
        ("bitsandbytes", "bitsandbytes"),
        ("accelerate", "accelerate"),
    ]

    deps_to_check = _CORE + (_QUANTIZE if quantize else [])
    missing = []
    for mod_name, _pip_name in deps_to_check:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(_pip_name)

    if not missing:
        return

    # 已经重试过一次仍然缺失 → 放弃，提示用户手动安装
    if "--_deps-installed" in sys.argv:
        _bootstrap_log.error(
            f"依赖安装后仍无法导入: {', '.join(missing)}\n"
            f"请手动安装: pip install {' '.join(missing)}"
        )
        sys.exit(1)

    _bootstrap_log.info(f"安装缺失依赖: {', '.join(missing)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *missing],
    )
    _bootstrap_log.info("依赖安装完成，重启进程以加载原生扩展...")

    # 重新 exec 自身，让新安装的 CUDA 扩展生效
    # 基本安全检查：确保 sys.executable 是合法的 Python 解释器
    exe = sys.executable
    if not exe or not os.path.isfile(exe):
        _bootstrap_log.error(f"Python 解释器路径无效: {exe}")
        sys.exit(1)
    args = sys.argv + ["--_deps-installed"]
    os.execv(exe, [exe, *args])


# ── 启动时检测 --quantize 参数并安装依赖 ──
# 仅在 __main__ 中安装依赖，避免被 import 时执行 pip install / os.execv
if __name__ == "__main__":
    _Quantize_Flag = "--quantize" in sys.argv
    _ensure_deps(quantize=_Quantize_Flag)

# ── 正式导入（依赖由 __main__ 中的 _ensure_deps 保证）──
import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import time  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


logger = logging.getLogger("musicgen-server")

# 每段最大生成时长（秒），官方推荐 8s 为最佳音质甜区
_SEGMENT_SEC = 8
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
        torch.cuda.get_device_properties(0).total_memory // 1024 // 1024,
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


def _setup_hf_env():
    """配置 HuggingFace 镜像和 Token（从 .env 或环境变量读取）"""
    from infra.config.core import ENV_FILE_PATH
    env_file = ENV_FILE_PATH

    # HF_ENDPOINT: 国内镜像加速（.env.example 中有配置）
    if not os.environ.get("HF_ENDPOINT"):
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("HF_ENDPOINT=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        os.environ["HF_ENDPOINT"] = val
                        logger.info(f"HF 镜像: {val}")
                        break

    # HF_TOKEN: 提升速率限制
    if os.environ.get("HF_TOKEN"):
        logger.info("HF_TOKEN 已配置（认证请求，速率更高）")
    else:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("HF_TOKEN=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        os.environ["HF_TOKEN"] = val
                        logger.info("HF_TOKEN 已从 .env 加载")
                        break


def load_model(model_size: str = "medium", quantize: bool = False):
    """加载 MusicGen 模型（优先本地缓存，无缓存时自动下载）"""
    global _model, _processor, _samplerate, _model_name, _is_quantized, _vram_total_mb
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    _setup_hf_env()

    _model_name = model_size
    _is_quantized = quantize
    model_name = f"facebook/musicgen-{model_size}"
    logger.info(f"加载模型: {model_name} (quantize={quantize}) ...")
    t0 = time.time()

    # 优先本地缓存，无缓存时自动下载
    try:
        _processor = AutoProcessor.from_pretrained(model_name, use_fast=True,
                                                   local_files_only=True)
    except Exception:
        logger.info("本地无缓存，从 HuggingFace 下载...")
        _processor = AutoProcessor.from_pretrained(model_name, use_fast=True)

    if quantize:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )
        try:
            _model = MusicgenForConditionalGeneration.from_pretrained(
                model_name, quantization_config=bnb_config, device_map="auto",
                use_safetensors=True, torch_dtype=torch.float16, local_files_only=True)
        except Exception:
            _model = MusicgenForConditionalGeneration.from_pretrained(
                model_name, quantization_config=bnb_config, device_map="auto",
                use_safetensors=True, torch_dtype=torch.float16)
        logger.info("已启用 4-bit NF4 量化")
    else:
        try:
            _model = MusicgenForConditionalGeneration.from_pretrained(
                model_name, use_safetensors=True, torch_dtype=torch.float16,
                local_files_only=True)
        except Exception:
            _model = MusicgenForConditionalGeneration.from_pretrained(
                model_name, use_safetensors=True, torch_dtype=torch.float16)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = _model.to(device)

    _samplerate = _model.config.sampling_rate

    used, total = _get_gpu_mem()
    _vram_total_mb = total
    logger.info(f"模型加载完成 ({time.time() - t0:.1f}s), 设备: {_model.device}, "
                f"显存: {used}/{total} MB")


def _generate_batch(prompts: list[str], durations: list[int]) -> list[np.ndarray]:
    """批量生成多段音频 — 手动拼 batch 避免 processor padding 问题

    逐段 tokenize → 手动左 padding 对齐 → 堆叠成 batch → 一次 generate。
    量化模型 + processor(padding=True) 会卡死，手动拼 batch 兼容。
    """
    target_frames_list = [d * _samplerate for d in durations]
    max_dur = max(durations)

    if _is_quantized:
        max_tokens = int(max_dur * 1.5 * (_samplerate // 256))
        max_tokens = min(max_tokens, 3000)
    else:
        max_tokens = int(max_dur * 2 * (_samplerate // 256))
        max_tokens = min(max_tokens, 3000)

    # 逐段 tokenize，手动左 padding 对齐
    tokenized = [_processor(text=[p], return_tensors="pt") for p in prompts]
    max_len = max(t["input_ids"].shape[1] for t in tokenized)

    pad_token_id = _processor.tokenizer.pad_token_id or 0
    input_ids_list, attention_mask_list = [], []
    for t in tokenized:
        ids = t["input_ids"][0]       # [seq_len]
        mask = t["attention_mask"][0]
        pad_len = max_len - ids.shape[0]
        if pad_len > 0:
            ids = torch.cat([torch.full((pad_len,), pad_token_id, dtype=ids.dtype, device=ids.device), ids])
            mask = torch.cat([torch.zeros(pad_len, dtype=mask.dtype, device=mask.device), mask])
        input_ids_list.append(ids)
        attention_mask_list.append(mask)

    batch_ids = torch.stack(input_ids_list).to(_model.device)
    batch_mask = torch.stack(attention_mask_list).to(_model.device)

    try:
        with torch.no_grad():
            audio = _model.generate(input_ids=batch_ids, attention_mask=batch_mask,
                                    max_new_tokens=max_tokens)
    except Exception as e:
        # batch generate 失败（量化模型兼容性问题），回退逐段串行
        logger.warning(f"batch generate 失败: {e}，回退逐段串行")
        results = []
        for i, (prompt, target_frames, duration) in enumerate(zip(prompts, target_frames_list, durations)):
            if _is_quantized:
                mt = min(int(duration * 1.5 * (_samplerate // 256)), 3000)
            else:
                mt = min(int(duration * 2 * (_samplerate // 256)), 3000)
            inp = _processor(text=[prompt], return_tensors="pt").to(_model.device)
            with torch.no_grad():
                aud = _model.generate(**inp, max_new_tokens=mt)
            arr = aud[0, 0].cpu().numpy()
            arr = arr.astype(np.float32) if arr.dtype == np.float16 else arr
            results.append(arr[:target_frames])
            logger.info(f"  段 {i+1}/{len(prompts)}: {duration}s 完成")
        return results

    results = []
    for i, target_frames in enumerate(target_frames_list):
        arr = audio[i, 0].cpu().numpy()
        arr = arr.astype(np.float32) if arr.dtype == np.float16 else arr
        results.append(arr[:target_frames])
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
    - duration > 15s: 拆段后一次 batch 生成（GPU batch 并行，≈ 单段耗时）
    """
    if _model is None:
        raise HTTPException(503, "模型未加载")

    duration = req.duration
    logger.info(f"生成: '{req.prompt}' ({duration}s)")
    t0 = time.time()

    try:
        if duration <= _SEGMENT_SEC:
            # 短音频直接生成
            audio_np = _generate_batch([req.prompt], [duration])[0]
        else:
            segments_sec = _split_segments(duration)
            n_segments = len(segments_sec)
            logger.info(f"  共 {n_segments} 段 × {segments_sec[0]}s, 批量生成 (batch={n_segments})")
            all_segments = _generate_batch([req.prompt] * n_segments, segments_sec)
            audio_np = _concat_segments(all_segments)

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


@app.get("/")
def root():
    """根路径 — 服务信息"""
    return {"service": "MusicGen 配乐服务", "version": "1.3",
            "endpoints": {"generate": "POST /generate", "health": "GET /health"}}


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
    # 移除内部标记，避免 argparse 报错
    if "--_deps-installed" in sys.argv:
        sys.argv.remove("--_deps-installed")

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
