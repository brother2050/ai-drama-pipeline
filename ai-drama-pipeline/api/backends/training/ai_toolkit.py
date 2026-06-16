"""AI Toolkit 训练后端 — 通过原生 Web UI API 远程调用 ostris/ai-toolkit 训练 LoRA

AI Toolkit 是 Flux LoRA 训练质量最好的开源工具，原生支持量化训练（12GB 可跑）。

部署方式:
  1. 在 GPU 服务器上安装 AI Toolkit:
     git clone https://github.com/ostris/ai-toolkit.git
     cd ai-toolkit && git checkout next && pip install -r requirements.txt

  2. 启动 Web UI:
     python run.py --ui
     （默认运行在 http://localhost:8675）

  3. 配置 config/system.yaml:
     training:
       backend: ai-toolkit
       api_url: http://<gpu-server>:8675

API 使用 AI Toolkit 原生 Next.js API（v0.9.14+）:
  POST /api/datasets/create   — 创建数据集
  POST /api/datasets/upload   — 上传图片到数据集
  POST /api/jobs              — 创建训练作业
  GET  /api/jobs/<id>/start   — 启动作业
  GET  /api/jobs?id=<id>      — 查询作业状态
  GET  /api/jobs/<id>/log     — 查看作业日志
  GET  /api/settings          — 获取服务端设置
  GET  /api/gpu               — GPU 状态

LoRA 文件命名规范:
  训练完成后，将 .safetensors 文件放入项目的 assets/loras/ 目录，
  文件名必须为: {char_id}_lora.safetensors
  例如: ch_8a3f2b1c_lora.safetensors

  项目查找 LoRA 的优先级:
    1. proj_{hash8}_{char_id}_{char_id}_lora.safetensors  （comfyui_asset_name 生成）
    2. {char_id}_lora.safetensors
    3. {char_id}.safetensors
    4. assets/characters/{char_id}/lora/*.safetensors
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from api.registry import BackendMeta, registry
from infra.config import ProjectPaths

logger = logging.getLogger(__name__)

__all__ = ["AIToolkitTrainer", "TrainingJobConfig", "TrainLoraParams"]


@dataclass
class TrainingJobConfig:
    """训练作业配置参数 — 消除 _build_job_config 的 9 个参数"""
    dataset_name: str = ""
    trigger_word: str = ""
    lora_name: str = ""
    steps: int = 600
    learning_rate: str = "1e-4"
    rank: int = 16
    resolution: int = 512
    conv_rank: int = 0
    sample_prompts: list[str] = field(default_factory=list)


@dataclass
class TrainLoraParams:
    """LoRA 训练参数 — 消除 train_lora 的 9 个参数"""
    char_id: str
    images_dir: str
    trigger_word: str = ""
    steps: int = 600
    learning_rate: float = 1e-4
    rank: int = 16
    resolution: str = "512x768"
    output_name: str = ""
    progress_cb: Callable[[int, int, str], None] | None = None

MAX_IMAGES = 150


class AIToolkitTrainer:
    """AI Toolkit 远程 LoRA 训练后端（原生 API）"""

    def __init__(self, config: dict):
        self._api_url = (config.get("api_url")
                         or config.get("training", {}).get("api_url", ""))
        if not self._api_url:
            raise ValueError("AI Toolkit api_url 未配置，请在 system.yaml 的 training.api_url 中设置")
        self._api_key = (config.get("api_key")
                         or config.get("training", {}).get("api_key", "")
                         or os.environ.get("AI_TOOLKIT_API_KEY", ""))
        self._gpu_ids = str(config.get("gpu_ids")
                            or config.get("training", {}).get("gpu_ids", "0"))
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        self._project_dir = (config.get("project_dir")
                             or config.get("_project_dir") or "")
        if not self._project_dir:
            logger.warning("AIToolkitTrainer: project_dir 为空，下载结果可能失败")
        self._paths = ProjectPaths(self._project_dir) if self._project_dir else None
        from infra.http_pool import get_client
        self._client = get_client(timeout=self._timeout)

        # 训练参数默认值
        defaults = config.get("defaults", {})
        self._default_resolution = self._parse_resolution(
            defaults.get("resolution", 512))
        self._default_learning_rate = str(defaults.get("learning_rate", "1e-4"))
        self._default_network_dim = int(defaults.get("network_dim", 16))
        self._default_conv_dim = int(defaults.get("conv_dim", 16))
        self._default_steps = int(defaults.get("steps", 600))
        self._base_model = str(defaults.get("base_model", "ostris/Flex.1-alpha"))
        self._arch = str(defaults.get("arch", ""))
        self._quantize_type = str(defaults.get("quantize_type", "qfloat8"))
        self._timestep_type = str(defaults.get("timestep_type", "sigmoid"))
        self._save_format = str(defaults.get("save_format", "diffusers"))
        self._use_ema = bool(defaults.get("use_ema", False))

    @property
    def name(self) -> str:
        return "ai-toolkit"

    def _headers(self) -> dict:
        """JSON 请求 headers"""
        from infra.http_pool import auth_headers
        return auth_headers(self._api_key)

    def _auth_headers(self) -> dict:
        """仅含认证的 headers（用于 multipart 等非 JSON 请求）"""
        from infra.http_pool import auth_headers
        return auth_headers(self._api_key, content_type="")

    def _collect_images(self, images_dir: str) -> list[str]:
        """收集目录中的图片文件路径，最多 MAX_IMAGES 张"""
        img_dir = Path(images_dir)
        if not img_dir.exists():
            return []
        paths = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            paths.extend(str(p) for p in img_dir.glob(ext))
        # 也收集子目录（如 outfit 子目录）
        for sub in img_dir.iterdir():
            if sub.is_dir():
                for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    paths.extend(str(p) for p in sub.glob(ext))
        paths.sort()
        return paths[:MAX_IMAGES]

    def _validate_paths(self, img_paths: list[str]) -> list[str]:
        """验证图片路径有效性"""
        valid = []
        for p in img_paths:
            if not p:
                continue
            try:
                if Path(p).exists():
                    valid.append(p)
                else:
                    logger.warning(f"  跳过不存在的图片: {p}")
            except (TypeError, OSError) as e:
                logger.warning(f"  跳过无效路径 {p}: {e}")
        return valid

    @staticmethod
    def _parse_resolution(resolution: str | int) -> int:
        """解析分辨率: 512, "512", "512x768" → 512"""
        if isinstance(resolution, int):
            return resolution
        try:
            return int(str(resolution).split("x")[0])
        except (ValueError, AttributeError):
            return 512

    # ────────────────────────────────────────────────
    # 原生 API 调用
    # ────────────────────────────────────────────────

    def _api_get_settings(self) -> dict:
        """GET /api/settings — 获取服务端设置（训练目录、数据集目录）"""
        url = f"{self._api_url.rstrip('/')}/api/settings"
        resp = self._client.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_create_dataset(self, name: str) -> str:
        """POST /api/datasets/create — 创建数据集，返回清理后的名称"""
        url = f"{self._api_url.rstrip('/')}/api/datasets/create"
        resp = self._client.post(url, json={"name": name},
                          headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise RuntimeError(f"创建数据集失败: {result['error']}")
        return result.get("name", name)

    def _api_upload_images(self, dataset_name: str, img_paths: list[str]) -> list[str]:
        """POST /api/datasets/upload — 上传图片到数据集

        Args:
            dataset_name: 数据集名称（已清理）
            img_paths: 图片文件路径列表

        Returns:
            上传成功的文件名列表
        """
        import mimetypes

        url = f"{self._api_url.rstrip('/')}/api/datasets/upload"

        # 构建 multipart 文件（确保异常时关闭所有句柄）
        open_files = []
        try:
            files = []
            for p in img_paths:
                fh = open(p, "rb")
                open_files.append(fh)
                mime = mimetypes.guess_type(p)[0] or "image/png"
                files.append(("files", (Path(p).name, fh, mime)))

            data = {"datasetName": dataset_name}
            resp = self._client.post(url, files=files, data=data,
                              headers=self._auth_headers(),
                              timeout=120)
            resp.raise_for_status()
            result = resp.json()
            if result.get("error"):
                raise RuntimeError(f"上传图片失败: {result['error']}")
            return result.get("files", [])
        finally:
            for fh in open_files:
                try:
                    fh.close()
                except Exception:
                    pass

    def _api_create_job(self, name: str, job_config: dict) -> dict:
        """POST /api/jobs — 创建训练作业

        Args:
            name: 作业名称
            job_config: AI Toolkit 配置（YAML 结构转为 dict）

        Returns:
            作业对象（含 id 字段）
        """
        url = f"{self._api_url.rstrip('/')}/api/jobs"
        body = {
            "name": name,
            "gpu_ids": self._gpu_ids,
            "job_config": job_config,
            "job_type": "train",
        }
        resp = self._client.post(url, json=body,
                          headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise RuntimeError(f"创建作业失败: {result['error']}")
        return result

    def _api_start_job(self, job_id: str) -> dict:
        """GET /api/jobs/<id>/start — 启动作业（加入队列）"""
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/start"
        resp = self._client.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_get_job(self, job_id: str) -> dict:
        """GET /api/jobs?id=<id> — 查询单个作业状态"""
        url = f"{self._api_url.rstrip('/')}/api/jobs"
        resp = self._client.get(url, params={"id": job_id},
                         headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_get_job_log(self, job_id: str) -> str:
        """GET /api/jobs/<id>/log — 获取作业日志"""
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/log"
        resp = self._client.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("log", "")

    # ────────────────────────────────────────────────
    # 配置构建
    # ────────────────────────────────────────────────

    def _build_model_config(self) -> tuple[dict[str, Any], bool]:
        """构建模型配置 → (model_cfg, is_flex)"""
        arch = self._arch
        if not arch:
            arch = "flex1" if "flex" in self._base_model.lower() else "flux"
        model_cfg: dict[str, Any] = {
            "name_or_path": self._base_model,
            "quantize": True, "qtype": self._quantize_type,
            "quantize_te": True, "qtype_te": self._quantize_type,
            "arch": arch,
        }
        return model_cfg, arch == "flex1"

    def _build_train_config(self, cfg: TrainingJobConfig, is_flex: bool,
                            res_buckets: list[int]) -> dict:
        """构建训练 + 数据集 + 采样配置"""
        network_cfg: dict[str, Any] = {"type": "lora", "linear": cfg.rank, "linear_alpha": cfg.rank}
        if cfg.conv_rank > 0:
            network_cfg["conv"] = cfg.conv_rank
            network_cfg["conv_alpha"] = cfg.conv_rank

        sample_prompts = cfg.sample_prompts or [
            f"{cfg.trigger_word} portrait, cinematic lighting",
            f"{cfg.trigger_word} casual outfit, outdoor",
            f"{cfg.trigger_word} close-up, studio lighting",
        ]

        return {
            "type": "diffusion_trainer",
            "training_folder": "output", "device": "cuda:0",
            "trigger_word": cfg.trigger_word,
            "network": network_cfg,
            "save": {"dtype": "bf16", "save_every": max(1, cfg.steps // 4),
                     "max_step_saves_to_keep": 4, "save_format": self._save_format},
            "datasets": [{"folder_path": cfg.dataset_name, "caption_ext": "txt",
                          "caption_dropout_rate": 0.05, "shuffle_tokens": False,
                          "cache_latents_to_disk": True, "resolution": res_buckets}],
            "train": {
                "batch_size": 1, "steps": cfg.steps,
                "gradient_accumulation_steps": 1, "train_unet": True,
                "train_text_encoder": False, "gradient_checkpointing": True,
                "noise_scheduler": "flowmatch", "optimizer": "adamw8bit",
                "timestep_type": self._timestep_type,
                "optimizer_params": {"weight_decay": 0.0001},
                "lr": float(cfg.learning_rate),
                "ema_config": {"use_ema": self._use_ema, "ema_decay": 0.99},
                "dtype": "bf16", "loss_type": "mse",
                "bypass_guidance_embedding": is_flex,
            },
            "model": None,  # filled by caller
            "sample": {
                "sampler": "flowmatch", "sample_every": max(1, cfg.steps // 4),
                "width": res_buckets[0], "height": res_buckets[1],
                "samples": [{"prompt": p} for p in sample_prompts],
                "neg": "", "seed": 42, "walk_seed": True,
                "guidance_scale": 4, "sample_steps": 30,
            },
            "logging": {"log_every": 1, "use_ui_logger": True},
        }

    def _build_job_config(self, cfg: TrainingJobConfig) -> dict:
        """构建 AI Toolkit 训练配置（与 Web UI 的 New Job 表单一致）"""
        res_buckets = ([cfg.resolution] * 3 if isinstance(cfg.resolution, int)
                       else list(cfg.resolution) if cfg.resolution else [512, 768, 1024])

        model_cfg, is_flex = self._build_model_config()
        process = self._build_train_config(cfg, is_flex, res_buckets)
        process["model"] = model_cfg

        return {"job": "extension", "config": {"name": cfg.lora_name, "process": [process]}}

    # ────────────────────────────────────────────────
    # 主入口
    # ────────────────────────────────────────────────

    def _prepare_dataset(self, char_id: str, images_dir: str,
                         trigger_word: str) -> tuple[str, list[str]]:
        """收集图片 → 创建数据集 → 上传图片和 caption。返回 (dataset_name, img_paths)"""
        img_paths = self._validate_paths(self._collect_images(images_dir))
        if not img_paths:
            raise FileNotFoundError(f"训练图片目录中无有效图片: {images_dir}")

        dataset_name = self._api_create_dataset(f"lora_{char_id}_{int(time.time())}")
        logger.info(f"  数据集已创建: {dataset_name}")

        uploaded = self._api_upload_images(dataset_name, img_paths)
        logger.info(f"  已上传 {len(uploaded)} 张图片到数据集 {dataset_name}")

        # 生成 caption 文件（每张图一个 .txt）
        caption_files = []
        for p in img_paths:
            cap_path = Path(p).with_suffix(".txt")
            if not cap_path.exists():
                cap_path.write_text(trigger_word, encoding="utf-8")
                caption_files.append(str(cap_path))
        if caption_files:
            try:
                self._api_upload_images(dataset_name, caption_files)
                logger.info(f"  已上传 {len(caption_files)} 个 caption 文件")
            except Exception as e:
                logger.warning(f"  caption 文件上传失败: {e}")

        return dataset_name, img_paths

    def _submit_training(self, char_id: str, dataset_name: str,
                         trigger_word: str, output_name: str,
                         steps: int, lr_str: str, res_val: int,
                         rank: int | None = None, conv_rank: int = 0) -> str:
        """构建配置 → 创建作业 → 启动作业。返回 job_id"""
        job_config = self._build_job_config(TrainingJobConfig(
            dataset_name=dataset_name, trigger_word=trigger_word,
            lora_name=output_name, steps=steps, learning_rate=lr_str,
            rank=rank if rank is not None else self._default_network_dim,
            resolution=res_val,
            conv_rank=conv_rank if conv_rank > 0 else self._default_conv_dim))

        job = self._api_create_job(f"lora_{char_id}_{int(time.time())}", job_config)
        job_id = job.get("id", "")
        if not job_id:
            raise RuntimeError(f"API 未返回作业 ID: {job}")
        logger.info(f"  训练作业已创建: {job_id}")

        self._api_start_job(job_id)
        logger.info(f"  训练作业已加入队列: {job_id}")
        return job_id

    def _poll_training(self, job_id: str, total_steps: int,
                       progress_cb: Callable[[int, int, str], None] | None = None) -> None:
        """轮询等待训练完成，超时或失败则抛异常"""
        start_time = time.time()
        last_status, last_step = "", 0

        while True:
            if time.time() - start_time > self._timeout:
                raise TimeoutError(f"训练超时（{self._timeout}s）: {job_id}")

            try:
                job_data = self._api_get_job(job_id)
            except Exception as e:
                logger.warning(f"  查询作业状态失败: {e}")
                time.sleep(self._poll_interval)
                continue

            if not job_data or isinstance(job_data, list):
                time.sleep(self._poll_interval)
                continue

            status = job_data.get("status", "unknown").lower()
            step = job_data.get("step", 0)
            info = job_data.get("info", "")

            if status != last_status or step != last_step:
                logger.info(f"  训练状态: {status}, step={step}, info={info}")
                last_status, last_step = status, step
                if progress_cb:
                    try:
                        progress_cb(step, total_steps, f"训练中: {status}, step={step}/{total_steps}")
                    except Exception:
                        logger.debug(f"进度回调失败: step={step}")

            if status in ("done", "complete", "finished"):
                logger.info(f"  训练完成: {info}")
                return
            if status in ("error", "failed"):
                try:
                    log = self._api_get_job_log(job_id)
                    if log:
                        logger.error(f"  训练日志:\n{log[-2000:]}")
                except Exception as log_err:
                    logger.debug(f"获取训练日志失败: {log_err}")
                raise RuntimeError(f"训练失败: {info}")
            if status in ("stopped", "cancelled"):
                raise RuntimeError(f"训练被取消: {info}")

            time.sleep(self._poll_interval)

    def _fetch_result(self, job_id: str, job_name: str, output_name: str) -> str:
        """下载训练结果到本地，返回本地路径"""
        output_dir = self._paths.loras_dir if self._paths else Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{output_name}.safetensors")

        # 尝试从作业日志查找输出文件
        import re
        try:
            log = self._api_get_job_log(job_id)
            if log:
                # 优先匹配 output 目录下的 .safetensors（最终输出）
                output_pattern = re.compile(r"(output[/\\][\w/\\]*\.safetensors)")
                # 回退：匹配包含 lora/final/save 关键词的路径
                final_pattern = re.compile(r"([\w/\\]*(?:lora|final|save)[\w/\\]*\.safetensors)")
                # 最后兜底：任意 .safetensors（排除 checkpoint 中间产物）
                any_pattern = re.compile(r"([\w/\\]+\.safetensors)")

                for pattern in [output_pattern, final_pattern, any_pattern]:
                    for line in reversed(log.split("\n")):
                        match = pattern.search(line)
                        if match:
                            path_str = match.group(1)
                            # 路径安全：拒绝目录遍历和 checkpoint 中间产物
                            if ".." in path_str or "checkpoint" in path_str.lower():
                                continue
                            try:
                                self._download_result(path_str, output_path)
                                return output_path
                            except Exception as e:
                                logger.warning(f"  下载 {path_str} 失败: {e}")
                                continue
        except Exception as e:
            logger.debug(f"从作业日志获取输出路径失败: {e}")

        # 回退：标准输出目录
        settings = {}
        try:
            settings = self._api_get_settings()
        except Exception as e:
            logger.debug(f"获取训练设置失败，使用默认值: {e}")
        training_folder = settings.get("TRAINING_FOLDER",
                                       os.environ.get("AI_TOOLKIT_OUTPUT_DIR", "/tmp/ai_toolkit_output"))
        job_output_dir = Path(training_folder) / job_name / "output"
        for candidate in [str(job_output_dir / f"{output_name}.safetensors"),
                          str(job_output_dir / "lora.safetensors")]:
            try:
                self._download_result(candidate, output_path)
                return output_path
            except Exception:
                continue

        raise RuntimeError(
            f"训练完成但无法自动获取结果文件。\n"
            f"请手动将 .safetensors 从服务器复制到: {output_path}\n"
            f"服务端训练目录: {training_folder}/{job_name}/output/\n"
            f"文件名必须为: {output_name}.safetensors")

    def train_lora(self, params: TrainLoraParams) -> str:
        """训练角色 LoRA

        Args:
            params: TrainLoraParams 数据类

        Returns:
            本地 .safetensors 路径
        """
        char_id = params.char_id
        output_name = params.output_name or f"{char_id}_lora"
        trigger_word = params.trigger_word or f"ohwx {char_id}"

        res_val = self._parse_resolution(params.resolution)
        lr_str = str(params.learning_rate) if isinstance(params.learning_rate, float) else params.learning_rate

        logger.info(f"开始训练 LoRA: {char_id}, steps={params.steps}, rank={params.rank}, resolution={res_val}")

        # 1. 准备数据集
        dataset_name, img_paths = self._prepare_dataset(char_id, params.images_dir, trigger_word)
        logger.info(f"  图片 {len(img_paths)} 张")

        # 2. 提交训练
        job_id = self._submit_training(char_id, dataset_name, trigger_word,
                                       output_name, params.steps, lr_str, res_val,
                                       rank=params.rank, conv_rank=params.conv_rank)

        # 3. 等待完成
        self._poll_training(job_id, params.steps, params.progress_cb)

        # 4. 获取结果
        output_path = self._fetch_result(job_id, f"lora_{char_id}_{int(time.time())}", output_name)
        logger.info(f"LoRA 已保存: {output_path}")
        return output_path

    def _download_result(self, remote_path: str, local_path: str) -> str:
        """通过 files API 下载训练结果"""

        url = f"{self._api_url.rstrip('/')}/api/files/{remote_path}"
        resp = self._client.get(url, headers=self._auth_headers(),
                         timeout=300, follow_redirects=True)
        resp.raise_for_status()

        # 检查是否为有效文件（非 HTML 错误页面）
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            raise RuntimeError(f"服务端返回 HTML 而非文件: {remote_path}")

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(resp.content)

        return local_path

    # ────────────────────────────────────────────────
    # 状态查询
    # ────────────────────────────────────────────────

    def check_status(self) -> dict:
        """检查 AI Toolkit 服务状态"""
        try:
            # 尝试获取 GPU 信息来验证连接
            url = f"{self._api_url.rstrip('/')}/api/gpu"
            resp = self._client.get(url, headers=self._headers(), timeout=5)
            data = resp.json() if resp.status_code == 200 else {}

            gpus = data.get("gpus", [])
            gpu_info = ""
            if gpus:
                gpu = gpus[0]
                gpu_info = f"{gpu.get('name', '?')} ({gpu.get('memory', {}).get('total', 0)}MB)"

            return {
                "status": "connected",
                "url": self._api_url,
                "message": f"AI Toolkit 就绪 — {gpu_info}",
                "gpu": gpu_info,
            }
        except Exception as e:
            ename = type(e).__name__
            if "Connect" in ename:
                return {"status": "disconnected", "url": self._api_url, "error": "连接被拒绝"}
            if "Timeout" in ename:
                return {"status": "disconnected", "url": self._api_url, "error": "连接超时"}
            return {"status": "disconnected", "url": self._api_url, "error": str(e)}


# ── 注册 ──

registry.register(BackendMeta(
    name="ai-toolkit",
    service_type="training",
    factory=lambda cfg: AIToolkitTrainer(cfg),
    description="AI Toolkit 远程 LoRA 训练（原生 Web API，Flux 原生优化）",
    priority=10,
    tags=["lora", "training", "ai-toolkit", "flux", "ostris"],
))
