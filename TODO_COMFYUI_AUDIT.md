# ComfyUI 工作流 & AI 管线逻辑审查 TODO

审查日期: 2026-06-06
审查范围: workflow_builder, workflow_inject, prompt_compiler, consistency_checker, quality_gate, portrait (五视图)

---

## 🔴 高优先级

### H1. prompt_compiler — 模板变量残留未检测
- **文件:** `engines/prompt_compiler.py:110` (`compile_text`)
- **问题:** 变量替换后不检查结果中是否残留 `${var}` / `{{var}}`。模板 typo 会导致字面量被发送到 ComfyUI。
- **修复:** 返回前添加 regex 检测，发现残留时 `logger.warning`。

## 🟡 中优先级

### M1. workflow_inject — 链式注入 downstream_node=None 时静默跳过
- **文件:** `engines/workflow_inject.py:145-148` (`inject_ip_adapter_chain`), `:224-227` (`inject_pulid_flux_chain`)
- **问题:** `_find_downstream_consumer` 返回 `(None, None)` 时直接 return，无日志。第二角色一致性注入被静默跳过。
- **修复:** 添加 `logger.warning`。

### M2. workflow_inject — inject_lora clip 回退可能指向错误节点
- **文件:** `engines/workflow_inject.py:272-280`
- **问题:** `find_first_node("CLIPLoader")` 全局搜索，Flux 双加载器场景可能匹配到错误的 CLIP。
- **修复:** 追踪 KSampler 的 clip 输入链（类似 `resolve_model_source`），而非全局搜索。

### M3. workflow_builder — `build_upload_map` 未检查 secondary_pool 长度
- **文件:** `engines/workflow_builder.py:308-312`
- **问题:** 3+ 角色但模板只为 2 个角色准备节点时，`secondary_pool[i]` 越界。
- **修复:** 添加 `if i < len(secondary_pool)` 保护。

### M4. workflow_builder — `_setup_img2img` plain_load 为空时错误复用一致性节点
- **文件:** `engines/workflow_builder.py:175-180`
- **问题:** 所有 LoadImage 都是 ipadapter/pulid 前缀时，plain_load 为空，回退到一致性节点。
- **修复:** plain_load 为空时创建新 LoadImage 节点。

### M5. consistency_checker — 情绪校验无防御性检查
- **文件:** `engines/consistency_checker.py:106-125` (`_check_emotion_transition`)
- **问题:** 直接读取 emotion 字段，不校验是否在 VALID_EMOTIONS 中。独立调用时无效情绪不会被捕获。
- **修复:** 添加 VALID_EMOTIONS 校验。

### M6. consistency_checker — 缺少 outfit 存在性校验
- **文件:** `engines/consistency_checker.py`
- **问题:** 不检查 shot.outfit 是否在角色 outfits 字典中存在。引用不存在的 outfit 会静默回退。
- **修复:** 新增 `_check_outfit_exists` 方法。

### M7. quality_gate — 翻译完整性不验证语言
- **文件:** `engines/quality_gate.py:81-95` (`_check_translation_complete`)
- **问题:** 只检查 `appearance_prompt_en` 是否 truthy，不验证是否为英文。LLM 翻译失败返回中文仍通过。
- **修复:** 添加 `is_ascii_only` 验证。

### M8. quality_gate — prompt 有效性阈值过低
- **文件:** `engines/quality_gate.py:100-113` (`_check_prompt_valid`)
- **问题:** `len < 20` 阈值过低；空 prompt 不报错。
- **修复:** 提高到 50 字符，空 prompt 报 warning。

### M9. quality_gate — 异常被 debug 级吞掉
- **文件:** `engines/quality_gate.py:65-67`
- **问题:** `except Exception: logger.debug(...)` 将 checker 异常降级为 debug，检查被静默跳过。
- **修复:** 改为 `logger.warning`，并记录为 warning 级 issue。

### M10. 五视图 — 侧面视图无参考图，一致性风险
- **文件:** `engines/portrait.py:102-107` (`_generate_five_views`)
- **问题:** left_side/right_side 不用 cover.png 参考，面部特征可能与正面差异大。
- **修复:** 考虑低权重 IP-Adapter 参考或改进 prompt 策略。

## 🟢 低优先级

### L1. workflow_builder — `_apply_gpu` 未覆盖的 latent 节点无日志
- **文件:** `engines/workflow_builder.py:111-128`

### L2. workflow_builder — `build_video` 返回空 dict 无 error 日志
- **文件:** `engines/workflow_builder.py:228`

### L3. workflow_inject — weight=0 时仍注入完整节点子图
- **文件:** `engines/workflow_inject.py:52-67`, `:163`

### L4. workflow_inject — `_build_ip_adapter_nodes` 不校验 model_source
- **文件:** `engines/workflow_inject.py:113-128`

### L5. prompt_compiler — 模板缺失时静默回退到硬编码
- **文件:** `engines/prompt_compiler.py:103-106`

### L6. consistency_checker — characters=[] 与 None 行为相同
- **文件:** `engines/consistency_checker.py:47`

### L7. consistency_checker — 缺少 action_en/dialogue_en 翻译完整性检查
- **文件:** `engines/consistency_checker.py`

### L8. quality_gate — `_check_all_audio` 空台词过滤不完整
- **文件:** `engines/quality_gate.py:151-162`
- **问题:** `"..."` (英文句号) 不在过滤集合中。

### L9. quality_gate — 缺少 lipsync 质量检查
- **文件:** `engines/quality_gate.py`

### L10. 五视图 — 正面失败阻塞后续视图参考图
- **文件:** `engines/portrait.py:95-115`

### L11. 五视图 — outfit seed 依赖字典遍历顺序
- **文件:** `engines/portrait.py:198-217`
- **修复:** `_outfit_seed` 中用 `outfit_key` 替代 `outfit_index`。

### L12. 五视图 — fake_shot 缺少 scene_id
- **文件:** `engines/portrait.py:62-64`

---

## 执行计划

- [ ] **Batch 1:** H1 + M1 + M5 + M9 — 日志/检测类，低风险
- [ ] **Batch 2:** M3 + M4 + M2 — workflow_builder/inject 逻辑修复
- [ ] **Batch 3:** M6 + M7 + M8 — consistency_checker + quality_gate 增强
- [ ] **Batch 4:** M10 + L10 + L11 + L12 — 五视图改进
- [ ] **Batch 5:** L1-L9 — 低优先级收尾
