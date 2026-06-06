# ComfyUI 工作流 & AI 管线逻辑审查 TODO

审查日期: 2026-06-06
审查范围: workflow_builder, workflow_inject, prompt_compiler, consistency_checker, quality_gate, portrait (五视图)

---

## ✅ 已修复

- **H1** prompt_compiler 模板变量残留检测 → `prompt_compiler.py` 已添加 regex 检测 + warning
- **M1** workflow_inject downstream_node=None 静默跳过 → 已添加 `logger.warning`
- **M2** inject_lora clip 全局搜索 → 沿 model_source 回溯 CheckpointLoader/LoraLoader 的 clip 输出
- **M3** workflow_builder secondary_pool 越界 → `build_upload_map` 已添加 `i < len(secondary_pool)` 保护
- **M4** workflow_builder img2img plain_load 为空 → 已创建新 LoadImage 节点
- **M5** consistency_checker 情绪校验 → 已添加 VALID_EMOTIONS 校验
- **M6** consistency_checker outfit 存在性 → 已新增 `_check_outfit_exists` 方法
- **M7** quality_gate 翻译完整性 → 已添加 `is_ascii_only` 验证
- **M8** quality_gate prompt 阈值 → 已从 20 提高到 50，空 prompt 报 warning
- **M9** quality_gate 异常吞掉 → 已改为 `logger.warning` + 记录为 warning issue
- **L1** workflow_builder `_apply_gpu` 未覆盖 latent 节点 → 已添加 warning 日志
- **L2** workflow_builder `build_video` 空工作流 → 已添加 warning 日志
- **L5** prompt_compiler 硬编码回退 → 已添加 warning（不再静默）
- **L8** quality_gate 空台词过滤 → 补全空格/破折号/波浪号
- **L11** outfit seed 依赖字典顺序 → 已改用 `outfit_key` 替代 `outfit_index`
- **L12** 五视图 fake_shot 缺少 scene_id → 已补充

## 🟡 部分修复

- **M10** 五视图侧面无参考图 → 已添加 warning 日志，但未实现 IP-Adapter 参考方案

## ⏳ 待修复

### 🟢 低优先级

- **L3** workflow_inject — weight=0 时仍注入完整节点子图
- **L4** workflow_inject — `_build_ip_adapter_nodes` 不校验 model_source
- **L6** consistency_checker — characters=[] 与 None 行为相同
- **L7** consistency_checker — 缺少 action_en/dialogue_en 翻译完整性检查
- **L9** quality_gate — 缺少 lipsync 质量检查
- **L10** 五视图 — 正面失败阻塞后续视图参考图
