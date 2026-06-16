# Technical Debt & Potential Issues

> 2026-06-16 全量检查记录

---

## 已修复

### ✅ `ComfyUI` 缺少 `get_available_node_types()` — 导致人脸一致性方案 100% 跳过

- **文件**: `api/backends/image/comfyui.py`
- **根因**: `builder.py:101` 通过 `hasattr` 检查 `get_available_node_types`，但 `ComfyUI` 类未定义该方法 → `available_nodes` 恒为空集 → 所有 consistency 方案检测节点失败 → 静默跳过
- **影响**: PuLID-Flux 人脸一致性、IP-Adapter、ControlNet Depth 等全部静默 fallback
- **修复**: 添加了 `get_available_node_types()` 方法，调用 ComfyUI `/object_info` 端点

### ✅ `inject_controlnet_depth` 硬编码重复检查 + `AIToolkitTrainer` 缺少 health_check/shutdown

- **文件**:
  - `engines/workflow/node_graph.py` — 将 `required_comfyui_nodes` 检查统一提升到 `inject_from_registry()` 入口
  - `engines/workflow/inject.py` — 删除硬编码的 `{"FluxControlNetLoader", "ApplyFluxControlNet"}`
  - `api/backends/training/ai_toolkit.py` — 新增 `health_check()` 和 `shutdown()` 方法
- **修复**:
  1. 节点可用性检查从两处（YAML + Python 硬编码）统一为 YAML 驱动，`inject_method` 覆盖和泛型两条路径共用同一检查
  2. `AIToolkitTrainer` 现在可参与 Container 健康检查 fallback

---

## 中优先级

_（已全部修复）_

---

## 低优先级

_（已全部修复）_

---

## 已验证安全的检查点

以下 `hasattr`/`getattr` 动态调用链均已验证目标方法存在，无问题：

| 位置 | 动态调用 | 目标 |
|------|---------|------|
| `registry.py:188/205` | `hasattr(inst, "health_check")` | 全部后端 ✅ |
| `registry.py:311/332` | `hasattr(inst, "shutdown")` | 全部后端 ✅ |
| `json_parse.py:37` | `hasattr(llm, "context_length")` | OllamaLLM / OpenAICompatLLM ✅ |
| `node_graph.py:186` | `hasattr(builder, 'available_nodes')` | builder.available_nodes ✅ |
| `node_graph.py:195-197` | `getattr(builder, ...)` | _char_name_to_id / project_dir / no_auto_gen ✅ |
| `node_graph.py:545` | `getattr(inject_module, ...)` | inject_controlnet_depth → inject.py:696 ✅ |
