"""测试 — 配置驱动的 ComfyUI 节点注入引擎

覆盖: NodeGraphInjector, inject_from_registry, 模板变量解析, 链式注入
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.workflow.node_graph import (
    NodeGraphInjector,
    inject_from_registry,
    _resolve_value,
    _resolve_string,
    _resolve_var,
    _lookup,
    _coerce,
    _find_model_pipeline,
    _find_downstream_consumer,
)
from engines.workflow.inject import _connect_to_model_pipeline
from engines.workflow.utils import (
    find_first_node,
    find_nodes_by_class,
    resolve_model_source,
)


# ── Fixtures ──

@pytest.fixture
def basic_wf():
    """最小 ComfyUI 工作流：CheckpointLoaderSimple → KSampler → VAE Decode"""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_model.safetensors"}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a cat", "clip": ["1", 1]}
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "bad", "clip": ["1", 1]}
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1}
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42, "steps": 20, "cfg": 7.5,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            }
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]}
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "output", "images": ["6", 0]}
        },
    }


@pytest.fixture
def mock_builder():
    """Mock WorkflowBuilder with minimal attributes for testing."""
    builder = MagicMock()
    builder.project_dir = "/fake/project"
    builder.no_auto_gen = True
    builder._char_name_to_id = {"Alice": "alice_hash", "Bob": "bob_hash"}
    builder.available_nodes = {
        "IPAdapterAdvanced", "IPAdapterModelLoader", "CLIPVisionLoader",
        "ApplyPulidFlux", "PulidFluxModelLoader", "PulidFluxInsightFaceLoader",
        "PulidFluxEvaClipLoader",
        "LoadFluxControlNet", "ApplyFluxControlNet",
        "KSampler", "CheckpointLoaderSimple",
    }

    def _get_character_refs(char_name, _no_auto_gen=False, ip_config=None):
        refs_map = {
            "Alice": ["/fake/project/alice/cover.png"],
            "Bob": ["/fake/project/bob/cover.png"],
        }
        return refs_map.get(char_name, [])

    builder._get_character_refs = MagicMock(side_effect=_get_character_refs)
    builder.models = {"image_backend": "sd15"}
    return builder


@pytest.fixture
def ip_adapter_graph_def():
    """IP-Adapter node graph definition (minimal for testing)."""
    return {
        "description": "IP-Plus face consistency",
        "compatible_backends": ["sd15", "sdxl", "flux"],
        "config_key": "ip_adapter",
        "required_comfyui_nodes": ["IPAdapterAdvanced"],
        "chainable": True,
        "chain": {
            "find_by_class": "IPAdapterAdvanced",
            "rewire_input": "model",
            "reuse_nodes": ["IPAdapterModelLoader", "CLIPVisionLoader"],
            "weight_decay": 0.6,
            "min_weight": 0.3,
        },
        "nodes": {
            "ipadapter_model_{suffix}": {
                "class_type": "IPAdapterModelLoader",
                "inputs": {"ipadapter_file": "{config.model|test_model.safetensors}"}
            },
            "ipadapter_clip_vision_{suffix}": {
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": "{config.clip_vision|test_clip.safetensors}"}
            },
            "ipadapter_{suffix}": {
                "class_type": "IPAdapterAdvanced",
                "inputs": {
                    "weight": "{chain_weight}",
                    "weight_type": "{config.weight_type|linear}",
                    "combine_embeds": "{config.combine_embeds|concat}",
                    "start_at": "{config.start_at|0.0}",
                    "end_at": "{config.end_at|1.0}",
                    "embeds_scaling": "{config.embeds_scaling|V only}",
                    "model": ["{model_source}", 0],
                    "ipadapter": ["ipadapter_model_{suffix}", 0],
                    "clip_vision": ["ipadapter_clip_vision_{suffix}", 0],
                    "image": "{ref_image}",
                }
            },
        },
        "output_wiring": {"target": "ksampler", "input": "model"},
    }


# ── Template Variable Resolution ──


class TestTemplateResolution:
    """模板变量解析测试"""

    def test_coerce_types(self):
        """测试类型强制转换"""
        assert _coerce("true") is True
        assert _coerce("false") is False
        assert _coerce("null") is None
        assert _coerce("none") is None
        assert _coerce("42") == 42
        assert _coerce("3.14") == 3.14
        assert _coerce("hello") == "hello"

    def test_dot_lookup(self):
        """测试点号路径查找"""
        ctx = {"config": {"model": "test.safetensors", "weight": 0.75}}
        assert _lookup("config.model", ctx) == "test.safetensors"
        assert _lookup("config.weight", ctx) == 0.75
        assert _lookup("config.nonexistent", ctx) is None
        assert _lookup("nonexistent", ctx) is None

    def test_resolve_var_with_default(self):
        """测试带默认值的变量解析"""
        ctx = {"config": {"weight": 0.8}}
        assert _resolve_var("config.weight|0.75", ctx) == 0.8
        assert _resolve_var("config.missing|0.75", ctx) == 0.75
        assert _resolve_var("config.missing|linear", ctx) == "linear"

    def test_resolve_var_without_default(self):
        """测试无默认值的变量解析"""
        ctx = {"suffix": 1001}
        assert _resolve_var("suffix", ctx) == 1001
        # Missing without default returns placeholder
        result = _resolve_var("missing_key", ctx)
        assert result == "{missing_key}"

    def test_resolve_string_full_match_returns_native(self):
        """测试整字符串匹配返回原生类型"""
        ctx = {"chain_weight": 0.75, "suffix": 1001}
        assert _resolve_string("{chain_weight}", ctx) == 0.75
        assert _resolve_string("{suffix}", ctx) == 1001

    def test_resolve_string_partial_match(self):
        """测试部分字符串插值"""
        ctx = {"suffix": 1001}
        assert _resolve_string("ipadapter_{suffix}", ctx) == "ipadapter_1001"

    def test_resolve_list_value(self):
        """测试列表值的递归解析"""
        ctx = {"model_source": "node_1"}
        result = _resolve_value(["{model_source}", 0], ctx)
        assert result == ["node_1", 0]

    def test_resolve_nested_dict(self):
        """测试嵌套字典的递归解析"""
        ctx = {"suffix": 1001}
        result = _resolve_value(
            {"type": "LoadImage", "inputs": {"image": "ref_{suffix}.png"}}, ctx
        )
        assert result == {"type": "LoadImage", "inputs": {"image": "ref_1001.png"}}


# ── Workflow Utilities ──


class TestWorkflowUtils:
    """工作流工具函数测试"""

    def test_find_first_node(self, basic_wf):
        assert find_first_node(basic_wf, "KSampler") == "5"
        assert find_first_node(basic_wf, "VAEDecode") == "6"
        assert find_first_node(basic_wf, "Nonexistent") is None

    def testfind_nodes_by_class(self, basic_wf):
        clip_nodes = find_nodes_by_class(basic_wf, "CLIPTextEncode")
        assert len(clip_nodes) == 2
        assert set(clip_nodes) == {"2", "3"}

    def test_find_model_pipeline(self, basic_wf):
        ksampler, model_source = _find_model_pipeline(basic_wf)
        assert ksampler == "5"
        assert model_source is not None

    def test_resolve_model_source(self, basic_wf):
        source = resolve_model_source(basic_wf, "5")
        assert source == "1"  # CheckpointLoaderSimple

    def test_connect_to_model_pipeline(self, basic_wf):
        _connect_to_model_pipeline(basic_wf, "5", "new_node")
        assert basic_wf["5"]["inputs"]["model"] == ["new_node", 0]

    def test_find_downstream_consumer(self, basic_wf):
        # CheckpointLoaderSimple "1" is consumed by multiple nodes.
        # Dict iteration order means first consumer "2" (CLIPTextEncode, clip input)
        # is returned — which matches the actual use case (chain injection with
        # single-consumer ApplyXXX nodes where iteration order doesn't matter).
        consumer, input_name = _find_downstream_consumer(basic_wf, "1")
        assert consumer == "2"
        assert input_name == "clip"


# ── NodeGraphInjector ──


class TestNodeGraphInjector:
    """NodeGraphInjector 核心引擎测试"""

    def test_inject_primary_creates_nodes(self, basic_wf, mock_builder,
                                          ip_adapter_graph_def):
        """主角色注入应创建完整的节点子图"""
        wf = dict(basic_wf)  # shallow copy for safety
        config = {
            "ip_adapter": {
                "model": "ip-adapter-plus-face_sd15.safetensors",
                "weight": 0.75,
                "weight_type": "linear",
                "combine_embeds": "concat",
                "embeds_scaling": "V only",
            }
        }
        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice"], mock_builder)

        # 应该有 IPAdapterModelLoader, CLIPVisionLoader, IPAdapterAdvanced 节点
        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 1

        model_nodes = find_nodes_by_class(wf, "IPAdapterModelLoader")
        assert len(model_nodes) == 1

        clip_nodes = find_nodes_by_class(wf, "CLIPVisionLoader")
        assert len(clip_nodes) == 1

        # KSampler 的 model 输入应该连接到 IPAdapterAdvanced
        ipa_id = ipa_nodes[0]
        ksampler_input = wf["5"]["inputs"]["model"]
        assert ksampler_input == [ipa_id, 0]

    def test_inject_primary_with_disabled_config(self, basic_wf, mock_builder,
                                                  ip_adapter_graph_def):
        """禁用的一致性配置应跳过注入"""
        wf = dict(basic_wf)
        config = {"ip_adapter": {"enabled": False}}
        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice"], mock_builder)

        # 不应该创建任何 IP-Adapter 节点
        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 0

    def test_inject_primary_weight_from_config(self, basic_wf, mock_builder,
                                                ip_adapter_graph_def):
        """权重应从配置中读取"""
        wf = dict(basic_wf)
        config = {"ip_adapter": {"weight": 0.9}}
        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice"], mock_builder)

        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 1
        assert wf[ipa_nodes[0]]["inputs"]["weight"] == 0.9

    def test_inject_primary_no_ref_images(self, basic_wf, mock_builder,
                                           ip_adapter_graph_def):
        """无参考图的角色应跳过注入"""
        wf = dict(basic_wf)
        config = {"ip_adapter": {"weight": 0.75}}

        # 清除 Alice 的参考图
        mock_builder._get_character_refs = MagicMock(return_value=[])

        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice"], mock_builder)

        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 0

    def test_inject_chain_secondary_character(self, basic_wf, mock_builder,
                                               ip_adapter_graph_def):
        """链式注入次要角色"""
        wf = dict(basic_wf)
        config = {"ip_adapter": {"weight": 0.75}}
        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice", "Bob"], mock_builder)

        # 应该有两个 IPAdapterAdvanced 节点（主 + 链）
        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 2

        # 共享的 loader 节点应该只有一个（被复用）
        model_nodes = find_nodes_by_class(wf, "IPAdapterModelLoader")
        assert len(model_nodes) == 1

        clip_nodes = find_nodes_by_class(wf, "CLIPVisionLoader")
        assert len(clip_nodes) == 1

        # 次要角色的权重应该被衰减
        secondary_node = ipa_nodes[1]
        assert wf[secondary_node]["inputs"]["weight"] < 0.75

    def test_inject_chain_weight_decay_minimum(self, basic_wf, mock_builder,
                                                ip_adapter_graph_def):
        """链式权重衰减不低於最小值"""
        wf = dict(basic_wf)
        config = {"ip_adapter": {"weight": 0.3}}  # 原权重已接近 min_weight (0.3)
        injector = NodeGraphInjector(ip_adapter_graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice", "Bob"], mock_builder)

        ipa_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 2
        # 0.3 * 0.6 = 0.18 < min 0.3, 应该被 clamped 到 0.3
        assert wf[ipa_nodes[1]]["inputs"]["weight"] == pytest.approx(0.3)

    def test_update_existing_nodes(self, mock_builder):
        """更新工作流中已存在的节点（模板已含 IP-Adapter）"""
        wf = {
            "10": {
                "class_type": "IPAdapterAdvanced",
                "inputs": {
                    "weight": 0.5,
                    "weight_type": "ease in",
                    "combine_embeds": "add",
                    "embeds_scaling": "V only",
                    "model": ["1", 0],
                    "ipadapter": ["11", 0],
                    "clip_vision": ["12", 0],
                    "image": ["13", 0],
                }
            },
            "11": {"class_type": "IPAdapterModelLoader",
                   "inputs": {"ipadapter_file": "old_model.safetensors"}},
            "12": {"class_type": "CLIPVisionLoader",
                   "inputs": {"clip_name": "old_clip.safetensors"}},
            "13": {"class_type": "LoadImage", "inputs": {"image": "old_ref.png"}},
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42, "steps": 20, "cfg": 7.5,
                    "sampler_name": "euler", "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["10", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                }
            },
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "sd_model.safetensors"}},
        }

        graph_def = {
            "description": "IP-Plus",
            "config_key": "ip_adapter",
            "chain": {"find_by_class": "IPAdapterAdvanced"},
            "nodes": {},  # 空模板 — 只触发 update 路径
        }
        config = {"ip_adapter": {"weight": 0.9, "weight_type": "linear"}}

        injector = NodeGraphInjector(graph_def, config["ip_adapter"])
        wf = injector.inject(wf, ["Alice"], mock_builder)

        # 权重应该被更新
        assert wf["10"]["inputs"]["weight"] == 0.9
        assert wf["10"]["inputs"]["weight_type"] == "linear"


# ── inject_from_registry 公共 API ──


class TestInjectFromRegistry:
    """inject_from_registry 公共 API 测试"""

    @patch("infra.config.registry.ModelRegistry")
    def test_uses_node_graph_from_registry(self, MockRegistry, basic_wf, mock_builder):
        """应从 registry 读取 node_graphs 并使用泛型引擎"""
        wf = dict(basic_wf)

        mock_registry = MockRegistry.return_value
        mock_registry.get_node_graph.return_value = {
            "description": "IP-Plus",
            "compatible_backends": ["sd15", "sdxl", "flux"],
            "config_key": "ip_adapter",
            "required_comfyui_nodes": ["IPAdapterAdvanced"],
            "chainable": True,
            "chain": {
                "find_by_class": "IPAdapterAdvanced",
                "rewire_input": "model",
                "reuse_nodes": ["IPAdapterModelLoader", "CLIPVisionLoader"],
                "weight_decay": 0.6,
                "min_weight": 0.3,
            },
            "nodes": {
                "ipadapter_model_{suffix}": {
                    "class_type": "IPAdapterModelLoader",
                    "inputs": {"ipadapter_file": "{config.model|test.safetensors}"}
                },
                "ipadapter_clip_vision_{suffix}": {
                    "class_type": "CLIPVisionLoader",
                    "inputs": {"clip_name": "{config.clip_vision|test.safetensors}"}
                },
                "ipadapter_{suffix}": {
                    "class_type": "IPAdapterAdvanced",
                    "inputs": {
                        "weight": "{chain_weight}",
                        "weight_type": "{config.weight_type|linear}",
                        "combine_embeds": "{config.combine_embeds|concat}",
                        "start_at": "{config.start_at|0.0}",
                        "end_at": "{config.end_at|1.0}",
                        "embeds_scaling": "{config.embeds_scaling|V only}",
                        "model": ["{model_source}", 0],
                        "ipadapter": ["ipadapter_model_{suffix}", 0],
                        "clip_vision": ["ipadapter_clip_vision_{suffix}", 0],
                        "image": "{ref_image}",
                    }
                },
            },
            "output_wiring": {"target": "ksampler", "input": "model"},
        }
        # No legacy fallback
        mock_registry.get_consistency_method.return_value = None

        config = {"ip_adapter": {"weight": 0.8}}
        result = inject_from_registry(mock_builder, wf, ["Alice"], "ip_adapter", config)

        ipa_nodes = find_nodes_by_class(result, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 1

    @patch("infra.config.registry.ModelRegistry")
    def test_inject_method_override(self, MockRegistry, basic_wf, mock_builder):
        """inject_method 覆盖时应调用 Python 函数而非泛型引擎"""
        wf = dict(basic_wf)

        mock_registry = MockRegistry.return_value
        # node_graphs defines inject_method override
        mock_registry.get_node_graph.return_value = {
            "description": "ControlNet Depth",
            "config_key": "controlnet_depth",
            "inject_method": "_inject_controlnet_depth",
        }

        config = {"controlnet_depth": {"enabled": True, "strength": 0.8}}

        # _call_inject_method strips leading _ before getattr:
        #   fn = getattr(inject_module, method_name.lstrip("_"), None)
        # So patch the actual function name (no underscore).
        with patch("engines.workflow.inject.inject_controlnet_depth",
                   return_value=wf) as mock_inject:
            result = inject_from_registry(mock_builder, wf, ["Alice"],
                                          "controlnet_depth", config)

        mock_inject.assert_called_once()
        assert result is not None

    @patch("infra.config.registry.ModelRegistry")
    def test_none_consistency_returns_wf_unchanged(self, MockRegistry, basic_wf, mock_builder):
        """consistency=none 应原样返回工作流"""
        wf = dict(basic_wf)

        mock_registry = MockRegistry.return_value
        mock_registry.get_node_graph.return_value = None
        mock_registry.get_consistency_method.return_value = None

        result = inject_from_registry(mock_builder, wf, [], "none", {})
        assert result == wf

    @patch("infra.config.registry.ModelRegistry")
    def test_flux_backend_prefers_ip_adapter_flux_config(self, MockRegistry,
                                                          basic_wf, mock_builder):
        """Flux 后端应优先使用 ip_adapter_flux 配置"""
        wf = dict(basic_wf)
        mock_builder.models = {"image_backend": "flux"}

        mock_registry = MockRegistry.return_value
        mock_registry.get_defaults.return_value = {"image_backend": "sd15"}
        mock_registry.get_node_graph.return_value = {
            "description": "IP-Plus",
            "compatible_backends": ["sd15", "sdxl", "flux"],
            "config_key": "ip_adapter",
            "required_comfyui_nodes": ["IPAdapterAdvanced"],
            "chainable": False,
            "nodes": {
                "ipadapter_model_{suffix}": {
                    "class_type": "IPAdapterModelLoader",
                    "inputs": {"ipadapter_file": "{config.model|test.safetensors}"}
                },
                "ipadapter_clip_vision_{suffix}": {
                    "class_type": "CLIPVisionLoader",
                    "inputs": {"clip_name": "{config.clip_vision|test.safetensors}"}
                },
                "ipadapter_{suffix}": {
                    "class_type": "IPAdapterAdvanced",
                    "inputs": {
                        "weight": "{chain_weight}",
                        "weight_type": "{config.weight_type|linear}",
                        "combine_embeds": "{config.combine_embeds|concat}",
                        "start_at": "{config.start_at|0.0}",
                        "end_at": "{config.end_at|1.0}",
                        "embeds_scaling": "{config.embeds_scaling|V only}",
                        "model": ["{model_source}", 0],
                        "ipadapter": ["ipadapter_model_{suffix}", 0],
                        "clip_vision": ["ipadapter_clip_vision_{suffix}", 0],
                        "image": "{ref_image}",
                    }
                },
            },
            "output_wiring": {"target": "ksampler", "input": "model"},
        }

        config = {
            "ip_adapter": {"weight": 0.75, "model": "sd15_model.safetensors"},
            "ip_adapter_flux": {"enabled": True, "weight": 0.85,
                                "model": "flux_model.safetensors"},
        }

        result = inject_from_registry(mock_builder, wf, ["Alice"], "ip_adapter", config)
        ipa_nodes = find_nodes_by_class(result, "IPAdapterAdvanced")
        assert len(ipa_nodes) == 1
        # Should use flux config weight (0.85) not ip_adapter weight (0.75)
        assert result[ipa_nodes[0]]["inputs"]["weight"] == 0.85