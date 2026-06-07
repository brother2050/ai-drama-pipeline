# TODO

> 2026-06-07 全项目深度审查遗留项（3 子代理 + 人工审查，约 20,000 行代码）
> 已修复的项见 git log。以下为未修复项，按严重程度分类。

---

## HIGH — 建议后续修复

| 文件 | 行号 | 问题 |
|---|---|---|
| `infra/batch_processor.py` | 157 | ~~`_execute_with_retry` 返回的 `attempt` 是 0-indexed~~ ✅ 已修复 |
| `engines/prompt.py` | 236 | ~~`batch_generate_appearance_prompts` 返回类型注解 `dict[str, dict]`，但 `parse_result` 返回 `list | None`，元素类型不确定时 `item.get("prompt_en")` 可能 `AttributeError`~~ ✅ 已修复 |
| `engines/prompt.py` | 330 | ~~`_merge_translate_results` 重试中 `parsed.get(local_idx + 1, "")` 如果 LLM 返回编号不连续或跳号，结果丢失~~ ✅ 已修复 |
| `pipeline/tasks/steps/frame.py` | 53 | ~~`_has_consistency_nodes` 硬编码~~ ✅ 已修复 |
| `pipeline/tasks/steps/frame.py` | 70 | `_upload_one` 在线程池中并发修改共享 `wf` dict（不同 node_id），CPython GIL 下安全但 PEP 703 去 GIL 后会成 race condition |
| `pipeline/tasks/steps/video.py` | 26 | ~~`_upload_first_frame_if_needed` 中 `load_nodes[0]` 只更新第一个 LoadImage 节点，多节点时后续节点引用错误图片~~ ✅ 已修复 |
| `api/registry.py` | 142 | `Container.get` 锁外做 `not_implemented` 检查，可能基于旧注册表数据 |
| `infra/concurrency_groups.py` | 102 | ~~`acquire_backend` 异常路径的锁泄漏风险：`lock.acquire()` 本身抛异常时 `finally` 不释放~~ ✅ 已修复 |

## MEDIUM — 可选修复

| 文件 | 行号 | 问题 |
|---|---|---|
| `engines/workflow_inject.py` | 190 | `inject_ip_adapter_chain` 和 `inject_pulid_flux_chain` 大量重复代码，可抽象为通用链式注入函数 |
| `engines/prompt_compiler.py` | 85 | ~~模板缓存无刷新~~ ✅ 已修复 |
| `engines/prompt_compiler.py` | 145 | `compile_text` 变量替换只支持 `\w+` 模式，不支持 `${shot.action}` 命名空间变量 |
| `engines/portrait.py` | 94 | 重入保护 TTL 竞态：两线程同时检测到 TTL 过期时都会生成同一角色的定妆照 |
| `engines/portrait.py` | 115 | ~~docstring 过时~~ ✅ 已修复 |
| `engines/shot_calibrator.py` | 72 | ~~fallback 不记录原因~~ ✅ 已修复 |
| `engines/quality_gate.py` | 200 | ~~`_check_all_audio` 中 dialogue 空值检测不完整：`"..."`、`"——"` 等被视为有效台词~~ ✅ 已修复 |
| `engines/workflow.py` | 90 | ~~回退返回全部 LoadImage~~ ✅ 已修复 |
| `pipeline/tasks/pipeline.py` | 166 | `_retry_failed` 用 `force=True` 但未跳过 `_try_mark_running_atomic`，可能与仍在执行的原任务并发 |
| `pipeline/tasks/pipeline.py` | 208 | ~~`_apply_preset` 中 `int(base_steps * 1.4)` 截断~~ ✅ 已修复 |
| `pipeline/tasks/helpers.py` | 254 | `PrepareParams` 10 个字段的 dataclass 本质是把 10 个函数参数换成了 10 个 dataclass 字段，未减少复杂度 |
| `pipeline/tasks/media_tasks.py` | 62 | ~~`tts_single_task` 用 `cont.get("tts")` 而非 fallback~~ ✅ 已修复 |
| `pipeline/tasks/training_tasks.py` | 120 | `_try_mark_running_atomic(0, char_id, "train_lora")` 硬编码 `episode=0`，与其他任务可能冲突 |
| `pipeline/tasks/training_tasks.py` | 147 | 直接导入 `api.backends.training.ai_toolkit.TrainLoraParams`，违反 DI 容器抽象 |
| `pipeline/tasks/seko.py` | 71 | ~~`_parse_seko_characters` 中 `safe_id` 重复~~ ✅ 已修复 |
| `infra/config.py` | 89 | `ProjectPaths.projects_dir` 硬编码 `parent.parent` 路径假设，symlink 或不同部署路径会指向错误位置 |
| `infra/models.py` | 180 | `ImportValidator.validate_references` 纯验证函数内执行 DB 查询，违反关注点分离 |
| `infra/toolcheck.py` | 51 | ~~`_hc_openai` 中 URL 拼接：`http://localhost:8000/api/v1` → `endswith("/v1")` 为 True 正确，但 `http://localhost:8000/api/v2` 会变成 `.../v2/v1`~~ ✅ 已修复 |
| `infra/database/schema.py` | 1 | ~~init_schema 不使用事务~~ ✅ 已修复 |
| `infra/http_pool.py` | 73 | `get_client` 的 double-checked locking 中 closed client 的 `is_closed` 属性线程安全性不确定 |
| `infra/json_parse.py` | 106 | ~~`ast.literal_eval` 对 LLM 输出使用，超长嵌套 Python 字面量可能导致 DoS~~ ✅ 已修复 |
| `infra/retry.py` | 16 | `max_retries` 参数语义：代码和 docstring 一致（含首次执行），但与 `safe_executor.py` 的 `retries` 命名不统一 |

## LOW / YAGNI — 不修

| 文件 | 行号 | 问题 |
|---|---|---|
| `infra/hooks.py` | — | 钩子系统支持 4 种类型（init/cleanup/health_check/cache_invalidate），当前只用 2 种 |
| `infra/monitor.py` | — | WatchDog LRU 淘汰功能 `max_active=0`（未使用） |
| `infra/safe_executor.py` | 60 | `SafeExecutionError` 的 `task_id`/`attempts`/`last_error` 属性从未被读取 |
| `infra/batch_processor.py` | 116 | `_get_limits` fallback 值 `context_window=8192` 对现代 LLM 偏小，可能导致过度分批 |
| `infra/concurrency.py` | 58 | `stagger` 时序在并行环境下不精确（任务 0 的 `last_start` 未更新时任务 1 已开始计算） |
| `infra/database/storyboard_db.py` | 138 | `batch_upsert_shots` 逐行执行而非批量（`save_episode_shots` 用 `execute_values`） |
| `engines/consistency_checker.py` | 110 | `_check_emotion_transition` 中 `BLOCKED_TRANSITIONS` 在函数体内每次重建 set |
| `engines/consistency_checker.py` | 110 | `VALID_EMOTIONS` 在函数体内重复导入，应移至模块顶层 |
| `engines/shot_utils.py` | 35 | `postprocess_shots` 引号清理只检查首尾字符，不处理嵌套/不平衡引号 |
| `engines/dialogue.py` | 75 | `concat_wav` 用 `raw.find(b"data")` 搜索 chunk 标记，理论上可能误匹配 |
| `engines/character_bible.py` | 120 | `get_tags` 嵌套字典只合并一层，深层字段不会被覆盖 |
| `pipeline/tasks/steps/tts.py` | 74 | 单条/多条台词分支中 `voice_config` 构建和 TTS 调用逻辑重复 |
| `pipeline/tasks/steps/lipsync.py` | 28 | 存在性检查 + force 跳过模式在 tts/frame/video/lipsync 中完全重复 |
| `pipeline/tasks/steps/lipsync.py` | 30 | ~~`synced_path` 先赋值为 `Path` 后赋值为 `str`，类型不一致~~ ✅ 已修复 |
| `pipeline/tasks/portrait_tasks.py` | 109 | `_outfits_batch_inner` 中 `apply().get(timeout=300)` 同步阻塞调用 Celery 任务 |
| `pipeline/tasks/training_tasks.py` | 88 | `_rename_lora_result` 中 `not new_path.exists()` 检查后 `os.replace` 不是原子的 |

## 架构级观察（不立即修改，记录供参考）

1. **重试逻辑碎片化** — `retry.py`、`safe_executor.py`、`json_parse.py`、`batch_processor.py` 各自实现指数退避，策略不统一（有的有抖动，有的没有）。建议统一为一个重试引擎。
2. **项目名解析重复** — `infra/config.py:get_active_project_dir` 和 `infra/database/_db.py:_get_project` 各自读 `.active` 文件，应统一入口。
3. **状态值无枚举约束** — `STATUS_*` 常量在 `constants.py` 定义，但 DB schema 中 `status` 列是 `TEXT`，无 CHECK 约束。拼写错误不会被 DB 层拦截。
4. **DB 校验与 Pydantic 校验不统一** — `storyboard_db.py` 的 `_sanitize_duration` 和 `models.py` 的 `ImportShot.duration` 使用不同的范围常量，变化时可能不同步。
