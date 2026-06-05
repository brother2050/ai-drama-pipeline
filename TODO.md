# TODO

> 全项目深度审查 — 2026-06-05（第三轮）
> P0/P1 全部清零，P2 剩余架构建议

---

## 本轮修复（2 次提交）

| # | 问题 | 文件 | 提交 |
|---|------|------|------|
| 1 | 情绪跳变检查只 debug 不返回警告 | `engines/consistency_checker.py` | `529bf40` |
| 2 | `_ai_prepare_inner` 重复加载 storyboard | `pipeline/tasks/ai.py` | `529bf40` |
| 3 | 死代码赋值 `id_remap, warnings = {}, []` | `pipeline/tasks/ai.py` | `529bf40` |
| 4 | `_generate_and_mix_bgm` 未注入 Container | `post/production.py` | `529bf40` |
| 5 | `start_file_watcher` 竞态条件 | `infra/file_watcher.py` | `529bf40` |
| 6 | 3 处 bare `except` 无日志 | `web/routers/imports.py` | `529bf40` |
| 7 | `music_task` 未注入 Container | `pipeline/tasks/media_tasks.py` | `e4b02a7` |

## 验证通过（无需修改）

| 文件 | 结论 |
|------|------|
| `infra/concurrency_groups.py` | `Semaphore._value` — Python 无公开替代 API |
| `infra/batch_processor.py` | `estimate_tokens` 已正确区分中英文 |
| `engines/prompt_compiler.py` | 双模板语法是设计意图 |
| `post/distributor.py` | 已使用 `infra.ffmpeg.probe()` |
| `web/routers/deps.py` | `_cfg()` / `_merged_cfg()` 用途不同 |
| `api/registry.py` | `Container.get()` ModelRegistry 检查已在锁外 |
| `infra/json_parse.py` | `ast.literal_eval` 已在 try/except 中作最终兜底 |
| `engines/workflow.py` | `pop()` 已改为 `get()` + `pop()` |
| `infra/batch_processor.py` | `estimate_tokens` 已区分 CJK/ASCII |

## P2 — 架构优化建议（低优先级）

| # | 建议 | 说明 |
|---|------|------|
| A-1 | `infra/config.py` 711 行 | ProjectPaths 可拆为独立模块 |
| A-2 | `engines/workflow_builder.py` 723 行 | `_apply_gpu` / `_setup_img2img` 可拆为 mixins |
| A-3 | `pipeline/tasks/ai.py` 655 行 | AI 生成任务可按类型拆分 |
