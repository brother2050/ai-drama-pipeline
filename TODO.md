# TODO

> 2026-06-07 全项目 5 链路审查（5 子代理 + 人工复核，约 25,000 行代码）
> 2026-06-10 分阶段执行职责分离（AI分镜/实体/准备各管各的）
> 2026-06-14 6 agent 深度审查（infra/engines/pipeline/web+api/flow+post+cli）+ 翻译自修复
> 2026-06-16 hasattr 静默失败 + 一致性节点检测 + 后端标准化审查
> 已修复 80+ 项，见 git log。

---

## 遗留项（已确认，待修复）

_无_

---

## 架构级观察（已审查，不修）

1. **重试逻辑碎片化** — 4 处重试各有不同职责，统一会过度抽象。**YAGNI。**
2. **项目名解析重复** — config 层和 db 层职责不同。**YAGNI。**
3. **健康检查逻辑重复** — `system_tools.py` 与 `toolcheck.py` 两套实现。重构收益低，暂不统一。
4. **Config 热重载线程安全** — 依赖 CPython GIL，个人项目单进程场景安全。
5. **`fcntl` 平台依赖** — 仅 Linux/macOS，个人部署场景足够。
6. **`Container._TYPE_KEY` 类变量** — 单实例使用，无实际竞态风险。
7. **Config 缓存层叠加** — `helpers.py` 和 `deps.py` 各有 Config 缓存，叠加在 `Config._check_reload()` 上。重构收益低，暂不统一。
8. **中文检测统一** — 已提取 `_has_chinese` + `_is_bad_translation`，消除 4 处重复。
9. **safe_executor max_workers=4** — `safe_run` 仅用于 TTS/lipsync/frame，shot 内串行，不构成瓶颈。**YAGNI。**
10. **deps.py _get_config() 锁外 _check_reload()** — `_reset_proj_cache` 仅 Web 请求调用，Celery 单线程无竞态。**YAGNI。**
11. **ViewPromptDict 二级缓存** — 生产环境模板不变，缓存是正确优化。开发时重启即可。**YAGNI。**
12. **context_length property 写入副作用** — property + fallback 模式，功能正确，7 处赋值是正常实现。**YAGNI。**

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
| workflow 缓存无 mtime 失效 | `engines/workflow_builder.py` | 缓存 (data, mtime) 元组，文件变化自动重载 |
| prompt 变量字典冗余计算 | `engines/prompt_compiler.py` | style/genre 先算一次再复用 |
| stagger last_start 竞态窗口 | `infra/concurrency.py` | 锁内统一更新 last_start |
| _check_outfit_reference 冗余别名导入 | `infra/models.py` | 直接用模块级已导入的函数名 |
| delete_episode 缺少 f-string | `web/routers/storyboard.py` | 错误信息显示字面 `{episode}` 而非实际集数 |
| .active 指针部分导入失败不恢复 | `scripts/project_builder.py` | 保存 prev_active，异常时恢复 |
| ImportShot.duration 类型 int | `infra/models.py` | DB 用 REAL，clip_duration 返回 float，统一为 float |
| 死代码 on_init | `infra/hooks.py` | 从未注册，连同 globals.py 的 run_hooks("init") 删除 |
| 死代码 _init_ctx | `pipeline/tasks/helpers.py` | 从未调用，直接用 _build_ctx |
| 死代码 get_or_check / get_cached | `infra/monitor.py` | 被 get_or_check_full 取代 / 从未调用 |
| 死代码 is_available / stats | `infra/concurrency_groups.py` | 从未调用，is_available 有 TOCTOU 问题 |
| 短剧管理 AI 从大纲预填 | `web/static/js/drama.js` | 生成角色/场景时从总大纲/各集大纲自动预填描述到 textarea |
| get_available_node_types 缺失 | `api/backends/image/comfyui.py` | ComfyUI 类缺少该方法 → available_nodes 恒空 → 全部一致性方案静默跳过 |
| controlnet_depth 硬编码重复 | `engines/workflow/inject.py` + `node_graph.py` | 节点可用性检查统一到 inject_from_registry() 入口，去除 Python 硬编码 |
| AIToolkitTrainer 缺少标准接口 | `api/backends/training/ai_toolkit.py` | 新增 health_check() + shutdown()，参与 Container fallback |
| upload_image 无 hasattr 保护 | `engines/workflow/builder.py` | 添加 hasattr(self.comfyui, 'upload_image') 防御 |
| _ComfyUIVideoBase 未代理 | `api/backends/video/animatediff.py` | 添加 get_available_node_types() 代理方法 |
