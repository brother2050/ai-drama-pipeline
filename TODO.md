# TODO — 审查遗留项

> 2026-06-07 深度审查后遗留。按优先级排列。

---

## P0 — 架构级问题

### ~~shot_task.apply_async().get() 阻塞 worker~~ ✅ 已修复
- **文件**: `pipeline/tasks/pipeline.py`
- **修复**: 改为直接调用 `_run_shot_direct()` → `_shot_task_inner()`，绕过 Celery 队列

---

## P1 — 功能性缺陷

### ~~auto-portrait 在首帧生成流程中嵌套触发~~ ✅ 已修复
- **文件**: `engines/workflow_inject.py`
- **修复**: 注入代码（IP-Adapter/PuLID）的 `_get_character_refs` 调用统一加 `_no_auto_gen=True`
- **效果**: preflight 已阻断缺少定妆照的场景，注入代码不再尝试自动生成

### ~~upload_image 每次重新读取文件~~ ✅ 已修复
- **文件**: `api/backends/image/comfyui.py`
- **修复**: 进程内缓存 `_uploaded: set[str]`，按 `filename:size` 去重
- **效果**: 同一 cover.png 被 10 个 shot 引用时只上传 1 次

### ~~_upload_reference_images 每 shot 创建 ThreadPoolExecutor~~ ✅ 已修复
- **文件**: `pipeline/tasks/steps/frame.py`
- **修复**: 提取模块级共享线程池 `_upload_pool`

### ~~TTS 后端 HTTP 响应未使用 stream 下载~~ ✅ 已修复
- **文件**: `api/backends/tts/cosyvoice.py`, `fish_speech.py`, `gpt_sovits.py`
- **修复**: 改用 `client.stream()` + `iter_bytes()` 分块读取

---

## P2 — 代码质量

### ~~30 个 `except Exception` 可精确化~~ ✅ 已修复
- `api/backends/image/comfyui.py`: `httpx.HTTPError`, `ValueError`, `(AttributeError, TypeError)`
- `post/production.py`: `RuntimeError` (FFmpeg), `(OSError, ValueError, KeyError)` (SRT)
- `flow/episode.py`: `psycopg2.Error` (DB 操作)

### ~~ProjectPaths 其他类集中化~~ ✅ 已修复
- **文件**: `engines/character_bible.py`
- **修复**: `__init__` 中一次性创建 `self._paths`，6 处重复 `ProjectPaths(project_dir)` 消除
- **`scripts/project_mgr.py`**: 独立函数，无需集中化

### ~~Container._TYPE_KEY 硬编码兜底可能与注册表漂移~~ ✅ 已修复
- **文件**: `api/registry.py`
- **修复**: 兜底逻辑改为从 `models_registry.yaml:defaults.config_paths` 读取
