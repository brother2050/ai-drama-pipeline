"""ComfyUI 节点类型注册表 — 消除散落的硬编码 class_type 字符串

所有 ComfyUI 节点的 class_type 字符串集中定义在此模块，
避免在业务代码中硬编码字符串，减少拼写错误和重构风险。
"""
from __future__ import annotations

# 采样器
K_SAMPLER = "KSampler"
K_SAMPLER_ADVANCED = "KSamplerAdvanced"
XLABS_SAMPLER = "XlabsSampler"
ALL_SAMPLERS = frozenset({K_SAMPLER, K_SAMPLER_ADVANCED, XLABS_SAMPLER})

# 模型加载器
UNET_LOADER = "UNETLoader"
CHECKPOINT_LOADER = "CheckpointLoaderSimple"
ALL_MODEL_LOADERS = frozenset({UNET_LOADER, CHECKPOINT_LOADER})

# CLIP 加载器
DUAL_CLIP_LOADER = "DualCLIPLoader"
CLIP_LOADER = "CLIPLoader"
ALL_CLIP_LOADERS = frozenset({DUAL_CLIP_LOADER, CLIP_LOADER})

# LoRA
LORA_LOADER = "LoraLoader"
LORA_LOADER_MODEL_ONLY = "LoraLoaderModelOnly"
ALL_LORA_LOADERS = frozenset({LORA_LOADER, LORA_LOADER_MODEL_ONLY})

# IP-Adapter
IP_ADAPTER_MODEL_LOADER = "IPAdapterModelLoader"
CLIP_VISION_LOADER = "CLIPVisionLoader"
IP_ADAPTER_ADVANCED = "IPAdapterAdvanced"

# PuLID-Flux
PULID_MODEL_LOADER = "PulidFluxModelLoader"
PULID_INSIGHTFACE_LOADER = "PulidFluxInsightFaceLoader"
PULID_EVA_CLIP_LOADER = "PulidFluxEvaClipLoader"
APPLY_PULID_FLUX = "ApplyPulidFlux"

# ControlNet
LOAD_FLUX_CONTROL_NET = "LoadFluxControlNet"
APPLY_FLUX_CONTROL_NET = "ApplyFluxControlNet"
MIDAS_DEPTH = "MiDaS-DepthMapPreprocessor"

# 通用
LOAD_IMAGE = "LoadImage"
LOAD_IMAGE_FROM_PATH = "LoadImageFromPath"
IMAGE_LOAD = "ImageLoad"
ALL_IMAGE_LOADERS = frozenset({LOAD_IMAGE, LOAD_IMAGE_FROM_PATH, IMAGE_LOAD})
CLIP_TEXT_ENCODE = "CLIPTextEncode"
EMPTY_LATENT = "EmptyLatentImage"
EMPTY_SD3_LATENT = "EmptySD3LatentImage"
IMAGE_SCALE = "ImageScale"
IMAGE_BATCH = "ImageBatch"
VAE_LOADER = "VAELoader"
VAE_DECODE = "VAEDecode"
SAVE_IMAGE = "SaveImage"
DUAL_CFG_GUIDER = "DualCFGGuider"

# Latent 节点（用于分辨率调整检测）
ALL_LATENT_NODES = frozenset({
    EMPTY_LATENT, EMPTY_SD3_LATENT, IMAGE_SCALE,
    "EmptyImage", "LatentUpscale", "LatentBatch",
})

# 采样器字段名映射（消除 if-else 分支）
SAMPLER_POSITIVE_FIELD = {
    K_SAMPLER: "positive",
    K_SAMPLER_ADVANCED: "positive",
    XLABS_SAMPLER: "conditioning",
}
SAMPLER_NEGATIVE_FIELD = {
    K_SAMPLER: "negative",
    K_SAMPLER_ADVANCED: "negative",
    XLABS_SAMPLER: "neg_conditioning",
}
SAMPLER_SEED_FIELD = {
    K_SAMPLER: "seed",
    K_SAMPLER_ADVANCED: "noise_seed",
    XLABS_SAMPLER: "noise_seed",
}

def get_positive_field(class_type: str) -> str:
    return SAMPLER_POSITIVE_FIELD.get(class_type, "positive")

def get_negative_field(class_type: str) -> str:
    return SAMPLER_NEGATIVE_FIELD.get(class_type, "negative")

def get_seed_field(class_type: str) -> str:
    return SAMPLER_SEED_FIELD.get(class_type, "seed")
