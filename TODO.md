# TODO

> 2026-06-07 全项目 5 链路审查（5 子代理 + 人工复核，约 20,000 行代码）
> 已修复 38 项（含前次 27 项 + 本轮 11 项），见 git log。
> 以下为未修复项，均为低优先级或需产品决策。

---

## 未修复项

| 严重度 | 文件 | 问题 | 不修理由 |
|--------|------|------|---------|
| 🟡 中 | `pipeline/tasks/training_tasks.py` | 全量导入项目已存在时静默切换追加模式，用户无感知 | 需产品决策：报错 vs 覆盖 vs 追加 |
| 🟢 低 | `pipeline/tasks/helpers.py` | `comfyui_generate` 的 `files[0]` 源文件存在性未检查 | 极端并发场景，概率极低 |
| 🟢 低 | `post/subtitle.py` | 短镜头 `duration < transition_duration` 时字幕越界 | `MIN_DURATION=2` 已保护，实际罕见 |
| 🟢 低 | `post/production.py` | BGM 回退用分镜预期时长而非已探测的 `video_durations` | 仅 ffprobe 失败时触发 |
| 🟢 低 | `scripts/project_builder.py` | 并发 TOCTOU 竞态（读 DB 去重与写 DB 之间有窗口） | 个人项目单用户场景 |
| 🟢 低 | `infra/models.py` | ImportPlan 内 characters/scenes ID 重复未检测 | LLM 生成 + 用户手动编辑均不易触发 |
| 🟢 低 | `engines/workflow_inject.py` | PuLID config 参数未完全透传（扩展性问题） | 当前仅 fusion 受影响，已修复 |
| 🟢 低 | `scripts/project_builder.py` | 追加导入非原子性（YAML 先写 DB 后写） | YAML 是配置文件非核心数据，重试即可 |

---

## 架构级观察（已审查，不修）

1. **重试逻辑碎片化** — 3 处重试各有不同职责，统一会过度抽象。**YAGNI。**
2. **项目名解析重复** — config 层和 db 层职责不同。**YAGNI。**

---

## 已修复项（本轮 git log）

| 修复 | 文件 | 说明 |
|------|------|------|
| normalize_character 返回值丢弃 | `llm_generator.py` + `entity_utils.py` | `results[:] = [...]` 回写列表 |
| transitions ffprobe "N/A" 崩溃 | `transitions.py` | `_safe_duration` 兜底 |
| 单路音频转场标签引用错误 | `transitions.py` | `audio_inputs` → `audio_parts` |
| 追加导入跨集去重丢失数据 | `project_builder.py` | `(episode, shot_id)` 元组去重 |
| 五视图参考图注入失效 | `portrait.py` | 回退到普通 LoadImage 节点 |
| 重试 force=True 重跑已成功步骤 | `pipeline.py` | 改为 force=False |
| 依赖跳过不识别 SKIPPED 状态 | `pipeline.py` | 扩展 blocked 检查 |
| SRT 异常捕获范围过窄 | `production.py` | 扩大为 Exception |
| 横转竖 ffprobe "N/A" 宽高崩溃 | `vertical.py` | try/except 兜底 |
| PuLID fusion 参数未注入 | `workflow_inject.py` | 添加到 ApplyPulidFlux inputs |
| outfit_seed 传参类型错误 | `portrait_tasks.py` | int index → string key |
| remap_shot_ids 跨类型误映射 | `entity_utils.py` + `ai.py` | char_ids/scene_ids 精确匹配 |
| 不可达 err 检查代码 | `ai.py` | 删除 dead code |
| concat_wav data chunk 定位 | `dialogue.py` | RIFF chunk 结构遍历 |
| _apply_preset 类型安全 | `pipeline.py` | int() 转换 + ValueError 捕获 |
| stagger 时序竞态 | `concurrency.py` | 读+写同一把锁 |
| ai_toolkit 子进程资源泄漏 | `ai_toolkit_api.py` | try/finally + terminate/kill |
| generated_characters 混入场景 ID | `ai.py` | entity_status 标记分组报告 |
