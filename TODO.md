# TODO — 全项目代码审查（2026-06-06）

> 5 个维度并行审查：Pipeline 任务层、Engines 引擎层、Infrastructure 基础设施层、Web 后端层、前端+测试+后期+脚本层。
> 按优先级排列。已修复的项不在此列。

---

## 🔴 高优先级（无）

审查未发现高严重度的待修复问题。（TTS 缓存失效 bug、duration 裁剪死代码、bible dict 翻译数据丢失、outfits_batch file object bug 均已在本轮修复）

---

## 🟡 中优先级

### 1. 缺少后期处理单元测试
**文件**: `tests/` 目录
**问题**: `post/production.py`（拼接流程）、`post/vertical.py`（裁剪逻辑）没有单元测试。
**修复**: 添加 post/ 模块的单元测试。

### 2. 缺少追加导入模式测试
**文件**: `tests/` 目录
**问题**: `ProjectBuilder.append()` 没有端到端测试。`test_import_standalone.py` 仅测 Schema 校验。
**修复**: 添加 append 模式的端到端测试。

---

## 🟢 低优先级

### 3. CharacterBible.save 和 save_en 重复代码
**文件**: `engines/character_bible.py:119-148`
**问题**: 两个方法结构完全相同，仅 bible vs bible_en 不同。
**修复**: 提取 `_save_bible(char_id, key, data, cache)`。

### 4. `_build_context` 在 shot_calibrator 和 llm_generator 间重复
**文件**: `engines/shot_calibrator.py:58-79` vs `engines/llm_generator.py:35-62`
**问题**: 上下文构建逻辑高度重复。
**修复**: 提取共享的 `_build_storyboard_context()`。

### 5. img2img 盲选第一个 LoadImage 节点
**文件**: `engines/workflow_builder.py:189-190`
**问题**: `_setup_img2img` 用 `load_nodes[0]` 注入参考图，未验证是否为 img2img 专用节点。模板变更可能注入到错误节点。
**修复**: 通过节点命名或 class_type 区分 img2img 和 IP-Adapter 的 LoadImage。

### 6. `_apply_preset` 临时文件泄漏
**文件**: `pipeline/tasks/pipeline.py` (`_apply_preset`)
**问题**: `tempfile.mkstemp` 创建的临时文件在 `save_config` 异常时不会被清理。
**修复**: 用 try/finally 包裹。

### 7. `_retry_failed` 进度计算超过 100%
**文件**: `pipeline/tasks/pipeline.py` (`_retry_failed`)
**问题**: 进度值 `(total + len(failed)) / total` 大于 1，且循环内不变化。
**修复**: 按实际迭代进度计算。

### 8. import_json 接受原始 dict 无 Schema 校验
**文件**: `web/routers/system_tools.py:188`
**问题**: `import_json(plan_data: dict)` 接受任意 JSON，不合规数据导致运行时异常而非 422。
**修复**: 使用 `ImportPlan` 或中间 Schema 校验。

### 9. 多人同框布局参数不一致
**文件**: `engines/multi_char.py:28-32, 38-40`
**问题**: `generate_multi_char_prompt` 和 `calculate_regions` 对非 "side_by_side" 布局的处理不一致。
**修复**: 统一布局参数映射。

### 10. prompt 截断：单 tag 超限时仍被保留
**文件**: `engines/prompt.py:164-180`
**问题**: 第一个 tag 无论 token 代价多高都会被保留。
**修复**: 第一个 tag 也检查 token 限制。

### 11. 测试 XSS 检测过于宽松
**文件**: `tests/test_e2e.py:~130`
**问题**: 检查 `innerHTML` 存在但仅全局搜索 `esc()` 函数，非逐行验证。
**修复**: 逐行检查每个 `innerHTML` 赋值是否有转义。

### 12. Seko 未知类型 element 图片互相覆盖
**文件**: `pipeline/tasks/seko.py:284-286`
**问题**: 非 CHARACTER/SCENE 的 element 类型图片都下载到 `assets/seko/cover.png`。
**修复**: 加入 element index 区分文件名。

### 13. ai_toolkit_api.py 进度解析依赖脆弱的日志格式
**文件**: `scripts/ai_toolkit_api.py:~110`
**问题**: 通过空格分割查找 `X/Y` 格式，AI Toolkit 更新日志格式后静默失效。
**修复**: 使用正则匹配多种格式。

### 14. production.py 的 `_collect_videos` 依赖字母排序
**文件**: `post/production.py:~25`
**问题**: `sorted(out_dir.glob("s*"))` 使用字母排序。当前零填充 ID 正确，但无防御性检查。
**修复**: 添加 shot_id 数值排序或格式校验。

### 15. TaskPanel 3 秒定时器无任务时仍运行
**文件**: `web/static/js/tasks.js:~280`
**问题**: `setInterval` 始终运行，即使无活跃任务。
**修复**: 有任务时启动，无任务时停止。

### 16. testTtsPreview 自建轮询未复用 pollTask
**文件**: `web/static/js/settings.js:~180-215`
**问题**: 独立实现 60 次轮询循环，重复了 core.js 的 pollTask 逻辑。
**修复**: 改用 `pollTask()`。

### 17. vertical.py 的 split 滤镜变量命名误导
**文件**: `post/vertical.py:~80`
**问题**: `split[original][blur]` 中 `[original]` 实际是副本，不是原始流。
**修复**: 改名为 `[orig_copy]` 或 `[main]`。

### 18. switchProj 未 await API 调用
**文件**: `web/static/js/projects.js:~150`
**问题**: `switchProj` 使用 `.then()` 链式调用而非 `async/await`。调用方无法得知操作何时完成。
**修复**: 改为 async/await。

---

## ✅ 已修复（本轮）

| # | 文件 | 问题 | 提交 |
|---|------|------|------|
| 1 | `pipeline/tasks/steps/tts.py` | TTS 缓存失效未重置 `_chars_dir` | `6ec3f88` |
| 2 | `pipeline/tasks/pipeline.py` | duration 裁剪是死代码（ctx 引用未更新） | `6ec3f88` |
| 3 | `pipeline/tasks/portrait_tasks.py` | `load_yaml_full(file_object)` 应传 Path | `73696bc` |
| 4 | `pipeline/tasks/ai.py` | bible dict 翻译 LLM 行数不足时丢弃 key | `cd97d99` |
| 5 | `infra/batch_processor.py` | 自适应批处理器缺 total_items/retries/elapsed 统计 | `29ce635` |
| 6 | `engines/prompt.py` | 重复的 `estimate_tokens` 函数 | `49aa2a9` |
| 7 | `engines/prompt_compiler.py` | `_clean_empty_values` 无界 while 循环 | `49aa2a9` |
| 8 | `engines/workflow.py` + `workflow_inject.py` | `_resolve_model_source` 重复逻辑 | `49aa2a9` |
| 9 | `web/schemas/__init__.py` | `ChatEditRequest.message` 缺 max_length | `49aa2a9` |
| 10 | `api/registry.py` | YAML 变体名误报 warning（降为 debug） | `8be5d0a` |
| 11 | `infra/concurrency.py` | 并发错开按 idx 累乘改为固定间隔 | `e708740` |
| 12 | `infra/database/_db.py` | cursor 创建失败 NameError | `e708740` |
| 13 | `infra/safe_executor.py` | 超时线程池改为进程级复用 | `e708740` |
| 14 | `engines/portrait.py` | TTL 竞态：finally 只清除自己的标记 | `f174f99` |
| 15 | `engines/workflow_builder.py` | LoRA 分类混合类型改为统一 dict | `f174f99` |
| 16 | `engines/shot_calibrator.py` | LLM 对齐去掉按索引 fallback | `f174f99` |
| 17 | `tests/test_import*.py` | ROOT 路径 parent → parent.parent | `dcf70f2` |
| 18 | `pipeline/tasks/pipeline.py` | _run_concurrent 异常捕获 | `dcf70f2` |
| 19 | `web/routers/system_tools.py` | 健康检查单个超时 vs 整体超时区分 | `dcf70f2` |
| 20 | `web/routers/imports.py` | Seko download_dir 路径遍历改为 _safe_path | `eb759c4` |
| 21 | `infra/watchdog.py` | HealthCache.get_or_check_full 异常缓存 | `eb759c4` |
| 22 | `pipeline/tasks/media_tasks.py` | music_task 构造函数移入 try 块 | `eb759c4` |
| 23 | `engines/prompt_compiler.py` | 空角色+空动作+有情绪时不再生成无主语句子 | `eb759c4` |
| 24 | `web/routers/assets.py` | 上传大小显示改用浮点 | `eb759c4` |
| 25 | `engines/consistency_checker.py` | 情绪跳变从白名单改为黑名单 | `ee9ecc6` |
| 26 | `engines/entity_utils.py` | 同名合并记录到 warnings 返回值 | `ee9ecc6` |
| 27 | `post/subtitle.py` | 字幕时间浮点精度修复 | `ee9ecc6` |
| 28 | `web/static/js/core.js` | GET 请求不设置 Content-Type | `ee9ecc6` |
