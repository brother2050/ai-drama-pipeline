# 准备阶段链路审查 TODO

审查日期: 2026-06-07
审查范围: 翻译 → YAML 回写 → 定妆照生成 → reference_images 更新

## 🔴 严重

### 1. `_generate_view_prompts` 失败静默吞掉，prepare 误报成功
- **文件**: `pipeline/tasks/ai.py:594-615`（函数）、`ai.py:640`（调用方）
- **问题**: `batch_generate_appearance_prompts` 整体失败时，所有角色 `appearance_prompt_en` 保持原始翻译文本（非 AI 优化的绘图 prompt），`body_features` 为空。prepare 仍报告 `STATUS_DONE`，用户无法发现问题。
- **修复**: 检查返回值，失败时注入 `result["warnings"]`

## 🟡 中等

### 2. outfit 参考图上传失败静默忽略
- **文件**: `engines/portrait.py:272`（`_generate_single_outfit` 调用 `_inject_ref_image` 未传 `raise_on_error=True`）
- **问题**: 上传失败时 workflow 继续但缺少 IP-Adapter 参考图，服装图与角色一致性无法保证
- **修复**: `_generate_single_outfit` 中传 `raise_on_error=True`

### 3. 翻译重试绕过 AdaptiveBatchProcessor
- **文件**: `engines/prompt.py:458-478`（`_retry_missing_in_small_batches`）
- **问题**: 固定 `SMALL_BATCH=10`，直接调用 `llm.chat`，无 token 估算和自适应分批。10 项仍可能截断导致丢失。
- **修复**: 使用 `AdaptiveBatchProcessor`，或对重试结果做完整性校验（返回数 < 预期时逐条重试）

### 4. `run_portraits` 中 `write_db=True` 冗余
- **文件**: `pipeline/portraits.py:87-93`
- **问题**: `ensure_portrait` 内部已 `save_yaml`，此处重新读取再写入完全多余
- **修复**: 删除 `write_db` 参数及相关代码

### 5. 系统提示字符串重复
- **文件**: `engines/prompt.py:360` 和 `prompt.py:467`
- **问题**: `"You are a professional translator..."` 出现两次
- **修复**: 提取为模块级常量 `_FALLBACK_TRANSLATE_SYSTEM`

## 🟢 低

### 6. `CharacterBible.get_tags` 硬编码截断数
- **文件**: `engines/character_bible.py:103-109`
- **问题**: `[:2]` 和 `[:1]` 魔法数字，无配置项
- **修复**: 提取为类常量 `_MAX_EMO_TAGS = 2`、`_MAX_BODY_TAGS = 1`

### 7. `_update_view_refs` 可能误删用户自定义参考图
- **文件**: `engines/portrait.py:179-190`
- **问题**: 同 prefix + 同文件名的自定义参考图会被移除
- **修复**: 加注释说明此行为（风险低，角色资产目录通常由系统管理）

### 8. `_split_merged_items` 误拆分边界
- **文件**: `pipeline/tasks/ai.py:388-398`
- **问题**: 翻译文本含数字+句点模式时可能误拆分（有 `(?<!\w)` 保护，概率极低）
- **修复**: 无需修复，加注释即可
