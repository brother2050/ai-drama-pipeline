# TODO

> 有效问题清单。已修复/误判/设计意图的已剔除。

---

## P1 — 低优先级（边缘场景或理论隐患）

| # | 文件 | 描述 |
|---|------|------|
| 62 | `infra/database/pool.py` | 连接归还不检查实际可用性（DB 可能已重启） |
| 73 | `api/backends/lipsync/musetalk.py` | 文件字段名硬编码，不同部署版本可能不兼容 |
| 82 | `api/backends/training/ai_toolkit.py` | 从日志提取 safetensors 路径可能匹配到中间 checkpoint |

## P2 — 优化（代码质量、可读性）

| # | 文件 | 描述 |
|---|------|------|
| 104 | `engines/workflow_inject.py` | suffix 用 `random.randint` 理论可能碰撞 |
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
| 61 | `infra/database/schema.py` | `9789cce` — shots 表添加 updated_at 列 |
| 102 | `engines/workflow_builder.py` | `7b2bee6` — sampler_types 构建提到 load_workflows |
| 113 | `pipeline/tasks/helpers.py` | `eb10f12` — _db_record_step 异常日志提升为 warning |

### 验证为非问题（审查中确认）

| 原编号 | 原因 |
|--------|------|
| P0 #1 | `results["quality_issues"]` — 误判，实际是局部变量 |
| P0 #4 | `safe_run` 超时 — 设计意图，Python 无法杀线程 |
| P0 #5 | `_last_error` 类型注解 — 合法 Python |
| P0 #6 | `translate_to_english` llm=None — 设计意图 |
| P1 #9 | offset 累积 — 已修复（batch_sizes 精确对齐） |
| P1 #23 | `resolve_node_aliases` pop — 无害，调用方传 copy |
| P1 #26 | PuLID 第一角色无 refs — 后续角色正常处理 |
| P1 #35 | storyboard 只加载一次 |
| P1 #36 | warnings 首次赋值，非覆盖 |
| P1 #45 | 调用方已传 container |
| P1 #50 | WatchDog 超时标记 — 设计如此 |
| P1 #76 | timeout key 实际一致 |
| P1 #80 | Seko 已重试 500 错误 5 次 |
| P1 #81 | 已有 finally 关闭文件句柄 |
| P2 #88 | 只有顶层一处 import yaml |
| P2 #93 | `ast.literal_eval` 实际无害 |
| P2 #94 | `estimate_tokens` 用 /4 非 //2 |
| P2 #98 | 只有顶层一处 import math |
| P2 #116 | effects.py 文件已不存在 |
| P2 #118 | 都使用 infra.ffmpeg.probe |
| P2 #128 | 已用 .lower() |
