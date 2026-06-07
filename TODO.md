# TODO

> 2026-06-07 全项目深度审查遗留项（3 子代理 + 人工审查，约 20,000 行代码）
> 已修复 27 项，见 git log。以下为未修复项。

---

## 未修复项

| 文件 | 行号 | 严重度 | 问题 | 审查结论 |
|---|---|---|---|---|
| `pipeline/tasks/steps/frame.py` | 70 | HIGH | `_upload_one` 在线程池中并发修改共享 `wf` dict | 误报 — wf 修改在主线程，不并发 |
| `api/registry.py` | 142 | HIGH | `Container.get` 锁外做 `not_implemented` 检查 | 可接受 — 快速失败优化，create 在锁内 |
| `engines/workflow_inject.py` | 190 | MEDIUM | `inject_ip_adapter_chain` 和 `inject_pulid_flux_chain` 大量重复代码 | 架构重构，个人项目不值得 |
| `engines/prompt_compiler.py` | 145 | MEDIUM | `compile_text` 变量替换只支持 `\w+` 模式 | 功能增强，当前够用 |
| `engines/portrait.py` | 94 | MEDIUM | 重入保护 TTL 竞态 | 误报 — `_generating_lock` 已保护 check-and-set |
| `pipeline/tasks/pipeline.py` | 166 | MEDIUM | `_retry_failed` 用 `force=True` 但未跳过 `_try_mark_running_atomic` | 误报 — retry 在所有 shot 完成后执行，无并发 |
| `pipeline/tasks/helpers.py` | 254 | MEDIUM | `PrepareParams` 10 个字段的 dataclass | YAGNI — named parameter 有意义 |
| `pipeline/tasks/training_tasks.py` | 120 | MEDIUM | `_try_mark_running_atomic(0, char_id, "train_lora")` 硬编码 `episode=0` | 合理 — 训练是角色级操作，episode=0 是哨兵值 |
| `pipeline/tasks/training_tasks.py` | 147 | MEDIUM | 直接导入 `ai_toolkit.TrainLoraParams` | YAGNI — DI 过度抽象 |
| `infra/config.py` | 89 | MEDIUM | `ProjectPaths.projects_dir` 硬编码 `parent.parent` | 合适 — 项目结构固定 |
| `infra/models.py` | 180 | MEDIUM | `ImportValidator.validate_references` 内执行 DB 查询 | 可接受 — 验证需要查 DB |
| `infra/http_pool.py` | 73 | MEDIUM | `get_client` double-checked locking 线程安全 | 理论问题，CPython GIL 下安全 |
| `infra/hooks.py` | — | LOW | 钩子系统支持 4 种类型，当前只用 2 种 | YAGNI |
| `infra/monitor.py` | — | LOW | WatchDog LRU 淘汰功能 `max_active=0` | YAGNI |
| `infra/safe_executor.py` | 60 | LOW | `SafeExecutionError` 属性从未被读取 | YAGNI |
| `infra/concurrency.py` | 58 | LOW | `stagger` 时序不精确 | 理论问题，实际影响极小 |
| `engines/dialogue.py` | 75 | LOW | `concat_wav` 用 `raw.find(b"data")` 搜索 chunk | 理论问题，WAV 格式足够可靠 |
| `pipeline/tasks/steps/tts.py` | 74 | LOW | voice_config 构建逻辑重复 | YAGNI — 只重复 3 行 |
| `pipeline/tasks/steps/lipsync.py` | 28 | LOW | 存在性检查 + force 跳过模式重复 | YAGNI — 只重复 2 行 |
| `pipeline/tasks/portrait_tasks.py` | 109 | LOW | `_outfits_batch_inner` 同步阻塞调用 Celery | 设计问题，个人项目可接受 |
| `pipeline/tasks/training_tasks.py` | 88 | LOW | `os.replace` 不是原子的 | POSIX 系统上是原子的 |

## 架构级观察（已审查，不修）

1. **重试逻辑碎片化** — 3 处重试各有不同职责，统一会过度抽象。**YAGNI。**
2. **项目名解析重复** — config 层和 db 层职责不同。**YAGNI。**
