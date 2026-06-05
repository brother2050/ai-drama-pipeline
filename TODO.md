# TODO

> 来源：AUDIT.md + DEEP_AUDIT.md 交叉验证 — 2026-06-05
> 仅保留经代码确认仍存在且有修复价值的条目

---

## P1 — 功能/逻辑缺陷

| # | 文件:行号 | 问题 | 说明 |
|---|-----------|------|------|
| ~~2~~ | ~~`engines/workflow_builder.py:114`~~ | ~~视频工作流回退硬编码~~ | ✅ 已修复：改为 raise ValueError |
| ~~3~~ | ~~`web/routers/storyboard.py:55-80`~~ | ~~每次 episodes 列表 API 扫描文件系统~~ | ✅ 已修复：优先从 DB 查询，回退到 FS 扫描 |

## P2 — 代码质量/健壮性

| # | 文件:行号 | 问题 | 说明 |
|---|-----------|------|------|
| 4 | `engines/workflow.py:18` | `resolve_node_aliases` 用 `pop()` 修改传入 dict | 调用方有 deepcopy 保护，但函数签名暗示非破坏性。改为 `get()` + 手动删除更安全 |
| ~~5~~ | ~~`infra/json_parse.py:210`~~ | ~~`ast.literal_eval` 接受非 JSON 结构~~ | ✅ 可接受：已在 try/except 中，仅作最终兜底 |
| ~~6~~ | ~~`api/registry.py:106-120`~~ | ~~`Container.get()` 锁内执行 ModelRegistry 检查~~ | ✅ 已在锁外（line 157-166），注释标注正确 |
| ~~7~~ | ~~`engines/prompt_compiler.py:104-107`~~ | ~~`${}` 和 `{{}}` 两套模板语法~~ | ✅ 可接受：设计意图（YAML 用 `${}`，代码内嵌用 `{{}}`），两条 regex 复杂度可控 |
| 8 | `post/music.py:27-33` | 每次 `generate()` 创建新 Container | 应注入 Container 或缓存复用 |
| ~~9~~ | ~~`post/distributor.py:50-53`~~ | ~~`ffprobe` 逻辑重复实现~~ | ✅ 已使用 `infra.ffmpeg.probe()`（line 38），`get_video_info` 是字段提取封装 |
| ~~10~~ | ~~`web/routers/deps.py:25-45`~~ | ~~`_cfg()` / `_merged_cfg()` 双层配置缓存~~ | ✅ 可接受：两者用途不同（项目级 vs 合并配置），TTL 缓存减少 Config 对象创建开销 |
| ~~11~~ | ~~`infra/batch_processor.py:29-31`~~ | ~~`estimate_tokens` 对英文高估~~ | ✅ 已修复：CJK 按 1 token/字，ASCII 按 1 token/4 字符（line 31） |
| 12 | `engines/prompt.py:193-220` | `_merge_translate_results` offset 累积 | 批量翻译结果合并时，batch_size 估算可能导致索引映射偏差 |
| 13 | `engines/workflow_builder.py:77-85` | 未知图像后端回退到空工作流 | 静默返回无输出。应 raise 明确错误 |
| 14 | `api/registry.py:173-180` | `Container._resolve` 不做 name normalize | `fish-speech` vs `fish_speech` 可能匹配不上 |

## P2 — 架构优化建议

| # | 建议 | 说明 |
|---|------|------|
| A-1 | `infra/config.py` 711 行 | ProjectPaths 可拆为独立模块 |
| A-2 | `engines/workflow_builder.py` 718 行 | `_apply_gpu` / `_setup_img2img` 可拆为 mixins |
| A-3 | `pipeline/tasks/ai.py` 655 行 | AI 生成任务可按类型拆分 |

## 可接受（无需修改）

| 文件 | 说明 |
|------|------|
| `infra/json_parse.py` 6 处 except | JSON 多策略解析的正常回退，预期失败 |
| `cli/__init__.py:202` | Celery 检查降级（Worker 未启动时合理） |
| `pipeline/tasks/seko.py:145` | Seko 数据解析回退 |
| `scripts/ai_toolkit_api.py:172` | 训练日志行解析失败，正常回退 |
| `post/vertical.py:108` | `_cy` 未使用 — `crop_h == h` 时无需垂直裁剪，无实际影响 |
| `infra/concurrency_groups.py:79` | `Semaphore._value` 私有属性 — Python 无公开替代 API |
| `engines/prompt.py:324` | `batch_translate_to_english(llm=None)` 早返回是预期行为；回退路径正确传入 `llm` |
