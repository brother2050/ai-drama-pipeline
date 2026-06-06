# TODO — 审查遗留项

> 2026-06-07 深度审查后遗留。按优先级排列。

---

## P0 — 架构级问题

### shot_task.apply_async().get() 阻塞 worker
- **文件**: `pipeline/tasks/pipeline.py:65-67`
- **问题**: `produce_task` 同步等待 `shot_task` 子任务，占用 worker 线程
- **建议**: 改用 Celery chord/chain，或直接在线程内执行 shot 逻辑
- **风险**: 改动涉及任务编排，需充分测试

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

---

## P2 — 代码质量

### 30 个 `except Exception` 可精确化
- **文件**: `api/backends/image/comfyui.py`, `post/vertical.py`, `flow/episode.py` 等
- **建议**: 逐个精确化为 JSONDecodeError、OSError、httpx.HTTPError 等

### ProjectPaths 其他类集中化
- **文件**: `engines/character_bible.py`(×6), `scripts/project_mgr.py`(×6)
- **建议**: 在 `__init__` 中一次性创建 `self._paths`
