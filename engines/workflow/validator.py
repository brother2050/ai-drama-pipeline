"""ComfyUI 工作流验证层 — 组装完成后校验图完整性

ValidationError: 验证错误数据类（level + node_id + message + field）
WorkflowValidator: 工作流验证器，检查悬空引用、必填输入、类型兼容性、采样器存在性
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.workflow.graph import NodeRef, WorkflowGraph
from engines.workflow.node_types import (
    ALL_LORA_LOADERS,
    ALL_MODEL_LOADERS,
    ALL_SAMPLERS,
    APPLY_FLUX_CONTROL_NET,
    APPLY_PULID_FLUX,
    IP_ADAPTER_ADVANCED,
    K_SAMPLER,
    LORA_LOADER,
)

__all__ = ["ValidationError", "WorkflowValidator", "parse_ref"]

# 输出 MODEL 的节点类型（output 0 为 MODEL）
MODEL_OUTPUT_NODES = ALL_MODEL_LOADERS | ALL_LORA_LOADERS | frozenset(
    {IP_ADAPTER_ADVANCED, APPLY_PULID_FLUX, APPLY_FLUX_CONTROL_NET}
)

# 关键节点类型的必填输入
REQUIRED_INPUTS: dict[str, list[str]] = {
    K_SAMPLER: ["model", "positive", "negative", "latent_image"],
    LORA_LOADER: ["lora_name", "strength_model", "model", "clip"],
    IP_ADAPTER_ADVANCED: ["model", "ipadapter", "clip_vision", "image"],
    APPLY_PULID_FLUX: ["model", "pulid_flux", "face_analysis", "eva_clip", "image"],
}


def parse_ref(val: Any) -> NodeRef | None:
    """解析 [node_id, output_index] 格式的引用，非引用值返回 None

    Args:
        val: 待解析的值，可能为标量或 [node_id, output_index] 引用列表

    Returns:
        解析成功返回 NodeRef，否则返回 None
    """
    if not isinstance(val, list) or len(val) != 2:
        return None
    node_id, output_index = val
    if not isinstance(node_id, str) or not isinstance(output_index, int) or isinstance(output_index, bool):
        return None
    return NodeRef(node_id=node_id, output_index=output_index)


@dataclass
class ValidationError:
    """验证错误 — 描述工作流中的一个校验问题

    Attributes:
        level: 错误级别（"error" 或 "warning"）
        node_id: 相关节点 ID
        message: 错误描述
        field: 相关输入字段名（可选，默认空字符串）
    """

    level: str
    node_id: str
    message: str
    field: str = ""

    def __str__(self) -> str:
        prefix = f"[{self.level.upper()}]"
        location = f" {self.node_id}" if self.node_id else ""
        if self.field:
            location += f".{self.field}"
        return f"{prefix}{location}: {self.message}"


class WorkflowValidator:
    """工作流验证器 — 组装完成后校验图完整性

    检查项:
    1. 悬空引用：所有节点引用是否指向存在的节点
    2. 必填输入：关键节点类型的必填输入是否齐全
    3. 类型兼容性：MODEL 输出是否只连到 model 输入（简化版，warning 级别）
    4. 采样器存在性：工作流至少包含一个采样器
    """

    def validate(self, graph: WorkflowGraph) -> list[ValidationError]:
        """执行全部校验，返回错误列表

        Args:
            graph: 待校验的工作流图

        Returns:
            ValidationError 列表（包含 error 和 warning 级别）
        """
        errors: list[ValidationError] = []
        errors.extend(self._check_dangling_refs(graph))
        errors.extend(self._check_required_inputs(graph))
        errors.extend(self._check_type_compatibility(graph))
        errors.extend(self._check_sampler_exists(graph))
        return errors

    def _check_dangling_refs(self, graph: WorkflowGraph) -> list[ValidationError]:
        """检查所有节点引用是否指向存在的节点

        遍历图中每个节点的输入，对 [node_id, output_index] 格式的引用
        检查目标节点是否存在于图中。不存在则为悬空引用（error 级别）。
        """
        errors: list[ValidationError] = []
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                ref = parse_ref(val)
                if ref is not None and graph.resolve_ref(ref) is None:
                    errors.append(ValidationError(
                        level="error",
                        node_id=node.node_id,
                        field=key,
                        message=f"悬空引用: 指向不存在的节点 '{ref.node_id}'",
                    ))
        return errors

    def _check_required_inputs(self, graph: WorkflowGraph) -> list[ValidationError]:
        """检查关键节点类型的必填输入

        根据 REQUIRED_INPUTS 映射检查 KSampler、LoraLoader、IPAdapterAdvanced、
        ApplyPulidFlux 等关键节点的必填输入字段是否齐全。
        """
        errors: list[ValidationError] = []
        for node in graph.nodes.values():
            required = REQUIRED_INPUTS.get(node.class_type)
            if not required:
                continue
            for field_name in required:
                if field_name not in node.inputs:
                    errors.append(ValidationError(
                        level="error",
                        node_id=node.node_id,
                        field=field_name,
                        message=f"缺少必填输入: {field_name}",
                    ))
        return errors

    def _check_type_compatibility(self, graph: WorkflowGraph) -> list[ValidationError]:
        """检查 MODEL 输出是否只连到 model 输入（简化版，返回 warning 级别）

        遍历所有引用，若目标节点输出 MODEL（class_type 在 MODEL_OUTPUT_NODES 中
        且 output_index 为 0），但引用方的输入名不是 "model"，则发出 warning。
        """
        errors: list[ValidationError] = []
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                ref = parse_ref(val)
                if ref is None:
                    continue
                target = graph.resolve_ref(ref)
                if target is None:
                    continue
                if target.class_type in MODEL_OUTPUT_NODES and ref.output_index == 0 and key != "model":
                    errors.append(ValidationError(
                        level="warning",
                        node_id=node.node_id,
                        field=key,
                        message=f"MODEL 输出可能误连到 '{key}' 输入（期望 'model'）",
                    ))
        return errors

    def _check_sampler_exists(self, graph: WorkflowGraph) -> list[ValidationError]:
        """确保工作流至少包含一个采样器

        检查图中是否存在 KSampler、KSamplerAdvanced 或 XlabsSampler 节点。
        不存在则返回 error 级别的验证错误。
        """
        for node in graph.nodes.values():
            if node.class_type in ALL_SAMPLERS:
                return []
        return [ValidationError(
            level="error",
            node_id="",
            message="工作流不包含任何采样器节点（KSampler/KSamplerAdvanced/XlabsSampler）",
        )]
