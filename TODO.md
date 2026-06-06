# TODO — 审查遗留项

> 2026-06-07 深度审查后遗留。按优先级排列。

---

## P0 — 架构级问题

### shot_task.apply_async().get() 阻塞 worker
- **文件**: `pipeline/tasks/pipeline.py:65-67`
- **问题**: `produce_task` 同步等待 `shot_task` 子任务，占用 worker 线程
- **建议**: 改用 Celery chord/chain，或直接在线程内执行 shot 逻辑
- **风险**: 改动涉及任务编排，需充分测试

### safe_executor 超时后线程泄漏
- **文件**: `infra/safe_executor.py:123-131`
- **问题**: Python 线程无法强制终止，超时后 cancel_event 无法中断阻塞 I/O
- **建议**: 对超时场景用进程池（可 terminate）
- **风险**: 进程池有 pickling 开销，需评估性能影响

---

## P1 — 功能性缺陷

### image_prompt_en 存入 DB 但 prompt_compiler 不使用
- **文件**: `engines/prompt_compiler.py`, `engines/workflow_builder.py`
- **问题**: shot_calibrator 生成的 image_prompt_en 被存储但从未用于图像生成
- **建议**: `_build_first_frame_prompt` 中优先使用 image_prompt_en（若非空），回退到 action_en

### auto-portrait 在首帧生成流程中嵌套触发
- **文件**: `engines/workflow_builder.py:347-360`
- **问题**: `_get_character_refs` 中无 cover.png 时自动触发 `ensure_portrait`
- **建议**: 移到 `preflight` 预检查阶段

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
