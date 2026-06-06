# TODO — 全项目代码审查（2026-06-06）

> 5 个维度并行审查：Pipeline 任务层、Engines 引擎层、Infrastructure 基础设施层、Web 后端层、前端+测试+后期+脚本层。
> 按优先级排列。已修复的项不在此列。

---

## 🔴 高优先级（无）

---

## 🟡 中优先级（无）

---

## 🟢 低优先级

### 5. 测试 XSS 检测过于宽松
**文件**: `tests/test_e2e.py:~130`
**问题**: 检查 `innerHTML` 存在但仅全局搜索 `esc()` 函数，非逐行验证。
**修复**: 逐行检查每个 `innerHTML` 赋值是否有转义。

---

## ✅ 已修复（本轮审查）

| # | 文件 | 问题 | 提交 |
|---|------|------|------|
| 38 | `engines/prompt.py` | `_truncate_tag_prompt` 首个 tag 不检查 token 限制（超长 tag 独占全部预算） | `本轮` |
| 39 | `engines/multi_char.py` | `generate_multi_char_prompt` 与 `calculate_regions` 布局逻辑不一致 | `本轮` |
| 40 | `engines/workflow_inject.py` | `_resolve_model_source` 无用包装函数（直接调用 `resolve_model_source`） | `本轮` |
| 41 | `engines/prompt.py` | `from engines.prompt_compiler import tpl` 未在文件顶部（E402） | `本轮` |
| 42 | `web/routers/imports.py` | `_safe_path` 未导入导致 Seko 自定义下载路径崩溃（F821） | `本轮` |
| 43 | `web/routers/imports.py` | 未使用的 `os` 导入（F401） | `本轮` |
| 44 | `web/routers/system_tools.py` | 未使用的 `Path` 导入（F401） | `本轮` |
| 45 | `infra/database/comfyui_assets.py` | 未使用的 `row_to_dict` 导入（F401） | `本轮` |
| 46 | `pipeline/tasks/pipeline.py` | 未使用的 `_ensure_path` 导入（F401） | `本轮` |
| 47 | `infra/batch_processor.py` | lambda 赋值改为 def（E731） | `本轮` |
| 48 | `pipeline/scene_images.py` | lambda 赋值改为 def（E731） | `本轮` |
| 49 | `web/app.py` | 模糊变量名 `l` → `loc_part`（E741） | `本轮` |
| 50 | `pipeline/tasks/training_tasks.py` | 模糊变量名 `l` → `loc_part`（E741） | `本轮` |
| 51 | `engines/workflow_builder.py` | `_setup_img2img` 盲选 LoadImage 节点，排除 IP-Adapter/PuLID 节点 | `本轮` |
| 52 | `web/routers/imports.py` | `import_json` 接受 raw dict 改为 `ImportPlan` Schema 校验（422 而非运行时异常） | `本轮` |
| 53 | `scripts/ai_toolkit_api.py` | 进度解析从空格分割改为正则匹配 `(\d+)\s*/\s*(\d+)` | `本轮` |
| 54 | `web/static/js/settings.js` | `testTtsPreview` 30 行手写轮询改为 `pollTask()` | `本轮` |
| 55 | `tests/test_post.py` | 新增 post/ 模块 21 项单元测试（subtitle/production/music/vertical） | `本轮` |
| 56 | `tests/test_append.py` | 新增 ProjectBuilder.append() 10 项端到端测试（角色/场景追加+跳过+安全名） | `本轮` |
| 57 | `engines/prompt.py` + `pipeline/tasks/ai.py` | 批量翻译输出预算不足导致逐条回退；空翻译仅 warning 不报错 | `87ff025` |
| 58 | `engines/prompt.py` + `engines/portrait.py` | 五视图左右脸混淆：视角prompt太弱+同seed+正面照误导侧面/背面 | `1437fc3` |

---

## ✅ 已修复（前轮审查）

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
| 21 | `infra/monitor.py` | HealthCache.get_or_check_full 异常缓存 | `eb759c4` |
| 22 | `pipeline/tasks/media_tasks.py` | music_task 构造函数移入 try 块 | `eb759c4` |
| 23 | `engines/prompt_compiler.py` | 空角色+空动作+有情绪时不再生成无主语句子 | `eb759c4` |
| 24 | `web/routers/assets.py` | 上传大小显示改用浮点 | `eb759c4` |
| 25 | `engines/consistency_checker.py` | 情绪跳变从白名单改为黑名单 | `ee9ecc6` |
| 26 | `engines/entity_utils.py` | 同名合并记录到 warnings 返回值 | `ee9ecc6` |
| 27 | `post/subtitle.py` | 字幕时间浮点精度修复 | `ee9ecc6` |
| 28 | `web/static/js/core.js` | GET 请求不设置 Content-Type | `ee9ecc6` |
| 29 | `infra/watchdog.py` → `infra/monitor.py` | 重命名消除与 watchdog pip 包同名 | `5ed5c1f` |
| 30 | `pipeline/tasks/pipeline.py` | _retry_failed 进度计算修复 | `298f704` |
| 31 | `pipeline/tasks/pipeline.py` | _apply_preset 临时文件异常清理 | `298f704` |
| 32 | `post/production.py` | _collect_videos 改为数值排序 | `298f704` |
| 33 | `pipeline/tasks/seko.py` | 未知类型 element 图片路径加 index | `298f704` |
| 34 | `engines/character_bible.py` | save/save_en 提取公共方法 | `298f704` |
| 35 | `post/vertical.py` | split 滤镜变量名 [original] → [main] | `298f704` |
| 36 | `web/static/js/tasks.js` | 定时器按需启停 | `298f704` |
| 37 | `web/static/js/projects.js` | switchProj 改为 async/await | `298f704` |
