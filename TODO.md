# TODO — 审查遗留项

> 2026-06-07 深度审查后遗留。按优先级排列，P0 最高。

---

## P0 — 架构级问题（需设计讨论）

### ComfyUI 轮询无整体超时上限
- **文件**: `api/backends/image/comfyui.py:131-148`
- **问题**: `_poll_until_done` 最长阻塞 15 分钟（`self._timeout`），结合 Celery `soft_time_limit=1800`，单镜头可阻塞 worker 30 分钟
- **建议**: 增加连续空轮询计数器，超过 N 次无进展主动报错

### shot_task.apply_async().get() 阻塞 worker
- **文件**: `pipeline/tasks/pipeline.py:65-67`
- **问题**: `produce_task` 同步等待 `shot_task` 子任务完成，占用 worker 线程长达 30 分钟
- **建议**: 改用 Celery chord/chain 编排，或直接在线程内执行 shot 逻辑（不经 broker）

### safe_executor 超时后线程泄漏
- **文件**: `infra/safe_executor.py:123-131`
- **问题**: Python 线程无法强制终止，超时后 `cancel_event` 无法中断阻塞 I/O（如 HTTP 请求），每个超时任务泄漏一个线程
- **建议**: 对超时场景用 `httpx`（支持 cancel）或进程池（可 terminate）

### _ctx_cache 更新时旧 Container 未 shutdown
- **文件**: `pipeline/tasks/helpers.py:200-225`
- **问题**: 热重载时新 Container 替换旧实例，但旧 Container 的 `shutdown_all()` 可能未调用，连接泄漏
- **建议**: 在 `_ctx_cache` 更新时显式调用旧 `cont.shutdown_all()`

---

## P1 — 功能性缺陷

### load_character() 已存在但 12+ 处未使用
- **文件**: `engines/portrait.py`, `pipeline/tasks/portrait_tasks.py`, `pipeline/tasks/ai.py`, `web/routers/imports.py` 等
- **问题**: `infra/config.py:load_character()` 已定义，但多处仍手动 `load_yaml_full` + `.get("character", {})`
- **建议**: 迁移到 `load_character()`，统一入口

### ProjectPaths 每方法重建
- **文件**: `engines/quality_gate.py`(×9), `engines/character_bible.py`(×6), `scripts/project_mgr.py`(×6)
- **问题**: 同一类中多个方法各自 `paths = ProjectPaths(project_dir)`
- **建议**: 在 `__init__` 中一次性创建 `self._paths`

### TTS 后端 _mimo_common 写文件未用 atomic_write_bytes
- **文件**: `api/backends/tts/_mimo_common.py`
- **问题**: 已改用 `atomic_write_bytes` 但 WAV header 构建逻辑需验证
- **状态**: 已修复，待集成测试确认

### tts_core._chars 函数属性缓存非线程安全
- **文件**: `pipeline/tasks/steps/tts.py:62-66`
- **问题**: 多线程同时检测 `_chars_dir != config_dir` 并重复加载
- **建议**: 用 `threading.Lock` 保护缓存读写

### save_episode_shots 逐行 INSERT 无批量优化
- **文件**: `infra/database/storyboard_db.py:98-115`
- **问题**: N 个镜头 = N 次 SQL 执行，批量场景下性能差
- **建议**: 用 `psycopg2.extras.execute_values` 批量插入

### image_prompt_en 存入 DB 但 prompt_compiler 不使用
- **文件**: `engines/prompt_compiler.py`, `engines/workflow_builder.py`
- **问题**: `shot_calibrator` 生成的 `image_prompt_en` 被存储但从未用于图像生成
- **建议**: `_build_first_frame_prompt` 中优先使用 `image_prompt_en`（若非空），回退到 `action_en`

### HTTP 404 错误消息格式不一致
- **文件**: `web/routers/` 多个文件（16+ 处）
- **问题**: 同类 404 错误消息格式不同（有的带 ID，有的不带）
- **建议**: 提取 `raise_not_found(entity_type, entity_id)` 工具函数

### HTTP 响应写文件部分写入风险
- **文件**: TTS 后端写 output 文件后如果异常，文件损坏但不清理
- **状态**: 已用 `atomic_write_bytes` 修复

---

## P2 — 代码质量

### 30 个 `except Exception` 可精确化
- **文件**: `api/backends/image/comfyui.py`, `post/vertical.py`, `flow/episode.py` 等
- **问题**: `except Exception` 捕获了应只捕获特定异常的场景（JSONDecodeError、OSError 等）
- **建议**: 逐个精确化异常类型

### _find_shot 从 DB 加载全部镜头再遍历
- **文件**: `pipeline/tasks/helpers.py:66-75`
- **问题**: 查找单个镜头加载该集全部镜头
- **建议**: 直接 SQL `SELECT * FROM shots WHERE episode=? AND shot_id=?`

### WorkflowBuilder.load_workflows() 每次重新加载 JSON
- **文件**: `engines/workflow_builder.py:264-285`
- **问题**: 每个 shot 都重新读取相同的 JSON 模板文件
- **建议**: 缓存已加载的工作流 JSON（按文件路径 key）

### upload_image 每次重新读取文件
- **文件**: `api/backends/image/comfyui.py:98-107`
- **问题**: 同一角色 cover.png 被多个 shot 引用时重复读取+上传
- **建议**: 在 `build_upload_map` 阶段去重，或在 `AssetTracker` 层缓存

### ComfyUI check_image_exists 用长超时客户端
- **文件**: `api/backends/image/comfyui.py:55-63`
- **问题**: 轻量 HEAD 检查用 900s 超时客户端
- **建议**: 用 `self._fast_client`（短超时）

### Web 保存路径缺少 emotion/shot_type/camera 值域校验
- **文件**: `web/routers/storyboard.py`
- **问题**: 仅导入路径有 `postprocess_shots` 校验，Web 保存可存入非法值
- **建议**: 在 `save_storyboard` 中增加值域校验

### auto-portrait 在首帧生成流程中嵌套触发
- **文件**: `engines/workflow_builder.py:347-360`
- **问题**: `_get_character_refs` 中无 cover.png 时自动触发 `ensure_portrait`，导致首帧生成中嵌套 ComfyUI 任务
- **建议**: 移到 `preflight` 预检查阶段

### infra/database/__init__.py re-export 无效
- **文件**: `infra/database/__init__.py`
- **问题**: 所有调用方直接 `from infra.database._db import ...`，`__init__.py` 的 re-export 无人使用
- **建议**: 统一为 `from infra.database import ...` 或删除 re-export

### cleanup 钩子失败被吞掉
- **文件**: `infra/hooks.py:152-155`
- **问题**: `cleanup` 钩子异常不传播，GPU 显存等关键资源可能泄漏
- **建议**: 至少 `logger.error` 并记录到监控
