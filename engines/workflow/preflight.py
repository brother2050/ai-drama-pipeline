"""ComfyUI 工作流预检器 — 在提交给 ComfyUI 之前全面检查工作流

WorkflowPreflightChecker: 预检器主类，执行 10 项检查规则。
PreflightResult: 预检结果，包含通过/失败状态和详细问题列表。

10 项预检规则:
  1. 节点类型有效性 — 检查所有 class_type 是否在 ComfyUI 服务器上注册
  2. 悬空引用 — 检查所有节点引用是否指向存在的节点
  3. 必填输入缺失 — 检查关键节点的必填输入是否齐全
  4. 输出索引越界 — 检查引用的 output_index 是否超出目标节点的输出数量
  5. 模型文件存在性 — 检查 LoRA/Checkpoint/VAE 等文件名是否在服务器上可用
  6. 参数值范围 — 检查数值型参数（steps/cfg/seed/denoise）是否在合法范围
  7. 采样器存在性 — 确保工作流至少包含一个采样器节点
  8. 循环依赖检测 — 检查工作流图是否存在循环引用
  9. 不可达节点检测 — 检查是否存在无法到达任何输出节点的孤立节点
  10. 类型兼容性 — 检查 MODEL 输出是否只连到 model 输入

用法:
    checker = WorkflowPreflightChecker(schema_cache)
    result = checker.check(workflow_dict)
    if not result.passed:
        for issue in result.issues:
            print(issue)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from engines.workflow.graph import WorkflowGraph
from engines.workflow.node_types import (
    ALL_SAMPLERS,
    IP_ADAPTER_ADVANCED,
    APPLY_PULID_FLUX,
    APPLY_FLUX_CONTROL_NET,
    K_SAMPLER,
    K_SAMPLER_ADVANCED,
    LORA_LOADER,
    LORA_LOADER_MODEL_ONLY,
    ALL_MODEL_LOADERS,
    ALL_LORA_LOADERS,
    SAVE_IMAGE,
    VAE_DECODE,
)
from engines.workflow.schema_cache import ComfyUISchemaCache
from engines.workflow.validator import ValidationError, parse_ref

logger = logging.getLogger(__name__)

__all__ = ["WorkflowPreflightChecker", "PreflightResult"]


@dataclass
class PreflightResult:
    """预检结果

    Attributes:
        passed: 是否全部通过（无 error 级别问题）
        issues: 所有问题列表（包含 error 和 warning）
        checks_run: 执行的检查项数量
        checks_passed: 通过的检查项数量
    """

    passed: bool = True
    issues: list[ValidationError] = field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0

    @property
    def errors(self) -> list[ValidationError]:
        """仅 error 级别问题"""
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationError]:
        """仅 warning 级别问题"""
        return [i for i in self.issues if i.level == "warning"]

    def add_error(self, node_id: str, message: str, field: str = "") -> None:
        self.issues.append(ValidationError(level="error", node_id=node_id, message=message, field=field))
        self.passed = False

    def add_warning(self, node_id: str, message: str, field: str = "") -> None:
        self.issues.append(ValidationError(level="warning", node_id=node_id, message=message, field=field))

    def summary(self) -> str:
        """生成可读的预检摘要"""
        lines = [
            f"预检结果: {'PASS' if self.passed else 'FAIL'}",
            f"检查项: {self.checks_run} 项, 通过 {self.checks_passed} 项",
            f"问题: {len(self.errors)} error, {len(self.warnings)} warning",
        ]
        if self.issues:
            lines.append("---")
            for issue in self.issues:
                lines.append(str(issue))
        return "\n".join(lines)


# 模型文件输入字段名映射
MODEL_FILE_FIELDS: dict[str, str] = {
    LORA_LOADER: "lora_name",
    LORA_LOADER_MODEL_ONLY: "lora_name",
    "UNETLoader": "unet_name",
    "CheckpointLoaderSimple": "ckpt_name",
    "VAELoader": "vae_name",
    "DualCLIPLoader": "clip_name1",  # 还有 clip_name2
    "CLIPLoader": "clip_name",
    "CLIPVisionLoader": "clip_name",
    "IPAdapterModelLoader": "ipadapter_file",
    "PulidFluxModelLoader": "pulid_file",
    "PulidFluxEvaClipLoader": "eva_clip_name",
    "LoadFluxControlNet": "controlnet_name",
}

# 数值型参数的合法范围
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "steps": (1, 200),
    "guidance": (0.0, 100.0),
    "cfg": (0.0, 100.0),
    "denoise": (0.0, 1.0),
    "denoise_strength": (0.0, 1.0),
    "weight": (0.0, 5.0),
    "strength_model": (0.0, 5.0),
    "strength_clip": (0.0, 5.0),
    "noise_seed": (0, 2**63 - 1),
    "seed": (0, 2**63 - 1),
}

# 输出节点类型（工作流的最终输出）
OUTPUT_NODE_TYPES = frozenset({SAVE_IMAGE, "SaveImageWebsocket", "SaveAnimatedPNG", "SaveVideo", "VHS_VideoCombine"})

# MODEL 输出节点类型
MODEL_OUTPUT_NODES = ALL_MODEL_LOADERS | ALL_LORA_LOADERS | frozenset(
    {IP_ADAPTER_ADVANCED, APPLY_PULID_FLUX, APPLY_FLUX_CONTROL_NET}
)


class WorkflowPreflightChecker:
    """工作流预检器 — 在提交给 ComfyUI 之前全面检查工作流

    依赖 ComfyUISchemaCache 提供节点 schema 信息。
    当 schema_cache 不可用（ComfyUI 离线）时，降级为仅做结构检查。

    Attributes:
        schema_cache: ComfyUI 节点 schema 缓存（None 时仅做结构检查）
        strict: 是否严格模式（严格模式下 warning 也算失败）
    """

    def __init__(self, schema_cache: ComfyUISchemaCache | None = None, strict: bool = False) -> None:
        self._schema = schema_cache
        self._strict = strict

    def check(self, workflow: dict) -> PreflightResult:
        """执行全部预检

        Args:
            workflow: ComfyUI 工作流 JSON（dict 格式）

        Returns:
            PreflightResult 包含通过/失败状态和详细问题列表
        """
        result = PreflightResult()
        graph = WorkflowGraph.from_dict(workflow)

        checks = [
            ("node_types", lambda: self._check_node_types(graph, result)),
            ("dangling_refs", lambda: self._check_dangling_refs(graph, result)),
            ("required_inputs", lambda: self._check_required_inputs(graph, result)),
            ("output_index", lambda: self._check_output_index(graph, result)),
            ("model_files", lambda: self._check_model_files(graph, result)),
            ("numeric_ranges", lambda: self._check_numeric_ranges(graph, result)),
            ("sampler_exists", lambda: self._check_sampler_exists(graph, result)),
            ("circular_deps", lambda: self._check_circular_deps(graph, result)),
            ("unreachable_nodes", lambda: self._check_unreachable_nodes(graph, result)),
            ("type_compatibility", lambda: self._check_type_compatibility(graph, result)),
        ]

        for name, check_fn in checks:
            result.checks_run += 1
            issues_before = len(result.issues)
            check_fn()
            issues_after = len(result.issues)
            # 如果该检查项没有新增 error，则算通过
            new_errors = any(
                i.level == "error" for i in result.issues[issues_before:issues_after]
            )
            if not new_errors:
                result.checks_passed += 1

        if self._strict and result.warnings:
            result.passed = False

        return result

    def _check_node_types(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """1. 节点类型有效性 — 检查所有 class_type 是否在 ComfyUI 服务器上注册"""
        if not self._schema or not self._schema._loaded:
            return  # schema 不可用时跳过
        for node in graph.nodes.values():
            if not self._schema.has_node_type(node.class_type):
                result.add_error(
                    node.node_id,
                    f"未知节点类型: '{node.class_type}' 不在 ComfyUI 服务器已注册的节点列表中",
                )

    def _check_dangling_refs(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """2. 悬空引用 — 检查所有节点引用是否指向存在的节点"""
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                ref = parse_ref(val)
                if ref is not None and graph.resolve_ref(ref) is None:
                    result.add_error(
                        node.node_id,
                        f"悬空引用: 指向不存在的节点 '{ref.node_id}'",
                        key,
                    )

    def _check_required_inputs(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """3. 必填输入缺失 — 检查节点的必填输入是否齐全"""
        for node in graph.nodes.values():
            # 优先使用 schema 检查
            if self._schema and self._schema._loaded:
                schema = self._schema.get_node_schema(node.class_type)
                if schema:
                    for inp in schema.get_required_inputs():
                        if inp.name not in node.inputs:
                            result.add_error(
                                node.node_id,
                                f"缺少必填输入: {inp.name} (类型: {inp.type})",
                                inp.name,
                            )
                    continue
            # 降级: 使用硬编码的必填输入表
            required = _FALLBACK_REQUIRED.get(node.class_type)
            if required:
                for field_name in required:
                    if field_name not in node.inputs:
                        result.add_error(
                            node.node_id,
                            f"缺少必填输入: {field_name}",
                            field_name,
                        )

    def _check_output_index(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """4. 输出索引越界 — 检查引用的 output_index 是否超出目标节点的输出数量"""
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                ref = parse_ref(val)
                if ref is None:
                    continue
                target = graph.resolve_ref(ref)
                if target is None:
                    continue  # 悬空引用已在规则 2 报告
                # 使用 schema 获取输出数量
                if self._schema and self._schema._loaded:
                    schema = self._schema.get_node_schema(target.class_type)
                    if schema:
                        output_count = schema.get_output_count()
                        if output_count > 0 and ref.output_index >= output_count:
                            result.add_error(
                                node.node_id,
                                f"输出索引越界: '{target.node_id}' 只有 {output_count} 个输出, "
                                f"但引用了 output[{ref.output_index}]",
                                key,
                            )
                        continue
                # 降级: 大多数节点只有 1 个输出，output_index > 0 可能有问题
                if ref.output_index > 0:
                    # 常见多输出节点
                    multi_output_types = {"CLIPTextEncode", "CheckpointLoaderSimple", "LoadImage"}
                    if target.class_type not in multi_output_types:
                        result.add_warning(
                            node.node_id,
                            f"引用 output[{ref.output_index}] 可能越界: "
                            f"'{target.node_id}'({target.class_type}) 通常只有 1 个输出",
                            key,
                        )

    def _check_model_files(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """5. 模型文件存在性 — 检查 LoRA/Checkpoint/VAE 等文件名是否在服务器上可用"""
        if not self._schema or not self._schema._loaded:
            return  # schema 不可用时跳过

        for node in graph.nodes.values():
            # 检查主模型文件字段
            field_name = MODEL_FILE_FIELDS.get(node.class_type)
            if field_name:
                self._validate_model_file(node, field_name, result)

            # DualCLIPLoader 有两个 clip 文件
            if node.class_type == "DualCLIPLoader":
                self._validate_model_file(node, "clip_name2", result)

            # IP-Adapter 模型文件
            if node.class_type == "IPAdapterModelLoader":
                self._validate_model_file(node, "ipadapter_file", result)

    def _validate_model_file(self, node: Any, field_name: str, result: PreflightResult) -> None:
        """验证单个模型文件字段"""
        file_val = node.inputs.get(field_name)
        if not file_val or not isinstance(file_val, str):
            return
        # 获取该字段的所有合法值
        schema = self._schema.get_node_schema(node.class_type) if self._schema else None
        if not schema:
            return
        inp_def = schema.get_input(field_name)
        if not inp_def or not inp_def.valid_values:
            return  # 无合法值列表时跳过
        if file_val not in inp_def.valid_values:
            result.add_error(
                node.node_id,
                f"模型文件不存在: '{file_val}' 不在 ComfyUI 服务器的可用文件列表中"
                f"（共 {len(inp_def.valid_values)} 个文件可用）",
                field_name,
            )

    def _check_numeric_ranges(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """6. 参数值范围 — 检查数值型参数是否在合法范围"""
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    continue
                range_spec = NUMERIC_RANGES.get(key)
                if not range_spec:
                    continue
                min_val, max_val = range_spec
                if val < min_val or val > max_val:
                    result.add_warning(
                        node.node_id,
                        f"参数值超出常规范围: {key}={val} (建议范围: {min_val}-{max_val})",
                        key,
                    )

    def _check_sampler_exists(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """7. 采样器存在性 — 确保工作流至少包含一个采样器节点"""
        has_sampler = any(
            node.class_type in ALL_SAMPLERS for node in graph.nodes.values()
        )
        if not has_sampler:
            result.add_error(
                "",
                "工作流不包含任何采样器节点 (KSampler/KSamplerAdvanced/XlabsSampler)",
            )

    def _check_circular_deps(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """8. 循环依赖检测 — 检查工作流图是否存在循环引用"""
        # 构建邻接表
        adj: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
        for node in graph.nodes.values():
            for val in node.inputs.values():
                ref = parse_ref(val)
                if ref and ref.node_id in graph.nodes:
                    adj[node.node_id].append(ref.node_id)

        # DFS 检测环
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in graph.nodes}
        cycle_path: list[str] = []

        def dfs(node_id: str, path: list[str]) -> bool:
            color[node_id] = GRAY
            path.append(node_id)
            for neighbor in adj.get(node_id, []):
                if color.get(neighbor) == GRAY:
                    # 找到环
                    cycle_start = path.index(neighbor)
                    cycle_path.extend(path[cycle_start:] + [neighbor])
                    return True
                if color.get(neighbor) == WHITE and dfs(neighbor, path):
                    return True
            path.pop()
            color[node_id] = BLACK
            return False

        for nid in graph.nodes:
            if color[nid] == WHITE:
                if dfs(nid, []):
                    cycle_str = " -> ".join(cycle_path)
                    result.add_error("", f"检测到循环依赖: {cycle_str}")
                    return

    def _check_unreachable_nodes(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """9. 不可达节点检测 — 检查是否存在无法到达任何输出节点的孤立节点"""
        if len(graph.nodes) <= 1:
            return

        # 找到所有输出节点
        output_nodes = [
            node for node in graph.nodes.values()
            if node.class_type in OUTPUT_NODE_TYPES
        ]
        if not output_nodes:
            return  # 无输出节点时跳过（其他检查会报告）

        # 反向 BFS: 从输出节点出发，标记所有可达节点
        # 先构建反向邻接表（从被引用节点 → 引用节点）
        reverse_adj: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
        for node in graph.nodes.values():
            for val in node.inputs.values():
                ref = parse_ref(val)
                if ref and ref.node_id in graph.nodes:
                    reverse_adj[ref.node_id].add(node.node_id)

        reachable: set[str] = set()
        queue = [n.node_id for n in output_nodes]
        while queue:
            nid = queue.pop(0)
            if nid in reachable:
                continue
            reachable.add(nid)
            for parent in reverse_adj.get(nid, set()):
                if parent not in reachable:
                    queue.append(parent)

        # 检查不可达节点
        for node in graph.nodes.values():
            if node.node_id not in reachable:
                result.add_warning(
                    node.node_id,
                    f"不可达节点: '{node.class_type}' 无法到达任何输出节点 (SaveImage 等)",
                )

    def _check_type_compatibility(self, graph: WorkflowGraph, result: PreflightResult) -> None:
        """10. 类型兼容性 — 检查 MODEL 输出是否只连到 model 输入"""
        for node in graph.nodes.values():
            for key, val in node.inputs.items():
                ref = parse_ref(val)
                if ref is None:
                    continue
                target = graph.resolve_ref(ref)
                if target is None:
                    continue
                # 使用 schema 检查输出类型
                if self._schema and self._schema._loaded:
                    target_schema = self._schema.get_node_schema(target.class_type)
                    if target_schema and ref.output_index < len(target_schema.output_types):
                        output_type = target_schema.output_types[ref.output_index]
                        # MODEL 输出只能连到 model 输入
                        if output_type == "MODEL" and key != "model":
                            result.add_warning(
                                node.node_id,
                                f"类型不匹配: {target.class_type} 的 MODEL 输出"
                                f"连到了 '{key}' 输入 (期望 'model')",
                                key,
                            )
                        # IMAGE 输出只能连到 image/images 输入
                        elif output_type == "IMAGE" and key not in ("image", "images", "image_output"):
                            result.add_warning(
                                node.node_id,
                                f"类型不匹配: {target.class_type} 的 IMAGE 输出"
                                f"连到了 '{key}' 输入",
                                key,
                            )
                        continue
                # 降级: 使用硬编码的 MODEL_OUTPUT_NODES
                if target.class_type in MODEL_OUTPUT_NODES and ref.output_index == 0 and key != "model":
                    result.add_warning(
                        node.node_id,
                        f"MODEL 输出可能误连到 '{key}' 输入 (期望 'model')",
                        key,
                    )


# 降级用的必填输入表（当 schema 不可用时使用）
_FALLBACK_REQUIRED: dict[str, list[str]] = {
    K_SAMPLER: ["model", "positive", "negative", "latent_image"],
    K_SAMPLER_ADVANCED: ["model", "positive", "negative", "latent_image"],
    "XlabsSampler": ["model", "conditioning", "neg_conditioning", "latent_image"],
    LORA_LOADER: ["lora_name", "strength_model", "model", "clip"],
    LORA_LOADER_MODEL_ONLY: ["lora_name", "strength_model", "model"],
    IP_ADAPTER_ADVANCED: ["model", "ipadapter", "clip_vision", "image"],
    APPLY_PULID_FLUX: ["model", "pulid_flux", "face_analysis", "eva_clip", "image"],
    "ApplyFluxControlNet": ["model", "controlnet", "image"],
}
