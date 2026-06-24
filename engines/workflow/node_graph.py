"""Config-driven ComfyUI node graph injection engine

Replaces per-method hardcoded Python with a declarative YAML DSL defined in
models_registry.yaml's node_graphs section. New methods need zero Python.

Template variable syntax:
    {config.key|default}  — config dict value with fallback
    {config.key}          — config dict value (no fallback)
    {model_source}        — current model chain head node ID
    {ref_image}           — character reference image filename
    {suffix}              — auto-incremented unique integer
    {ksampler}            — KSampler node ID
"""
from __future__ import annotations

import logging
import os
import re

from engines.workflow.inject import _create_ref_nodes, _next_suffix
from engines.workflow.utils import (
    find_first_node,
    find_nodes_by_class,
    resolve_model_source,
)

logger = logging.getLogger(__name__)

__all__ = ["NodeGraphInjector", "inject_from_registry"]


# ══════════════════════════════════════════════════════════
#  Template Variable Resolution
# ══════════════════════════════════════════════════════════

_VAR_PATTERN = re.compile(r"\{([^}]+)\}")


def _resolve_value(value, ctx: dict):
    if isinstance(value, str):
        return _resolve_string(value, ctx)
    if isinstance(value, list):
        return [_resolve_value(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_value(v, ctx) for k, v in value.items()}
    return value


def _resolve_string(s: str, ctx: dict):
    """Resolve {var} and {var|default} placeholders. Full-match returns native type."""
    m = _VAR_PATTERN.fullmatch(s)
    if m:
        return _resolve_var(m.group(1), ctx)

    def _replace(m):
        val = _resolve_var(m.group(1), ctx)
        return str(val) if val is not None else m.group(0)

    return _VAR_PATTERN.sub(_replace, s)


def _resolve_var(expr: str, ctx: dict):
    if "|" in expr:
        key, _, default = expr.partition("|")
        val = _lookup(key.strip(), ctx)
        if val is not None:
            return val
        return _coerce(default.strip())
    val = _lookup(expr.strip(), ctx)
    if val is None:
        logger.warning(f"模板变量未解析: {{{expr}}}（无默认值）")
        return f"{{{expr}}}"
    return val


def _lookup(key: str, ctx: dict):
    parts = key.split(".")
    obj = ctx
    for p in parts:
        if isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return None
    return obj


def _coerce(s: str):
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null" or s == "none":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ══════════════════════════════════════════════════════════
#  Workflow Utilities
# ══════════════════════════════════════════════════════════

def _find_model_pipeline(wf: dict) -> tuple[str | None, str | None]:
    """Find KSampler / XlabsSampler and its model source node."""
    ksampler = find_first_node(wf, "KSampler") or find_first_node(wf, "KSamplerAdvanced") or find_first_node(wf, "XlabsSampler")
    if not ksampler:
        return None, None
    return ksampler, resolve_model_source(wf, ksampler)

def _find_downstream_consumer(wf: dict, source_node: str) -> tuple[str | None, str | None]:
    """Find the node that receives source_node's output. Returns (node_id, input_name)."""
    for nid, node in wf.items():
        if nid == source_node or node.get("class_type") == "LoadImage":
            continue
        for inp_name, inp_val in node.get("inputs", {}).items():
            if isinstance(inp_val, list) and len(inp_val) == 2 and inp_val[0] == source_node:
                return nid, inp_name
    ksampler = find_first_node(wf, "KSampler") or find_first_node(wf, "KSamplerAdvanced") or find_first_node(wf, "XlabsSampler")
    return (ksampler, "model") if ksampler else (None, None)


# ══════════════════════════════════════════════════════════
#  NodeGraphInjector — the core engine
# ══════════════════════════════════════════════════════════

class NodeGraphInjector:
    """Config-driven ComfyUI node graph injector.

    Reads a node graph definition from models_registry.yaml and injects
    the corresponding ComfyUI node subgraph into a workflow dict.

    Args:
        graph_def: node graph definition from YAML (node_graphs.<name>)
        config: project config dict (for {config.xxx} resolution)
        method_config: method-specific config dict (ip_adapter, pulid_flux, etc.)
    """

    def __init__(self, graph_def: dict, method_config: dict | None = None):
        self.graph = graph_def
        self.method_config = method_config or {}

    def inject(self, wf: dict, char_names: list[str], builder) -> dict:
        """Main entry — handles primary + chain injection for all characters.

        Args:
            wf: ComfyUI workflow dict (modified in place)
            char_names: list of character names to inject
            builder: WorkflowBuilder instance (for _get_character_refs, _char_name_to_id, etc.)

        Returns:
            Modified workflow dict
        """
        if not char_names:
            return wf

        # Respect enabled flag
        if isinstance(self.method_config, dict) and self.method_config.get("enabled") is False:
            logger.info(f"{self.graph.get('description', '')} 已禁用，跳过注入")
            return wf

        # Check ComfyUI node availability
        required = self.graph.get("required_comfyui_nodes", [])
        if required and hasattr(builder, 'available_nodes'):
            available = builder.available_nodes or set()
            missing = set(required) - available
            if missing:
                logger.warning(f"缺少 ComfyUI 插件节点: {missing}，跳过 {self.graph.get('description', '')}")
                return wf

        # Collect reference images for each character
        char_refs: list[tuple[str, list[str]]] = []
        no_auto_gen = getattr(builder, 'no_auto_gen', False)

        for char_name in char_names:
            refs = builder._get_character_refs(char_name, _no_auto_gen=no_auto_gen)
            if refs:
                char_refs.append((char_name, refs))
            else:
                logger.warning(f"角色 '{char_name}' 无参考图，跳过注入")

        if not char_refs:
            return wf

        # Pre-check hook (e.g., PuLID face detection)
        pre_check = self.graph.get("pre_check")
        if pre_check == "face_detectable" and char_refs:
            from engines.workflow.inject import _check_face_detectable
            primary_refs = char_refs[0][1]
            if not _check_face_detectable(primary_refs[0]):
                logger.warning(f"参考图未检测到人脸，跳过 {self.graph.get('description', '')}")
                return wf

        # Inject primary character
        primary_name, primary_refs = char_refs[0]
        suffix = _next_suffix()
        ctx = self._build_context(primary_refs, suffix, builder, char_name=primary_name)

        # Check for existing nodes (update path)
        existing_class = self.graph.get("chain", {}).get("find_by_class", "")
        existing_nodes = find_nodes_by_class(wf, existing_class) if existing_class else []

        if existing_nodes:
            wf = self._update_existing(wf, existing_nodes, primary_refs, ctx, builder)
        else:
            wf = self._inject_subgraph(wf, primary_refs, suffix, ctx, builder)

        # Chain secondary characters
        if self.graph.get("chainable") and len(char_refs) > 1:
            for char_name, refs in char_refs[1:]:
                suffix = _next_suffix()
                chain_weight_decay = self.graph.get("chain", {}).get("weight_decay", 0.6)
                chain_min_weight = self.graph.get("chain", {}).get("min_weight", 0.3)
                ctx = self._build_context(refs, suffix, builder, weight_decay=chain_weight_decay,
                                          min_weight=chain_min_weight, char_name=char_name)
                wf = self._inject_chain(wf, refs, suffix, ctx, builder)

        return wf

    def _build_context(self, ref_images: list[str], suffix: int, builder,
                       weight_decay: float = 1.0, min_weight: float = 0.0,
                       char_name: str = "") -> dict:
        """Build template resolution context."""
        project_dir = getattr(builder, 'project_dir', '')
        name_to_id = getattr(builder, '_char_name_to_id', {})
        # char_name 可能是角色名或 hash ID；查不到映射意味着已经是 ID 本体
        char_id = name_to_id.get(char_name, char_name)

        # Calculate chain weight for secondary characters
        base_weight = self.method_config.get("weight", 0.75)
        if weight_decay < 1.0:
            chain_weight = max(min_weight, base_weight * weight_decay)
        else:
            chain_weight = base_weight

        return {
            "config": self.method_config,
            "ref_image": ref_images[0] if ref_images else "",
            "ref_images": ref_images,
            "suffix": suffix,
            "project_dir": project_dir,
            "char_id": char_id,
            "chain_weight": chain_weight,
            "base_weight": base_weight,
        }

    def _inject_subgraph(self, wf: dict, ref_images: list[str], suffix: int,
                         ctx: dict, builder) -> dict:
        """Create node subgraph from template and wire to workflow."""
        # Resolve KSampler and model source for this workflow
        ksampler, model_source = _find_model_pipeline(wf)
        if not ksampler or not model_source:
            logger.warning("未找到 KSampler 或模型来源，跳过节点注入")
            return wf

        ctx["model_source"] = model_source
        ctx["ksampler"] = ksampler

        # Create nodes from template
        nodes_template = self.graph.get("nodes", {})
        created_nodes = {}
        last_node_id = None

        for node_id_template, node_def in nodes_template.items():
            # Resolve node ID
            node_id = _resolve_string(node_id_template, ctx)

            # Resolve class_type
            class_type = _resolve_value(node_def.get("class_type", ""), ctx)

            # Resolve inputs
            inputs_raw = node_def.get("inputs", {})
            inputs = self._resolve_inputs(inputs_raw, ctx, ref_images, wf,
                                          suffix, builder, node_id)

            wf[node_id] = {"class_type": class_type, "inputs": inputs}
            created_nodes[node_id] = class_type
            last_node_id = node_id

        # Wire output to model pipeline
        wiring = self.graph.get("output_wiring", {})
        if last_node_id and wiring:
            target = wiring.get("target", "ksampler")
            input_name = wiring.get("input", "model")
            if target == "ksampler":
                wf[ksampler]["inputs"][input_name] = [last_node_id, 0]

        logger.info(f"注入节点图: {self.graph.get('description', '')} "
                    f"({len(created_nodes)} 节点, suffix={suffix})")
        return wf

    def _inject_chain(self, wf: dict, ref_images: list[str], suffix: int,
                      ctx: dict, builder) -> dict:
        """Chain secondary character after existing nodes."""
        chain_cfg = self.graph.get("chain", {})
        find_class = chain_cfg.get("find_by_class", "")
        reuse_classes = set(chain_cfg.get("reuse_nodes", []))

        if not find_class:
            logger.warning("chain.find_by_class 未定义，跳过链式注入")
            return wf

        # Find last instance of the chain target class
        existing = find_nodes_by_class(wf, find_class)
        if not existing:
            logger.warning(f"未找到 {find_class} 节点，无法链式注入")
            return wf

        last_instance = existing[-1]

        # Find its downstream consumer
        downstream_node, downstream_input = _find_downstream_consumer(wf, last_instance)
        if not downstream_node:
            logger.warning(f"链式注入失败: 未找到 {last_instance} 的下游消费者")
            return wf

        # Resolve model source from workflow
        ksampler, model_source = _find_model_pipeline(wf)
        if not ksampler or not model_source:
            logger.warning("未找到 KSampler，无法链式注入")
            return wf

        ctx["model_source"] = model_source
        ctx["ksampler"] = ksampler

        # Resolve reusable loader node IDs, keyed by class_type
        reuse_node_map: dict[str, str] = {}  # class_type → node_id
        for cls in reuse_classes:
            nodes = find_nodes_by_class(wf, cls)
            if nodes:
                reuse_node_map[cls] = nodes[0]

        # Build template-key → reused-node mapping for input reference remapping
        nodes_template = self.graph.get("nodes", {})
        template_remap: dict[str, str] = {}  # template_key → reused_node_id
        for node_id_template, node_def in nodes_template.items():
            ct = _resolve_value(node_def.get("class_type", ""), ctx)
            if ct in reuse_node_map:
                template_remap[node_id_template] = reuse_node_map[ct]

        # Create chain nodes (only non-reusable ones)
        last_chain_node = None

        for node_id_template, node_def in nodes_template.items():
            node_id = _resolve_string(node_id_template, ctx)
            class_type = _resolve_value(node_def.get("class_type", ""), ctx)

            # Skip reusable loader nodes
            if class_type in reuse_node_map:
                continue

            inputs_raw = node_def.get("inputs", {})
            inputs = self._resolve_inputs(inputs_raw, ctx, ref_images, wf,
                                          suffix, builder, node_id,
                                          chain_source=last_instance, shared_loaders=template_remap)

            wf[node_id] = {"class_type": class_type, "inputs": inputs}
            last_chain_node = node_id

        # Rewire downstream consumer
        if last_chain_node and downstream_node and downstream_input:
            wf[downstream_node]["inputs"][downstream_input] = [last_chain_node, 0]

        display = ctx.get("char_name", "")
        logger.info(f"链式注入: {display} ({find_class}, weight={ctx.get('chain_weight', '?')})")
        return wf

    def _update_existing(self, wf: dict, existing_nodes: list[str],
                         ref_images: list[str], ctx: dict, builder) -> dict:
        """Update existing nodes in-place (e.g., IP-Adapter already in template)."""
        project_dir = ctx.get("project_dir", "")
        char_id = ctx.get("char_id", "")

        # Update weight and config params on the primary node
        target_node = existing_nodes[0]
        node_def = wf.get(target_node, {})
        inputs = node_def.get("inputs", {})

        # Update weight
        weight_key = self.method_config.get("weight_key", "weight")
        if weight_key in inputs:
            inputs[weight_key] = ctx.get("base_weight", inputs[weight_key])

        # Update other config params
        for key in ("weight_type", "combine_embeds", "embeds_scaling",
                     "start_at", "end_at", "fusion"):
            if key in inputs and key in self.method_config:
                inputs[key] = self.method_config[key]

        # Update reference image on existing LoadImage nodes
        from engines.workflow.utils import find_character_load_image_nodes
        from infra.storage.asset_tracker import comfyui_asset_name

        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes and ref_images:
            char_id = ctx.get("char_id", "")
            remote_name = (comfyui_asset_name(project_dir, char_id, os.path.basename(ref_images[0]))
                           if project_dir else os.path.basename(ref_images[0]))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name

        logger.info(f"更新已有节点: {target_node} (weight={inputs.get(weight_key, '?')})")
        return wf

    def _resolve_inputs(self, inputs_raw: dict, ctx: dict, ref_images: list[str],
                        wf: dict, suffix: int, builder, node_id: str,
                        chain_source: str = "", shared_loaders: dict[str, str] | None = None) -> dict:
        """Resolve template variables in node inputs.

        Handles both primary injection and chain injection.
        chain_source: for chain mode, replaces {model_source} with the previous chain node.
        shared_loaders: for chain mode, maps template_key → reused_node_id for reuse.
        """
        resolved = {}
        remap = shared_loaders or {}
        for key, value in inputs_raw.items():
            if isinstance(value, str):
                if value == "{ref_image}":
                    project_dir = ctx.get("project_dir", "")
                    char_id = ctx.get("char_id", "")
                    prefix = f"{node_id.split('_')[0]}_ref"
                    ref_node = _create_ref_nodes(wf, ref_images, prefix, suffix, project_dir, char_id)
                    resolved[key] = [ref_node, 0]
                elif value == "{model_source}" and chain_source:
                    resolved[key] = [chain_source, 0]
                else:
                    resolved[key] = _resolve_value(value, ctx)
            elif isinstance(value, list) and len(value) == 2 and chain_source:
                ref_id = value[0] if isinstance(value[0], str) else ""
                # Chain mode: {model_source} → 上一个链式节点；template_key → 可复用加载器
                if isinstance(ref_id, str) and ref_id == "{model_source}":
                    resolved[key] = [chain_source, value[1]]
                elif isinstance(ref_id, str) and ref_id in remap:
                    resolved[key] = [remap[ref_id], value[1]]
                else:
                    resolved[key] = _resolve_value(value, ctx)
            else:
                resolved[key] = _resolve_value(value, ctx)
        return resolved

# ══════════════════════════════════════════════════════════
#  Public API — called from inject.py / builder.py
# ══════════════════════════════════════════════════════════

def inject_from_registry(builder, wf: dict, char_names: list[str],
                         consistency: str, config: dict) -> dict:
    """Inject consistency method via node_graphs YAML definition.

    Single entry point called by WorkflowBuilder._inject_consistency_method().
    All consistency methods (ip_adapter, pulid_flux, controlnet_depth) route
    through here — either via the generic NodeGraphInjector or an escape-hatch
    inject_method override for complex cases.
    """
    from infra.config.registry import ModelRegistry
    registry = ModelRegistry()

    graph_def = registry.get_node_graph(consistency)
    if not graph_def:
        if consistency == "none":
            logger.info("一致性方案: none，跳过注入")
        else:
            logger.warning(f"未注册的 node graph: {consistency}")
        return wf

    # Check ComfyUI node availability (unified for both paths)
    required = graph_def.get("required_comfyui_nodes", [])
    if required and hasattr(builder, 'available_nodes'):
        available = builder.available_nodes or set()
        missing = set(required) - available
        if missing:
            logger.warning(f"缺少 ComfyUI 插件节点: {missing}，跳过 {consistency}")
            return wf

    # Escape hatch: inject_method override for complex Python logic
    override = graph_def.get("inject_method")
    if override:
        return _call_inject_method(builder, wf, char_names, override, config, consistency)

    # Resolve method config
    config_key = graph_def.get("config_key", "")
    method_config = config.get(config_key, {}) if config_key else {}

    # Flux 后端：优先使用 ip_adapter_flux 配置
    if config_key == "ip_adapter" and method_config:
        img_backend = getattr(builder, 'models', {}).get("image_backend", "flux")
        if img_backend == "flux":
            flux_config = config.get("ip_adapter_flux", {})
            if flux_config and flux_config.get("enabled") is not False:
                method_config = flux_config
                logger.debug("Flux 后端：使用 ip_adapter_flux 配置")

    if isinstance(method_config, dict) and method_config.get("enabled") is False:
        logger.info(f"{consistency} 已禁用，跳过一致性注入")
        return wf

    # Merge defaults from node_graphs
    if isinstance(method_config, dict):
        defaults = graph_def.get("defaults", {})
        for k, v in defaults.items():
            method_config.setdefault(k, v)

    injector = NodeGraphInjector(graph_def, method_config)
    return injector.inject(wf, char_names, builder)


def _call_inject_method(builder, wf, char_names, method_name, config, consistency):
    """Call a Python inject function by name (escape hatch for complex cases)."""
    import engines.workflow.inject as inject_module
    fn = getattr(inject_module, method_name.lstrip("_"), None)
    if not fn:
        logger.warning(f"注入方法不存在: {method_name}")
        return wf

    method_config = config.get(consistency, {}) if consistency else {}
    return fn(builder, wf, char_names, method_config)
