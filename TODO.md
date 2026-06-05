# TODO

> 来源：AUDIT.md + DEEP_AUDIT.md 交叉验证 — 2026-06-05
> P1 全部清零，P2 剩余架构建议

---

## 已修复（本轮）

| # | 问题 | 提交 |
|---|------|------|
| P1#2 | 视频工作流硬编码 `"02_img2video.json"` 回退 | `0506830` |
| P1#3 | storyboard API 每次扫描文件系统 | `692cb8a` |
| P2#4 | `resolve_node_aliases` 用 `pop()` 修改传入 dict | `0506830` |
| P2#8 | `post/music.py` 每次 `generate()` 创建新 Container | `0506830` |
| P2#12 | `_merge_translate_results` offset 累积偏差 | `0506830` |
| P2#13 | 未知图像后端静默回退空工作流 | `0506830` |
| P2#14 | `Container._resolve` 第二路径不做 name normalize | `0506830` |

## 验证通过（已正确实现/可接受）

| # | 问题 | 结论 |
|---|------|------|
| P1#1 | `batch_translate_to_english(llm=None)` | 预期行为：无 LLM 时无法翻译 |
| P2#5 | `ast.literal_eval` 接受非 JSON | 已在 try/except 中，仅作最终兜底 |
| P2#6 | `Container.get()` 锁内 ModelRegistry 检查 | 已在锁外（line 157-166） |
| P2#7 | `${}` / `{{}}` 双模板语法 | 设计意图，复杂度可控 |
| P2#9 | distributor ffprobe 重复 | 已使用 `infra.ffmpeg.probe()` |
| P2#10 | `_cfg()` / `_merged_cfg()` 双缓存 | 用途不同，设计合理 |
| P2#11 | `estimate_tokens` 英文高估 | 已区分中英文（CJK 1:1, ASCII 4:1） |

## P2 — 架构优化建议（低优先级）

| # | 建议 | 说明 |
|---|------|------|
| A-1 | `infra/config.py` 711 行 | ProjectPaths 可拆为独立模块 |
| A-2 | `engines/workflow_builder.py` 718 行 | `_apply_gpu` / `_setup_img2img` 可拆为 mixins |
| A-3 | `pipeline/tasks/ai.py` 655 行 | AI 生成任务可按类型拆分 |
