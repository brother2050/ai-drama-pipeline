# TODO

> 2026-06-07 全项目 5 链路审查（5 子代理 + 人工复核，约 20,000 行代码）
> 已修复 51 项（含前次 45 项 + 本轮 6 项），见 git log。

---

## 遗留项

> 无遗留项。

---

## 架构级观察（已审查，不修）

1. **重试逻辑碎片化** — 3 处重试各有不同职责，统一会过度抽象。**YAGNI。**
2. **项目名解析重复** — config 层和 db 层职责不同。**YAGNI。**
3. **健康检查逻辑重复** — `system_tools.py` 与 `toolcheck.py` 两套实现。重构收益低，暂不统一。
4. **Config 热重载线程安全** — 依赖 CPython GIL，个人项目单进程场景安全。
5. **`fcntl` 平台依赖** — 仅 Linux/macOS，个人部署场景足够。
6. **`Container._TYPE_KEY` 类变量** — 单实例使用，无实际竞态风险。

---

## 已修复项（完整历史）

| 修复 | 文件 | 说明 |
|------|------|------|
| 删除死代码 shot_calibrator | `engines/shot_calibrator.py` | 3 阶段校准系统从未被调用，连同 3 个 prompt 模板一起删除 |
| 删除死代码 expand_outline | `engines/llm_generator.py` | 无调用方 |
| 实体顺序依赖 bug | `engines/llm_generator.py` | LLM 返回乱序时用 ID 匹配而非位置匹配 |
| appearance_prompt_en 被覆盖 | `pipeline/tasks/ai.py` + 5 文件 | LLM 结果存入 appearance_prompt_generated，不覆盖翻译 |
| 批量 prompt 部分失败丢弃 | `engines/prompt.py` | 部分成功返回已有结果，不 raise |
| 转场回退 SRT 不匹配 | `post/production.py` | 回退简单拼接后重新生成无转场 SRT |
| 多人对话字幕单行 | `post/subtitle.py` | 保留 SRT 换行，每行单独 sanitize |
| 字幕越界 | `post/subtitle.py` | 最后一条字幕用完整 duration |
| TOCTOU 竞态 | `scripts/project_builder.py` | 移除应用层 DB 去重，改用 DB 级 upsert |
| 导入静默切换追加模式 | `training_tasks.py` | 返回 mode_switched + warning |
| comfyui_generate files[0] 未检查 | `helpers.py` | 源文件存在性防御检查 |
| BGM 回退用预期时长 | `production.py` | 复用已探测的 video_durations |
| ImportPlan ID 重复未检测 | `infra/models.py` | characters/scenes ID 重复校验 |
| normalize_character 返回值丢弃 | `llm_generator.py` + `entity_utils.py` | results[:] = [...] 回写列表 |
| transitions ffprobe "N/A" 崩溃 | `transitions.py` | _safe_duration 兜底 |
| 单路音频转场标签引用错误 | `transitions.py` | audio_inputs → audio_parts |
| 追加导入跨集去重丢失数据 | `project_builder.py` | (episode, shot_id) 元组去重 |
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
