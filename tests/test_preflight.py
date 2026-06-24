"""工作流预检系统测试

测试 WorkflowPreflightChecker 的 10 项预检规则，
以及 ComfyUISchemaCache 的 schema 解析和缓存功能。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.workflow.preflight import WorkflowPreflightChecker, PreflightResult
from engines.workflow.schema_cache import ComfyUISchemaCache, NodeSchema, InputDef


# ── 测试用工作流 ──────────────────────────────────────

VALID_WORKFLOW = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive prompt", "clip": ["2", 0]}},
    "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
    "4": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 576, "batch_size": 1}},
    "5": {"class_type": "XlabsSampler", "inputs": {
        "noise_seed": 42, "sampler_mode": "fixed", "steps": 28, "guidance": 3.5,
        "denoise": 1.0, "true_gs": 3.5, "timestep_to_start_cfg": 0.0,
        "denoise_strength": 1.0, "image_to_image_strength": 1.0,
        "model": ["1", 0], "conditioning": ["3", 0], "neg_conditioning": ["9", 0], "latent_image": ["4", 0],
    }},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.sft"}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["8", 0]}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "first_frame"}},
}

DANGLING_REF_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal",
        "denoise": 1.0,
        "model": ["99", 0],  # 悬空引用: 节点 99 不存在
        "positive": ["3", 0],
        "negative": ["9", 0],
        "latent_image": ["4", 0],
    }},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos", "clip": ["2", 0]}},
    "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}

MISSING_INPUT_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 20,
        # 缺少 model, positive, negative, latent_image
    }},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}

NO_SAMPLER_WORKFLOW = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "hello"}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}

CIRCULAR_DEP_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal",
        "denoise": 1.0,
        "model": ["2b", 0],  # KSampler.model → LoraLoader (创建循环)
        "positive": ["3", 0],
        "negative": ["9", 0],
        "latent_image": ["4", 0],
    }},
    "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors", "weight_dtype": "default"}},
    # LoraLoader.model → KSampler (反向引用, 形成循环: 1→2b→1)
    "2b": {"class_type": "LoraLoader", "inputs": {
        "lora_name": "test.safetensors", "strength_model": 0.7, "strength_clip": 0.7,
        "model": ["1", 0],
        "clip": ["2", 0],
    }},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos", "clip": ["2", 0]}},
    "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}

OUT_OF_RANGE_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 999, "cfg": 500.0,  # steps 和 cfg 超出范围
        "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
        "model": ["2", 0], "positive": ["3", 0], "negative": ["9", 0], "latent_image": ["4", 0],
    }},
    "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors", "weight_dtype": "default"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos", "clip": ["2", 0]}},
    "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}

UNREACHABLE_NODE_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal",
        "denoise": 1.0,
        "model": ["2", 0], "positive": ["3", 0], "negative": ["9", 0], "latent_image": ["4", 0],
    }},
    "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors", "weight_dtype": "default"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos", "clip": ["2", 0]}},
    "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    # 孤立节点: 不被任何节点引用，也不连接到输出
    "99": {"class_type": "CLIPTextEncode", "inputs": {"text": "orphan", "clip": ["2", 0]}},
}


# ── 预检器测试 ──────────────────────────────────────

class TestWorkflowPreflightChecker:
    """测试 WorkflowPreflightChecker 的各项预检规则"""

    def setup_method(self):
        self.checker = WorkflowPreflightChecker(schema_cache=None)

    def test_valid_workflow_passes(self):
        """有效工作流应全部通过"""
        result = self.checker.check(VALID_WORKFLOW)
        assert result.passed, f"有效工作流应通过, 但有: {result.issues}"
        assert result.checks_run == 10

    def test_dangling_ref_detected(self):
        """悬空引用应被检测到"""
        result = self.checker.check(DANGLING_REF_WORKFLOW)
        errors = [e for e in result.issues if e.level == "error"]
        assert any("悬空引用" in e.message for e in errors), "应检测到悬空引用"
        assert any("99" in e.message for e in errors), "应指出引用了不存在的节点 99"

    def test_missing_required_input_detected(self):
        """必填输入缺失应被检测到"""
        result = self.checker.check(MISSING_INPUT_WORKFLOW)
        errors = [e for e in result.issues if e.level == "error"]
        assert any("model" in e.field for e in errors), "应检测到缺少 model 输入"
        assert any("positive" in e.field for e in errors), "应检测到缺少 positive 输入"
        assert any("negative" in e.field for e in errors), "应检测到缺少 negative 输入"
        assert any("latent_image" in e.field for e in errors), "应检测到缺少 latent_image 输入"

    def test_no_sampler_detected(self):
        """缺少采样器应被检测到"""
        result = self.checker.check(NO_SAMPLER_WORKFLOW)
        errors = [e for e in result.issues if e.level == "error"]
        assert any("采样器" in e.message for e in errors), "应检测到缺少采样器"

    def test_circular_dependency_detected(self):
        """循环依赖应被检测到"""
        result = self.checker.check(CIRCULAR_DEP_WORKFLOW)
        errors = [e for e in result.issues if e.level == "error"]
        assert any("循环依赖" in e.message for e in errors), "应检测到循环依赖"

    def test_numeric_range_warning(self):
        """数值超出范围应产生 warning"""
        result = self.checker.check(OUT_OF_RANGE_WORKFLOW)
        warnings = [e for e in result.issues if e.level == "warning"]
        assert any("steps" in e.field for e in warnings), "应警告 steps 超出范围"
        assert any("cfg" in e.field for e in warnings), "应警告 cfg 超出范围"

    def test_unreachable_node_warning(self):
        """不可达节点应产生 warning"""
        result = self.checker.check(UNREACHABLE_NODE_WORKFLOW)
        warnings = [e for e in result.issues if e.level == "warning"]
        assert any("不可达" in e.message for e in warnings), "应检测到不可达节点"
        assert any("99" in e.node_id for e in warnings), "应指出节点 99 不可达"

    def test_strict_mode_fails_on_warning(self):
        """严格模式下 warning 也算失败"""
        strict_checker = WorkflowPreflightChecker(schema_cache=None, strict=True)
        result = strict_checker.check(OUT_OF_RANGE_WORKFLOW)
        assert not result.passed, "严格模式下有 warning 应失败"

    def test_empty_workflow(self):
        """空工作流应报采样器缺失"""
        result = self.checker.check({})
        assert not result.passed
        errors = result.errors
        assert any("采样器" in e.message for e in errors)

    def test_result_summary(self):
        """结果摘要应包含关键信息"""
        result = self.checker.check(DANGLING_REF_WORKFLOW)
        summary = result.summary()
        assert "FAIL" in summary
        assert "error" in summary


# ── Schema 缓存测试 ──────────────────────────────────────

class TestComfyUISchemaCache:
    """测试 ComfyUISchemaCache 的 schema 解析和缓存功能"""

    # 模拟 /object_info 响应
    MOCK_OBJECT_INFO = {
        "KSampler": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "positive": ["CONDITIONING"],
                    "negative": ["CONDITIONING"],
                    "latent_image": ["LATENT"],
                    "seed": ["INT", {"default": 0, "min": 0, "max": 18446744073709551615}],
                    "steps": ["INT", {"default": 20, "min": 1, "max": 200}],
                    "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0}],
                    "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m"]],
                    "scheduler": [["normal", "karras", "exponential"]],
                    "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0}],
                }
            },
            "output": ["LATENT"],
            "output_name": ["LATENT"],
            "category": "sampling",
        },
        "LoraLoader": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "clip": ["CLIP"],
                    "lora_name": [["test_lora.safetensors", "style_lora.safetensors"]],
                    "strength_model": ["FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0}],
                    "strength_clip": ["FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0}],
                }
            },
            "output": ["MODEL", "CLIP"],
            "output_name": ["MODEL", "CLIP"],
            "category": "loaders",
        },
        "SaveImage": {
            "input": {
                "required": {
                    "images": ["IMAGE"],
                    "filename_prefix": ["STRING", {"default": "ComfyUI"}],
                }
            },
            "output": [],
            "output_name": [],
            "category": "image",
        },
    }

    def test_parse_object_info(self):
        """解析 /object_info 响应"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        assert cache.has_node_type("KSampler")
        assert cache.has_node_type("LoraLoader")
        assert cache.has_node_type("SaveImage")

    def test_get_node_schema(self):
        """获取单个节点 schema"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        schema = cache.get_node_schema("KSampler")
        assert schema is not None
        assert schema.class_type == "KSampler"
        assert schema.category == "sampling"
        assert len(schema.inputs) == 10  # 10 个必填输入

    def test_required_inputs(self):
        """获取必填输入"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        schema = cache.get_node_schema("KSampler")
        required = schema.get_required_inputs()
        required_names = [inp.name for inp in required]
        assert "model" in required_names
        assert "positive" in required_names
        assert "steps" in required_names

    def test_input_valid_values(self):
        """输入合法值列表（下拉框）"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        schema = cache.get_node_schema("KSampler")
        sampler_input = schema.get_input("sampler_name")
        assert sampler_input is not None
        assert sampler_input.valid_values == ["euler", "euler_ancestral", "dpmpp_2m"]

    def test_input_numeric_range(self):
        """数值型输入的范围"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        schema = cache.get_node_schema("KSampler")
        steps_input = schema.get_input("steps")
        assert steps_input is not None
        assert steps_input.min_val == 1.0
        assert steps_input.max_val == 200.0

    def test_output_count(self):
        """输出数量"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        ksampler_schema = cache.get_node_schema("KSampler")
        lora_schema = cache.get_node_schema("LoraLoader")
        assert ksampler_schema.get_output_count() == 1
        assert lora_schema.get_output_count() == 2  # MODEL + CLIP

    def test_get_lora_files(self):
        """获取 LoRA 文件列表"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        lora_files = cache.get_lora_files()
        assert "test_lora.safetensors" in lora_files
        assert "style_lora.safetensors" in lora_files

    def test_file_cache_save_load(self, tmp_path):
        """文件缓存保存和加载"""
        cache_file = tmp_path / "schema_cache.json"
        cache = ComfyUISchemaCache(comfyui_url="", cache_file=cache_file)
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        cache._loaded = True
        cache._save_to_file()
        assert cache_file.exists()

        # 新实例从文件加载
        cache2 = ComfyUISchemaCache(comfyui_url="", cache_file=cache_file)
        assert cache2._load_from_file()
        assert cache2.has_node_type("KSampler")
        assert cache2.has_node_type("LoraLoader")

    def test_preflight_with_schema(self):
        """使用 schema 做深度预检"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        cache._loaded = True

        checker = WorkflowPreflightChecker(schema_cache=cache)

        # 工作流引用了不存在的 LoRA 文件
        workflow = {
            "1": {"class_type": "LoraLoader", "inputs": {
                "lora_name": "nonexistent.safetensors",
                "strength_model": 0.7, "strength_clip": 0.7,
                "model": ["2", 0], "clip": ["3", 0],
            }},
            "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors", "weight_dtype": "default"}},
            "3": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "a.safetensors", "clip_name2": "b.safetensors", "type": "flux"}},
        }
        result = checker.check(workflow)
        errors = result.errors
        # 应检测到 LoRA 文件不存在（因为 schema 中只有 test_lora 和 style_lora）
        # 注意: LoraLoader 不在 _FALLBACK_REQUIRED 中，但 schema 检查会覆盖
        assert any("nonexistent" in e.message or "不存在" in e.message for e in errors), \
            f"应检测到 LoRA 文件不存在, errors: {errors}"

    def test_preflight_unknown_node_type_with_schema(self):
        """使用 schema 检测未知节点类型"""
        cache = ComfyUISchemaCache(comfyui_url="")
        cache._parse_object_info(self.MOCK_OBJECT_INFO)
        cache._loaded = True

        checker = WorkflowPreflightChecker(schema_cache=cache)
        workflow = {
            "1": {"class_type": "NonExistentNode", "inputs": {}},
        }
        result = checker.check(workflow)
        errors = result.errors
        assert any("未知节点类型" in e.message for e in errors), \
            f"应检测到未知节点类型, errors: {errors}"
