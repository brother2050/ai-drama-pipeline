# TODO

> 有效问题清单。已修复/误判/设计意图的已剔除。

---

## P1 — 低优先级（边缘场景或理论隐患）

| # | 文件 | 描述 |
|---|------|------|
| 50 | `infra/watchdog.py` | 超时仅标记不中断，`except TimeoutError` 永不触发（设计如此） |
| 61 | `infra/database/schema.py` | shots 表无 `updated_at` 列，无法追踪修改时间 |
| 62 | `infra/database/pool.py` | 连接归还不检查实际可用性（DB 可能已重启） |
| 73 | `api/backends/lipsync/musetalk.py` | 文件字段名硬编码，不同部署版本可能不兼容 |
| 80 | `api/backends/seko/proposal.py` | API 错误 code=500 应重试而非终止 |
| 81 | `api/backends/training/ai_toolkit.py` | 文件句柄在异常时可能泄漏 |
| 82 | `api/backends/training/ai_toolkit.py` | 从日志提取 safetensors 路径可能匹配到中间 checkpoint |

## P2 — 优化（代码质量、可读性）

| # | 文件 | 描述 |
|---|------|------|
| 93 | `infra/json_parse.py` | `ast.literal_eval` 可能接受非 JSON 结构（Python tuple/set） |
| 94 | `infra/batch_processor.py` | `estimate_tokens` 对英文高估（len//4 是合理近似） |
| 102 | `engines/workflow_builder.py` | `_apply_gpu` 每次构建 `_sampler_types` 集合 |
| 104 | `engines/workflow_inject.py` | suffix 用 `random.randint` 理论可能碰撞 |
| 113 | `pipeline/tasks/helpers.py` | `_db_record_step` 静默吞异常，建议 `logger.warning` |
| 118 | `post/distributor.py` | ffprobe 逻辑重复实现，应抽取为共享工具 |
| 128 | `api/backends/training/ai_toolkit.py` | 状态字符串比较未 `.lower()` |
| 131 | `web/routers/deps.py` | `_safe_path` URL 解码可能破坏含 `%` 的文件名 |

---

## 已修复

| 原编号 | 文件 | 修复 commit |
|--------|------|-------------|
| P0 #2 | `pipeline/tasks/training_tasks.py` | `3529965` — `_ROOT` 改为参数传递 |
| P0 #3 | `post/vertical.py` | `3529965` — 人脸裁剪使用 cy 垂直居中 |
| P1 #33 | `pipeline/tasks/pipeline.py` | `3529965` — `.apply()` → `.apply_async()` |
| P1 #30 | `infra/models.py` | `0abd4d0` — `normalize_character` 浅拷贝 |
| P1 #27 | `engines/workflow_inject.py` | `ba01fd3` — LoRA 注入追踪 KSampler 当前 model/clip 来源 |
| P1 #34 | `pipeline/tasks/steps.py` | `ba01fd3` — ShotManager 实例缓存 |
| P1 #101 | `engines/shot_utils.py` | `ba01fd3` — 引号清理扩展中文引号 |
| P1 #84 | `web/routers/storyboard.py` | 已有 episode 校验（代码已修复） |
| P1 #14 | `engines/shot_calibrator.py` | `9f8d23f` — shot_id 匹配规范化为三位数 |
| P1 #7 | `engines/storyboard.py` | `efb7948` — 跳过无效镜头时增加 warning |
| P1 #12 | `engines/llm_generator.py` | `efb7948` — 空 dict 纳入失败计数 |
| P1 #17 | `engines/shot_utils.py` | `efb7948` — 去重与格式校验分离 |
| P1 #20 | `engines/workflow_builder.py` | `efb7948` — 工作流为空时 raise |
| P1 #22 | `engines/workflow_builder.py` | `efb7948` — 上传失败时 raise |
| P1 #24 | `engines/workflow.py` | `efb7948` — 只修改 KSampler 引用的节点 |
| P1 #32 | `pipeline/tasks/pipeline.py` | `8b65bc3` — shot_data 浅拷贝 |
| P1 #37 | `pipeline/tasks/portrait_tasks.py` | `8b65bc3` — outfits_batch 添加 project_scope |
| P1 #44 | `post/subtitle.py` | `c5bca82` — 最小推进 0.5s |
| P1 #66 | `api/__init__.py` | `c5bca82` — 注册表失败时重置 _loaded |
| P1 #74 | `api/backends/image/comfyui.py` | `c5bca82` — _extract_error 拆分 JSON 解析 |
| — | `engines/llm_generator.py` | `24793fe` — 已有实体上下文注入 |
