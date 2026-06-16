#!/usr/bin/env python3
"""AI Toolkit 轻量 REST API 包装 — 部署在 GPU 服务器上

在 AI Toolkit 所在机器上启动:
    pip install fastapi uvicorn
    python scripts/ai_toolkit_api.py --port 7860 --ai-toolkit-path /path/to/ai-toolkit

API:
    POST /train         — 启动训练（multipart: images + form params）
    GET  /status/{id}   — 查询训练状态
    GET  /health        — 健康检查
"""
from __future__ import annotations

from infra.config import save_yaml
from infra.constants import STATUS_RUNNING, STATUS_DONE, STATUS_ERROR
import argparse
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("ai_toolkit_api")

app = FastAPI(title="AI Toolkit Training API")

# ── 全局状态 ──
_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_AI_TOOLKIT_PATH = ""
_OUTPUT_DIR = Path(os.environ.get("AI_TOOLKIT_OUTPUT_DIR", str(Path.home() / ".ai_drama" / "training_output")))


def _update_task(task_id: str, **kwargs):
    with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)


@app.get("/health")
def health():
    return {"status": "ok", "ai_toolkit_path": _AI_TOOLKIT_PATH}


def _build_local_train_config(trigger_word: str, lora_name: str, steps: int,
                              learning_rate: str, network_dim: int,
                              img_dir: Path, output_dir: Path,
                              res_list: list[int], base_model: str) -> dict:
    """构建本地 AI Toolkit 训练配置"""
    return {
        "job": "extension",
        "config": {
            "name": lora_name,
            "process": [{
                "type": "sd_trainer",
                "training_folder": str(output_dir),
                "device": "cuda:0",
                "trigger_word": trigger_word,
                "network": {"type": "lora", "linear": network_dim, "linear_alpha": network_dim},
                "save": {"dtype": "float16", "save_every": max(1, steps // 4), "max_step_saves_to_keep": 2},
                "datasets": [{"folder_path": str(img_dir), "caption_ext": "txt",
                              "caption_dropout_rate": 0.05, "shuffle_tokens": False,
                              "cache_latents_to_disk": True, "resolution": res_list}],
                "train": {
                    "batch_size": 1, "steps": steps, "gradient_accumulation_steps": 1,
                    "train_unet": True, "train_text_encoder": False,
                    "gradient_checkpointing": True, "noise_scheduler": "flowmatch",
                    "optimizer": "adamw8bit", "lr": float(learning_rate),
                    "ema_config": {"use_ema": True, "ema_decay": 0.99}, "dtype": "bf16",
                },
                "model": {"name_or_path": base_model, "is_flux": True, "quantize": True},
                "sample": {"sampler": "flowmatch", "sample_every": steps,
                           "width": res_list[0], "height": res_list[0],
                           "prompts": [f"{trigger_word} portrait"]},
            }],
        },
    }


@app.post("/train")
async def train(
    images: list[UploadFile] = File(..., description="训练图片"),
    trigger_word: str = Form("ohwx person"),
    lora_name: str = Form("my_lora"),
    steps: int = Form(600),
    learning_rate: str = Form("1e-4"),
    network_dim: int = Form(16),
    resolution: str = Form("512"),
    base_model: str = Form("ostris/Flex.1-alpha"),
):
    task_id = str(uuid.uuid4())[:8]
    task_dir = _OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # 保存图片 + 生成 caption
    img_dir = task_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for img in images:
        with open(img_dir / img.filename, "wb") as f:
            shutil.copyfileobj(img.file, f)
    for img_file in img_dir.iterdir():
        if img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            cap_file = img_file.with_suffix(".txt")
            if not cap_file.exists():
                cap_file.write_text(trigger_word, encoding="utf-8")

    res_list = [int(r.strip()) for r in resolution.split(",")]
    if len(res_list) == 1:
        res_list *= 3

    config = _build_local_train_config(trigger_word, lora_name, steps, learning_rate,
                                       network_dim, img_dir, task_dir / "output", res_list, base_model)
    config_path = task_dir / "config.yaml"
    save_yaml(config_path, config)

    _tasks[task_id] = {"status": STATUS_RUNNING, "progress": 0, "message": "训练启动中...",
                       "lora_name": lora_name, "start_time": time.time()}

    thread = threading.Thread(target=_run_training, args=(task_id, config_path, task_dir))
    thread.daemon = True
    thread.start()

    return {"task_id": task_id, "status": "submitted"}


def _run_training(task_id: str, config_path: Path, task_dir: Path):
    """后台执行 AI Toolkit 训练"""
    global _AI_TOOLKIT_PATH
    run_py = Path(_AI_TOOLKIT_PATH) / "run.py"
    if not run_py.exists():
        _update_task(task_id, status=STATUS_ERROR, message=f"run.py 不存在: {run_py}")
        return

    try:
        cmd = ["python", str(run_py), str(config_path)]
        logger.info(f"[{task_id}] 启动训练: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                logger.info(f"[{task_id}] {line}")
                _parse_progress(task_id, line)
        finally:
            # 确保子进程资源释放（异常时避免僵尸进程）
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            proc.stdout.close()

        _finalize_training(task_id, task_dir, proc.returncode)

    except Exception as e:
        logger.error(f"[{task_id}] 训练异常: {e}", exc_info=True)
        _update_task(task_id, status=STATUS_ERROR, message=str(e))


def _parse_progress(task_id: str, line: str) -> None:
    """从训练日志中解析进度（正则匹配多种格式）"""
    import re
    m = re.search(r'(\d+)\s*/\s*(\d+)', line)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            _update_task(task_id, progress=int(current / total * 100), message=f"Step {current}/{total}")


def _finalize_training(task_id: str, task_dir: Path, returncode: int) -> None:
    """训练结束后的结果处理"""
    if returncode != 0:
        _update_task(task_id, status=STATUS_ERROR, message=f"训练退出码: {returncode}")
        return
    output_dir = task_dir / "output"
    lora_files = list(output_dir.rglob("*.safetensors"))
    if lora_files:
        _update_task(task_id, status=STATUS_DONE, progress=100, message="训练完成", result_path=str(lora_files[-1]))
    else:
        _update_task(task_id, status=STATUS_ERROR, message="训练完成但未找到 .safetensors 文件")


@app.get("/status/{task_id}")
def get_status(task_id: str):
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "任务不存在"})
    return task


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Toolkit REST API")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--ai-toolkit-path", required=True, help="AI Toolkit 安装路径")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="训练输出目录")
    args = parser.parse_args()

    _AI_TOOLKIT_PATH = args.ai_toolkit_path
    _OUTPUT_DIR = Path(args.output_dir)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
