# TODO — 全项目代码审查（2026-06-06 第二轮）

> 5 个维度并行审查：前端↔API 契约、Celery 任务流、YAML 配置、LLM 交互、文件 I/O。
> 按优先级排列。已修复的项不在此列。

---

## 🔴 高优先级

### 1. `_deserialize_numbered` 正则不匹配常用分隔符
**文件**: `pipeline/tasks/ai.py:298`
**问题**: 正则 `r"^\d+\s*[.)]\s*(.+)"` 只匹配 `.` 和 `)`，遗漏 `:：\-）`。同项目的 `_parse_numbered_lines`（`engines/prompt.py:389`）已覆盖全部 6 种分隔符。导致 bible_dict/bible_list 翻译回写丢失结果。
**修复**: 对齐 `_parse_numbered_lines` 的正则。

### 2. `style_desc` / `genre_desc` 模板变量永远为空
**文件**: `web/routers/imports.py:279-289`
**问题**: `_load_prompt_presets()` 初始化 `style_desc`/`genre_desc` 为空字符串，但从未从 `system.yaml` 的 `presets.styles`/`presets.genres` 加载描述。LLM 分镜生成时无法获得风格/题材的详细描述。
**修复**: 从 `presets.styles[style]` 和 `presets.genres[genre]` 读取描述。

### 3. `_serialize_dict_values` + `_deserialize_numbered` 对齐错位
**文件**: `pipeline/tasks/ai.py:289+292`
**问题**: `_serialize_dict_values` 跳过空值（`if v`），生成连续编号。但 `_deserialize_numbered` 用完整 `orig_keys` 列表（含空值 key）配对，导致值映射错位。
**修复**: 序列化时不跳过空值（用占位符），或反序列化时只用非空 key。

---

## 🟡 中优先级

### 4. `estimate_tokens` 低估 CJK 标点
**文件**: `infra/batch_processor.py:23-26`
**问题**: CJK 范围 `U+4E00-U+9FFF` 不含 CJK 标点（`，。、！？：；（）【】《》`），这些被按 0.25 token/字符估算，实际应 ~1 token/字符。中文文本 token 估算偏低 20-30%。

### 5. `generate_storyboard` 不校验返回镜头数
**文件**: `engines/llm_generator.py:50-54`
**问题**: prompt 指定目标总时长，但不校验返回镜头数是否合理（过少导致时长不足，过多导致超时）。

### 6. `.active` 文件内容未校验路径遍历
**文件**: `infra/config.py:321-327, 340-347`
**问题**: `resolve_project_config` 和 `get_active_project_dir` 中，`.active` 文件内容直接用于 `Path()` 拼接，无 `_safe_path` 校验。

### 7. `os.replace` 跨文件系统失败无回退
**文件**: `engines/portrait.py:100-103, 278-281`
**问题**: ComfyUI 输出到 tmpfs 时，`os.replace` 跨文件系统抛 `OSError`，仅捕获 `FileNotFoundError`。

### 8. 上传文件写入非原子
**文件**: `web/routers/assets.py:71`
**问题**: `open(dest, "wb").write(content)` 直接写入，无 tempfile + rename。并发上传或崩溃时可能损坏文件。

### 9. FFmpeg `input()`/`output()` 路径未转义特殊字符
**文件**: `infra/ffmpeg.py:33-46`
**问题**: 路径含 `#`、`%`、`'` 等 FFmpeg 特殊字符时行为不可预期。

### 10. `cosyvoice`/`fish_speech` 健康检查配置缺失
**文件**: `config/system.yaml`（缺失），`config/models_registry.yaml:71, 81`
**问题**: 注册表引用 `models.cosyvoice.api_url` 和 `models.fish_speech.api_url`，但 system.yaml 无此键。健康检查误报。

### 11. default_storyboard `outfits` 缺 `default` key
**文件**: `config/default_storyboard.py`
**问题**: 角色 outfits 用 `casual`/`home`，无 `default`。但 prompt_templates 要求至少有 `default`。

### 12. `_load_prompt_presets` shot_types/cameras/emotions 只传 key 不传描述
**文件**: `web/routers/imports.py:287-289`
**问题**: 只传 key 名（如"特写"），不传描述（如"面部/物体细节"），LLM 不理解可选值含义。

### 13. `get_entity_asset` 未使用 `_safe_path`
**文件**: `web/routers/assets.py:97-107`
**问题**: 仅靠 `_check_filename` 正则防护，缺少 resolve + `is_relative_to` 双重校验。

---

## 🟢 低优先级

### 14. `_rename_final` 跨文件系统时回退到非原子 copy2
**文件**: `post/production.py:126-136`

### 15. `models_registry.yaml` `config_paths` 缺 seko/training 映射
**文件**: `config/models_registry.yaml:16-22`

### 16. `llm.model` 键名传递链路不完整
**文件**: `config/system.yaml:17`, `api/backends/llm/ollama.py:27`

### 17. `_enrich_stage` shot_id 匹配失败静默跳过
**文件**: `engines/shot_calibrator.py:108-120`

### 18. `_merge_translate_results` batch_len 回退防御性不足
**文件**: `engines/prompt.py:420-424`

### 19. `add_subtitle` 路径转义映射可能不完整
**文件**: `infra/ffmpeg.py:94-105`

### 20. `post/vertical.py` 直接导入 `_FFMPEG` 内部变量
**文件**: `post/vertical.py:83`

### 21. `yaml_delete` 使用 `shutil.rmtree(ignore_errors=True)`
**文件**: `web/routers/deps.py:219-223`

---

## ✅ 已修复（本轮审查）

| # | 文件 | 问题 | 提交 |
|---|------|------|------|
| — | *见上一轮 TODO* | *上一轮已修复 58 项* | *见上一轮* |

---

## ⏳ 待补充

- audit2-frontend-api（前端 JS ↔ 后端 API 契约）— 进行中
- audit2-celery（Celery 任务流）— 进行中
