# TODO — 全项目代码审查（2026-06-06 第二轮）

> 5 个维度并行审查：前端↔API 契约、Celery 任务流、YAML 配置、LLM 交互、文件 I/O。
> 按优先级排列。已修复的项不在此列。

---

## 🟡 中优先级

### 5. `generate_storyboard` 不校验返回镜头数
**文件**: `engines/llm_generator.py:50-54`
**问题**: prompt 指定目标总时长，但不校验返回镜头数是否合理（过少导致时长不足，过多导致超时）。

### 9. FFmpeg `input()`/`output()` 路径未转义特殊字符
**文件**: `infra/ffmpeg.py:33-46`
**问题**: 路径含 `#`、`%`、`'` 等 FFmpeg 特殊字符时行为不可预期。
**说明**: subprocess 使用列表参数（非 shell），`input()`/`output()` 路径由 OS 直接传递，不受特殊字符影响。`concat()` 和 `add_subtitle()` 已有转义。此条为误报，降级为无需修复。

---

## 🟢 低优先级

### 14. `_rename_final` 跨文件系统时回退到非原子 copy2
**文件**: `post/production.py:126-136`

### 16. `llm.model` 键名传递链路不完整
**文件**: `config/system.yaml:17`, `api/backends/llm/ollama.py:27`
**说明**: Container._backend_config 已将 llm 段 merge 到 cfg，model 键正常传递。此条为误报。

### 17. `_enrich_stage` shot_id 匹配失败静默跳过
**文件**: `engines/shot_calibrator.py:108-120`
**说明**: 已有 debug 日志，且保留原始数据不丢失。降级为低优。

### 18. `_merge_translate_results` batch_len 回退防御性不足
**文件**: `engines/prompt.py:420-424`

### 19. `add_subtitle` 路径转义映射可能不完整
**文件**: `infra/ffmpeg.py:94-105`

### 21. `yaml_delete` 使用 `shutil.rmtree(ignore_errors=True)`
**文件**: `web/routers/deps.py:219-223`

---

## ✅ 已修复（本轮审查）

| # | 文件 | 问题 | 提交 |
|---|------|------|------|
| 4 | `infra/batch_processor.py` | `estimate_tokens` 低估 CJK 标点 | `fix: CJK 标点 token 估算` |
| 6 | `infra/config.py` | `.active` 文件路径遍历 | `fix: .active 路径校验` |
| 7 | `engines/portrait.py` | `os.replace` 跨文件系统 | `fix: 跨文件系统 rename` |
| 8 | `web/routers/assets.py` | 上传文件非原子写入 | `fix: 原子上传写入` |
| 10 | `config/system.yaml` | cosyvoice/fish_speech 配置缺失 | `fix: 补充后端配置` |
| 11 | `config/default_storyboard.py` | outfits 缺 default key | `fix: outfits default key` |
| 12 | `web/routers/imports.py` | presets 只传 key 不传描述 | `fix: presets 传递描述` |
| 13 | `web/routers/assets.py` | get_entity_asset 缺 _safe_path | `fix: 资产路径安全校验` |
| 15 | `config/models_registry.yaml` | config_paths 缺 seko/training | `fix: 补充 config_paths` |
| 20 | `post/vertical.py` | 导入 _FFMPEG 内部变量 | `fix: 使用公开 API` |

---

## ⏳ 待补充

- audit2-frontend-api（前端 JS ↔ 后端 API 契约）— 进行中
- audit2-celery（Celery 任务流）— 进行中
