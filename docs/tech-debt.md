# Technical Debt & Potential Issues

> 2026-06-16 全量检查记录

---

## 已修复

### ✅ `ComfyUI` 缺少 `get_available_node_types()` — 导致人脸一致性方案 100% 跳过

- **文件**: `api/backends/image/comfyui.py`
- **根因**: `builder.py:101` 通过 `hasattr` 检查 `get_available_node_types`，但 `ComfyUI` 类未定义该方法 → `available_nodes` 恒为空集 → 所有 consistency 方案检测节点失败 → 静默跳过
- **影响**: PuLID-Flux 人脸一致性、IP-Adapter、ControlNet Depth 等全部静默 fallback
- **修复**: 添加了 `get_available_node_types()` 方法，调用 ComfyUI `/object_info` 端点

---

## 中优先级

### 🔶 1. `inject_controlnet_depth` 硬编码重复检查

- **文件**: 
  - `engines/workflow/inject.py` 第 720 行
  - `config/models_registry.yaml` 中 `controlnet_depth.required_comfyui_nodes`
- **问题**: Python 函数硬编码了 `{"FluxControlNetLoader", "ApplyFluxControlNet"}`，与 YAML 的 `required_comfyui_nodes` 重复。如果插件节点名变更，需同时修改两处，容易遗漏导致行为不一致。
- **建议**: 让 Python 函数从 registry 读取 `required_comfyui_nodes`，而非硬编码。

### 🔶 2. `AIToolkitTrainer` 缺少 `health_check()` / `shutdown()`

- **文件**: `api/backends/training/ai_toolkit.py`
- **问题**: 该类有 `check_status()` 但没有标准的 `health_check()` 签名。`Container.get_with_fallback()` 和 `Container.shutdown_all()` 通过 `hasattr` 安全跳过，但 training 后端无法参与健康检查 fallback 逻辑。
- **建议**: 添加标准 `health_check() -> tuple[bool, str]` 和 `shutdown()` 方法。

---

## 低优先级

### 🔹 3. `builder.py` 中 `upload_image()` 无 `hasattr` 保护

- **文件**: `engines/workflow/builder.py` 第 338 行
- **问题**: `self.comfyui.upload_image(...)` 只做了 `None` 检查，没有 `hasattr` 保护。当前 `cfg.comfyui` 始终是 `ComfyUI` 实例所以安全，但如果未来传入其他后端类型会直接抛 `AttributeError`。
- **建议**: 添加 `hasattr(self.comfyui, 'upload_image')` 保护。

### 🔹 4. `_ComfyUIVideoBase` 未代理 `get_available_node_types()`

- **文件**: `api/backends/video/animatediff.py`
- **问题**: 视频后端内部持有 `ComfyUI` 实例，但未暴露 `get_available_node_types()`。当前不影响功能（builder 用 image 后端查询），但属于隐式耦合。如果未来视频工作流也需要节点可用性检查，会失败。
- **建议**: 在 `_ComfyUIVideoBase` 中添加代理方法，透传到内部 `ComfyUI` 实例。

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
