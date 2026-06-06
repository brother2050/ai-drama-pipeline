# TODO — 审查遗留项

> 2026-06-07 深度审查后遗留。按优先级排列。

---

## P0 — 架构级问题

### ~~shot_task.apply_async().get() 阻塞 worker~~ ✅ 已修复
- **文件**: `pipeline/tasks/pipeline.py`
- **修复**: 改为直接调用 `_run_shot_direct()` → `_shot_task_inner()`，绕过 Celery 队列
- **效果**: 消除 worker 线程阻塞死锁风险，serial/concurrent/retry 三条路径统一

---

## P1 — 功能性缺陷

### auto-portrait 在首帧生成流程中嵌套触发
- **文件**: `engines/workflow_builder.py:732-770`
- **问题**: `_get_character_refs` 中无 cover.png 时自动触发 `ensure_portrait`
- **建议**: 默认禁用 auto-gen（preflight 已检查），仅在显式请求时启用
- **现状**: preflight 已阻断缺少定妆照的场景，auto-gen 是安全网

### upload_image 每次重新读取文件
- **文件**: `api/backends/image/comfyui.py:98-107`
- **问题**: 同一角色 cover.png 被多 shot 引用时重复读取+上传
- **建议**: 在 AssetTracker 层缓存已上传文件

### ~~_upload_reference_images 每 shot 创建 ThreadPoolExecutor~~ ✅ 已修复
- **文件**: `pipeline/tasks/steps/frame.py`
- **修复**: 提取模块级共享线程池 `_upload_pool`，所有 shot 复用

### ~~TTS 后端 HTTP 响应未使用 stream 下载~~ ✅ 已修复
- **文件**: `api/backends/tts/cosyvoice.py`, `fish_speech.py`, `gpt_sovits.py`
- **修复**: 改用 `client.stream()` + `iter_bytes()` 分块读取

---

## P2 — 代码质量

### ~~30 个 `except Exception` 可精确化~~ ✅ 部分修复
- **已修复文件**:
  - `api/backends/image/comfyui.py`: `httpx.HTTPError`, `ValueError`, `(ValueError, KeyError)`, `(AttributeError, TypeError)`
  - `post/production.py`: `RuntimeError` (FFmpeg), `(OSError, ValueError, KeyError)` (SRT)
  - `flow/episode.py`: `psycopg2.Error` (DB 操作)
- **剩余**: 其他模块中的 `except Exception` 多为日志记录或降级场景，风险较低

### ProjectPaths 其他类集中化
- **文件**: `engines/character_bible.py`(×6), `scripts/project_mgr.py`(×6)
- **建议**: 在 `__init__` 中一次性创建 `self._paths`

### ~~Container._TYPE_KEY 硬编码兜底可能与注册表漂移~~ ✅ 已修复
- **文件**: `api/registry.py`
- **修复**: 兜底逻辑改为从 `models_registry.yaml:defaults.config_paths` 读取（单一数据源），消除硬编码
