# TODO — 全项目代码审查（2026-06-06）

> 5 个维度并行审查：Pipeline 任务层、Engines 引擎层、Infrastructure 基础设施层、Web 后端层、前端+测试+后期+脚本层。
> 按优先级排列。已修复的项不在此列。

---

## 🔴 高优先级（无）

审查未发现高严重度的待修复问题。（TTS 缓存失效 bug、duration 裁剪死代码、bible dict 翻译数据丢失、outfits_batch file object bug 均已在本轮修复）

---

## 🟡 中优先级

### 1. 并发错开逻辑数学错误
**文件**: `infra/concurrency.py:40`
**问题**: 任务按 `idx * stagger_ms` 等待，实际错开间隔是 stagger_ms 的整数倍而非固定的 stagger_ms。且线程池不保证按 idx 顺序启动，导致时序不可预测。
**修复**: 改为基于上一个任务启动时间的固定间隔错开。

### 2. cursor 创建失败时 NameError 掩盖原始异常
**文件**: `infra/database/_db.py:91-100`
**问题**: `dict_cursor(conn)` 若抛异常，`finally` 块中 `cur.close()` 引发 NameError，掩盖原始异常。连接不泄漏但调试体验差。
**修复**: `cur = None` 初始化，`finally` 中 `if cur: cur.close()`。

### 3. safe_executor 每次超时创建新线程池，超时后线程泄漏
**文件**: `infra/safe_executor.py:95-102`
**问题**: 每次重试创建新 `ThreadPoolExecutor`。超时后后台线程无法终止，重试又创建新线程，可能累积阻塞线程。
**修复**: 复用线程池实例，或在超时后记录线程状态避免重复创建。

### 4. 定妆照 TTL 重入保护竞态
**文件**: `engines/portrait.py:226-233`
**问题**: `_generating` 的 TTL 检查和 `finally: _generating.pop()` 之间存在竞态窗口。线程 A 的生成耗时恰好在 TTL 边界时，线程 B 可通过检查并启动并发生成。
**修复**: TTL 检查 + 标记必须在同一把锁内原子完成。

### 5. 混合类型列表：角色 LoRA 分类逻辑脆弱
**文件**: `engines/workflow_builder.py:281-282` → `engines/workflow_inject.py:52-55`
**问题**: `chars_with_lora` 存 `(cid, lora_path)` 元组，`chars_without_lora` 存 `cid` 字符串。后续 `set()` 操作恰好能工作但依赖巧合，重构易引入 bug。
**修复**: 统一数据结构，如全部使用 dict。

### 6. LLM 结果对齐 fallback 假设顺序一致
**文件**: `engines/shot_calibrator.py:117-119`
**问题**: `_enrich_stage` 按 shot_id 合并失败时 fallback 到 `result[i]` 按索引取值。LLM 返回顺序不可控，可能将错误数据合并到错误镜头。
**修复**: 去掉按索引 fallback，shot_id 匹配失败时跳过该镜头。

### 7. 健康检查异常误判
**文件**: `web/routers/system_tools.py:98`
**问题**: `as_completed` 的 `except TimeoutError` 在 Python 3.11+ 中行为不同，可能将连接拒绝等真实不可用误判为"检测超时"。
**修复**: 区分超时异常和连接异常，分别处理。

### 8. Seko 下载目录路径遍历预检不足
**文件**: `web/routers/imports.py:80`
**问题**: `download_dir` 仅检查 `..`，未处理 `....//` 或 URL 编码变体。下游 `download_elements_images` 若不做路径校验，存在写入任意目录风险。
**修复**: 使用 `_safe_path` 统一校验 download_dir。

### 9. 测试 ROOT 路径错误
**文件**: `tests/test_import_standalone.py:6`, `tests/test_import_e2e_standalone.py:6`
**问题**: `ROOT = Path(__file__).resolve().parent` 指向 `tests/` 而非项目根目录。直接运行 `python tests/test_xxx.py` 会因模块找不到而失败。
**修复**: 改为 `parent.parent`。

### 10. 缺少后期处理单元测试
**文件**: `tests/` 目录
**问题**: `post/production.py`（拼接流程）、`post/vertical.py`（裁剪逻辑）没有单元测试。
**修复**: 添加 post/ 模块的单元测试。

### 11. 缺少追加导入模式测试
**文件**: `tests/` 目录
**问题**: `ProjectBuilder.append()` 没有端到端测试。`test_import_standalone.py` 仅测 Schema 校验。
**修复**: 添加 append 模式的端到端测试。

### 12. 项目删除时 DB 清理部分失败仍删目录
**文件**: `scripts/project_mgr.py:160-180`
**问题**: `_cleanup_project_db` 异常被 catch 后，`shutil.rmtree` 仍执行，导致孤立 DB 记录。
**修复**: DB 清理失败时中止删除，或记录警告后清理 DB 残留。

### 13. `_run_concurrent` 异常未捕获导致整个批次失败
**文件**: `pipeline/tasks/pipeline.py` (`_run_concurrent`)
**问题**: `run_staggered_sync` 若抛异常，整个集级任务以 unhandled exception 失败，已成功镜头的结果丢失。
**修复**: 包裹 try/except，返回包含部分结果的 error dict。

### 14. `post_task` 中 `_run_post` 嵌套 project_scope 可能不可重入
**文件**: `pipeline/tasks/media_tasks.py:29-38`
**问题**: `_run_post` 自己创建 `project_scope`，从 `run_all_task` 调用时外层已有 scope。若不可重入，内层可能覆盖外层项目名。
**修复**: 验证 `project_scope` 可重入性，或改为传递项目名参数。

---

## 🟢 低优先级

### 15. HealthCache.get_or_check_full 不捕获 checker 异常
**文件**: `infra/watchdog.py:195`
**问题**: 与 `get_or_check()` 不同，不捕获异常。已知失败不会被缓存，每次重复触发。
**修复**: 添加 try/except，缓存失败结果（短 TTL）。

### 16. 情绪跳变白名单不完整
**文件**: `engines/consistency_checker.py:102-118`
**问题**: `ALLOWED_TRANSITIONS` 只有 ~11 种组合，大量合法跳变（如 happy→angry 喜剧反转）被误报为警告。
**修复**: 扩展白名单或改为黑名单模式。

### 17. 翻译失败语义丢失
**文件**: `engines/prompt.py:186-195`
**问题**: `translate_to_english` 失败返回空字符串，与"本来就空"无法区分。质量门禁可能误报。
**修复**: 返回 `(text, success)` 元组或使用特殊标记。

### 18. 自然语言 prompt 编译：空字符/动作生成畸形输出
**文件**: `engines/prompt_compiler.py:178-195`
**问题**: `_compile_natural` 当 character 和 action 都为空时，单独的 `"With a worried expression."` 缺乏主语。
**修复**: 空值时生成最小有效 prompt。

### 19. CharacterBible.save 和 save_en 重复代码
**文件**: `engines/character_bible.py:119-148`
**问题**: 两个方法结构完全相同，仅 bible vs bible_en 不同。
**修复**: 提取 `_save_bible(char_id, key, data, cache)`。

### 20. `_build_context` 在 shot_calibrator 和 llm_generator 间重复
**文件**: `engines/shot_calibrator.py:58-79` vs `engines/llm_generator.py:35-62`
**问题**: 上下文构建逻辑高度重复。
**修复**: 提取共享的 `_build_storyboard_context()`。

### 21. entity_utils 同名合并静默丢弃数据
**文件**: `engines/entity_utils.py:98-105`
**问题**: 第二个同名实体被跳过，无用户提示。
**修复**: 在 warnings 中记录被合并的实体信息。

### 22. img2img 盲选第一个 LoadImage 节点
**文件**: `engines/workflow_builder.py:189-190`
**问题**: `_setup_img2img` 用 `load_nodes[0]` 注入参考图，未验证是否为 img2img 专用节点。模板变更可能注入到错误节点。
**修复**: 通过节点命名或 class_type 区分 img2img 和 IP-Adapter 的 LoadImage。

### 23. `_apply_preset` 临时文件泄漏
**文件**: `pipeline/tasks/pipeline.py` (`_apply_preset`)
**问题**: `tempfile.mkstemp` 创建的临时文件在 `save_config` 异常时不会被清理。
**修复**: 用 try/finally 包裹。

### 24. `_retry_failed` 进度计算超过 100%
**文件**: `pipeline/tasks/pipeline.py` (`_retry_failed`)
**问题**: 进度值 `(total + len(failed)) / total` 大于 1，且循环内不变化。
**修复**: 按实际迭代进度计算。

### 25. music_task 构造函数未包裹 try/except
**文件**: `pipeline/tasks/media_tasks.py:85-93`
**问题**: `MusicGenerator()` 构造异常时前端只能看到 Celery generic failure。
**修复**: 构造函数放入 try 块。

### 26. import_json 接受原始 dict 无 Schema 校验
**文件**: `web/routers/system_tools.py:188`
**问题**: `import_json(plan_data: dict)` 接受任意 JSON，不合规数据导致运行时异常而非 422。
**修复**: 使用 `ImportPlan` 或中间 Schema 校验。

### 27. assets.py 上传大小校验错误信息显示 "0MB"
**文件**: `web/routers/assets.py:50`
**问题**: `len(content) // 1024 // 1024` 对 20MB 以下整除为 0，错误信息误导。
**修复**: 直接用常量值显示限制。

### 28. 多人同框布局参数不一致
**文件**: `engines/multi_char.py:28-32, 38-40`
**问题**: `generate_multi_char_prompt` 和 `calculate_regions` 对非 "side_by_side" 布局的处理不一致。
**修复**: 统一布局参数映射。

### 29. prompt 截断：单 tag 超限时仍被保留
**文件**: `engines/prompt.py:164-180`
**问题**: 第一个 tag 无论 token 代价多高都会被保留。
**修复**: 第一个 tag 也检查 token 限制。

### 30. `_clear_tts_char_cache` 已修复但需验证 hooks 传播
**文件**: `pipeline/tasks/steps/tts.py:14-17`
**问题**: 已修复 `_chars_dir` 重置。但需确认 `on_cache_invalidate` 钩子在文件变化时确实被触发。
**状态**: 已修复，待验证。

### 31. 测试 XSS 检测过于宽松
**文件**: `tests/test_e2e.py:~130`
**问题**: 检查 `innerHTML` 存在但仅全局搜索 `esc()` 函数，非逐行验证。
**修复**: 逐行检查每个 `innerHTML` 赋值是否有转义。

### 32. Seko 未知类型 element 图片互相覆盖
**文件**: `pipeline/tasks/seko.py:284-286`
**问题**: 非 CHARACTER/SCENE 的 element 类型图片都下载到 `assets/seko/cover.png`。
**修复**: 加入 element index 区分文件名。

### 33. ai_toolkit_api.py 进度解析依赖脆弱的日志格式
**文件**: `scripts/ai_toolkit_api.py:~110`
**问题**: 通过空格分割查找 `X/Y` 格式，AI Toolkit 更新日志格式后静默失效。
**修复**: 使用正则匹配多种格式。

### 34. production.py 的 `_collect_videos` 依赖字母排序
**文件**: `post/production.py:~25`
**问题**: `sorted(out_dir.glob("s*"))` 使用字母排序。当前零填充 ID 正确，但无防御性检查。
**修复**: 添加 shot_id 数值排序或格式校验。

### 35. 前端 `api()` 对 GET 请求也发送 Content-Type
**文件**: `web/static/js/core.js:~100`
**问题**: GET 请求无 body，发送 `Content-Type: application/json` 无意义。
**修复**: GET 请求不设置 Content-Type。

### 36. TaskPanel 3 秒定时器无任务时仍运行
**文件**: `web/static/js/tasks.js:~280`
**问题**: `setInterval` 始终运行，即使无活跃任务。
**修复**: 有任务时启动，无任务时停止。

### 37. testTtsPreview 自建轮询未复用 pollTask
**文件**: `web/static/js/settings.js:~180-215`
**问题**: 独立实现 60 次轮询循环，重复了 core.js 的 pollTask 逻辑。
**修复**: 改用 `pollTask()`。

### 38. vertical.py 的 split 滤镜变量命名误导
**文件**: `post/vertical.py:~80`
**问题**: `split[original][blur]` 中 `[original]` 实际是副本，不是原始流。
**修复**: 改名为 `[orig_copy]` 或 `[main]`。

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
