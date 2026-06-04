# 🔍 AI 短剧管线 v2 — 深度代码审查报告

> 审查范围：全项目 170 文件、22000+ 行代码
> 审查维度：功能缺陷、逻辑缺陷、代码缺陷
> 面向新用户，不兼容旧数据，个人使用不管安全

---

## P0 — 必修（运行时必崩或逻辑严重错误）

| # | 模块 | 文件:行号 | 类型 | 描述 |
|---|------|-----------|------|------|
| 1 | pipeline | `pipeline/tasks/pipeline.py:246` | 逻辑缺陷 | `results["quality_issues"] = issues` — `results` 是 list，不能用 str 做 key，运行时 `TypeError` |
| 2 | pipeline | `pipeline/tasks/training_tasks.py:170,189` | 逻辑缺陷 | `_import_json_append` / `_import_json_full` 引用局部变量 `_ROOT`，运行时 `NameError` |
| 3 | post | `post/vertical.py:96-100` | 逻辑缺陷 | blur_bg 模式 ffmpeg filter 前景缩放比例错误，输出视频有黑边或裁剪 |
| 4 | infra | `infra/safe_executor.py:81-85` | 功能缺陷 | `safe_run` 超时后后台线程继续运行，无法取消，资源泄漏 |
| 5 | infra | `infra/batch_processor.py:91` | 代码缺陷 | `_last_error` 类变量注解 vs 实例变量赋值混淆，设计脆弱 |
| 6 | engines | `engines/prompt.py:178-180` | 功能缺陷 | `translate_to_english` 当 `llm=None` 时返回原始中文，下游静默传入 ComfyUI 导致生成质量严重下降 |

---

## P1 — 建议修（潜在错误、性能问题、逻辑隐患）

### engines 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 7 | `engines/storyboard.py:42-48` | 逻辑缺陷 | `append_storyboard` 中 `int("")` 静默跳过，用户无感知丢弃镜头 |
| 8 | `engines/prompt.py:155-171` | 逻辑缺陷 | `_truncate_tag_prompt` token/字符单位混用，SD1.5 prompt 截断阈值约为预期 4 倍宽松 |
| 9 | `engines/prompt.py:193-220` | 逻辑缺陷 | `batch_translate_to_english` 中 `_merge_translate_results` 的 offset 累积误差，翻译结果可能映射到错误索引 |
| 10 | `engines/prompt.py:233-236` | 逻辑缺陷 | 回退翻译传入 `llm=None`，永远返回中文原文，不会真正翻译 |
| 11 | `engines/llm_generator.py:27` | 逻辑缺陷 | `STORYBOARD_SYSTEM` 等 4 个模块级常量在加载时执行，YAML 不存在时静默降级为空字符串 |
| 12 | `engines/llm_generator.py:99-109` | 逻辑缺陷 | `_generate_entities` 不检查空 dict `{}`，空结果被当作成功 |
| 13 | `engines/shot_calibrator.py:100-108` | 逻辑缺陷 | `_enrich_stage` 50% 阈值硬编码，49% 镜头缺少必填字段仍视为成功 |
| 14 | `engines/shot_calibrator.py:100-108` | 逻辑缺陷 | shot_id 有误时（"001" vs "1"）错误按索引匹配，字段写入错误镜头 |
| 15 | `engines/shot_calibrator.py:33-38` | 功能缺陷 | Stage 2/3 失败时只 warning 继续，返回缺少 action/dialogue 的镜头 |
| 16 | `engines/shot_manager.py:30-34` | 逻辑缺陷 | `episode=0` 不是有效集数，`load_storyboard(episode=0)` 查询不存在的集 |
| 17 | `engines/shot_utils.py:25-28` | 逻辑缺陷 | 去重和格式校验是 OR 关系，合法 sid 可能被覆盖 |
| 18 | `engines/shot_utils.py:35-38` | 逻辑缺陷 | duration 硬截断 [2,8]，LLM 创作意图丢失 |
| 19 | `engines/shot_utils.py:56-78` | 逻辑缺陷 | `strip_dialogue` 中文动词列表不全（缺"讲""念""嘟囔"等），对话内容残留在 action 中 |
| 20 | `engines/workflow_builder.py:77-85` | 逻辑缺陷 | 未知图像后端回退到空工作流，静默返回无输出 |
| 21 | `engines/workflow_builder.py:89-93` | 逻辑缺陷 | 视频后端回退硬编码 `"02_img2video.json"`，违反零硬编码原则 |
| 22 | `engines/workflow_builder.py:242-265` | 逻辑缺陷 | `_setup_img2img` 文件名在上传前设置，ComfyUI 可能找不到文件 |
| 23 | `engines/workflow.py:16-21` | 逻辑缺陷 | `resolve_node_aliases` 用 `pop()` 直接修改传入 dict，破坏性操作 |
| 24 | `engines/workflow.py:67-78` | 逻辑缺陷 | `set_clip_text_prompts` 将所有非 negative CLIPTextEncode 都设为 positive，第三节点被覆盖 |
| 25 | `engines/workflow_inject.py:47-50` | 逻辑缺陷 | 只检查 IPAdapterAdvanced，PuLID 工作流会错误注入 IP-Adapter |
| 26 | `engines/workflow_inject.py:181-215` | 逻辑缺陷 | `inject_pulid_flux` 第一个角色无参考图时跳过所有后续角色 |
| 27 | `engines/workflow_inject.py:259-273` | 逻辑缺陷 | LoRA 注入后 clip 连接未更新，绕过了 LoRA 对 CLIP 的微调 |
| 28 | `engines/portrait.py:26-32` | 逻辑缺陷 | 注释说"三张图"实际是五张，不一致 |
| 29 | `engines/models.py:148-157` | 逻辑缺陷 | `type("C", (), {...})()` 伪对象访问其他属性会出错 |
| 30 | `engines/models.py:196-220` | 逻辑缺陷 | `normalize_character` 就地修改输入 dict，调用方引用被污染 |
| 31 | `engines/models.py:205,208` | 逻辑缺陷 | 过滤所有 http URL 过于激进，用户有意的网络图被丢弃 |

### pipeline 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 32 | `pipeline/tasks/pipeline.py:46-47` | 逻辑缺陷 | 原地修改 `shot_data["duration"]`，共享 dict 被污染 |
| 33 | `pipeline/tasks/pipeline.py:134-138` | 逻辑缺陷 | `.apply().get()` 在并发模式下可能死锁，应用 `apply_async` |
| 34 | `pipeline/tasks/steps.py:48-52` | 逻辑缺陷 | `tts_core` 中 `characters=None` 时每次都重建 `ShotManager`，50+ 镜头批量处理时大量重复 IO |
| 35 | `pipeline/tasks/ai.py:620` | 逻辑缺陷 | `_ai_prepare_inner` 两次加载 storyboard，中间被修改会导致回写错误数据 |
| 36 | `pipeline/tasks/ai.py:60-61` | 逻辑缺陷 | `warnings` 用 `=` 赋值而非 `extend()`，前序 warnings 丢失 |
| 37 | `pipeline/tasks/portrait_tasks.py:130` | 逻辑缺陷 | `outfits_batch_task` 未绑定 project_scope，DB 写入可能指向错误项目 |
| 38 | `pipeline/tasks/helpers.py:171-200` | 逻辑缺陷 | `_build_ctx` 双检锁在 Celery fork 后可能失效，worker 启动时应调用 `invalidate_ctx_cache()` |
| 39 | `pipeline/tasks/helpers.py:272` | 逻辑缺陷 | SQL 用 `EXTRACT(EPOCH FROM ...)` 仅 PostgreSQL 兼容，SQLite 测试环境会通过但生产报错 |
| 40 | `pipeline/preview.py:76-84` | 逻辑缺陷 | 直接修改 `cfg.data["generation"]` 有并发风险，其他任务看到被污染的配置 |
| 41 | `pipeline/scene_images.py:104` | 逻辑缺陷 | 空场景列表返回 `STATUS_ERROR`，应返回 `STATUS_DONE` + `generated=0` |

### post 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 42 | `post/production.py:170-171` | 逻辑缺陷 | storyboard 被加载 3 次（run_post + _run_subtitle），应加载一次传递 |
| 43 | `post/production.py:99` | 逻辑缺陷 | `cfg.get("post_production.bgm_volume", 0.15)` 嵌套 key 是否支持取决于 Config 实现 |
| 44 | `post/subtitle.py:37-41` | 逻辑缺陷 | `transition_duration > duration` 时字幕时间重叠为 0 |
| 45 | `post/music.py:27-33` | 逻辑缺陷 | 每次 `generate()` 都创建新 Container，开销大 |
| 46 | `post/music.py:40-47` | 逻辑缺陷 | 模板回退方案生成 sine 波当配乐，用户体验极差但只有 `logger.debug` |
| 47 | `post/vertical.py:77` | 逻辑缺陷 | `_find_face_center` 返回的 `cy` 未被使用，裁剪固定 y=0 |
| 48 | `post/distributor.py:108` | 逻辑缺陷 | 返回 status 值不一致（`"ready"` vs `STATUS_ERROR`） |

### infra 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 49 | `infra/globals.py:97-108` | 逻辑缺陷 | shutdown 中 cleanup 钩子与全局变量置 None 时序问题 |
| 50 | `infra/watchdog.py:101-109` | 功能缺陷 | 超时仅标记不中断，`except TimeoutError` 永不触发 |
| 51 | `infra/hooks.py:113-126` | 逻辑缺陷 | cleanup/health_check 钩子异常被静默吞掉 |
| 52 | `infra/http_pool.py:56-58` | 代码缺陷 | 访问 httpx 私有属性 `_is_closed`，版本升级可能失效 |
| 53 | `infra/concurrency.py:51-55` | 逻辑缺陷 | stagger 基于索引而非实际启动时间，错开效果可能不明显 |
| 54 | `infra/concurrency_groups.py:85-86` | 代码缺陷 | 访问 Semaphore 私有 `_value` 属性 |
| 55 | `infra/gpu.py:40-44` | 代码缺陷 | 每次调用创建新 Config 实例，频繁调用时开销大 |
| 56 | `infra/ffmpeg.py:38-46` | 代码缺陷 | `**opts` 无验证，可能生成无效 ffmpeg 命令 |
| 57 | `infra/toolcheck.py:38` | 逻辑缺陷 | HTTP 401/403 被视为"可达"，应区分"在线"和"可用" |
| 58 | `infra/file_watcher.py:93-96` | 逻辑缺陷 | 两个线程同时调用 `start_file_watcher` 可能创建两个 observer |
| 59 | `infra/file_watcher.py:72-79` | 功能缺陷 | `ModelRegistry.reload(ModelRegistry())` 创建不必要的新实例 |
| 60 | `infra/file_watcher.py:93-96` | 功能缺陷 | 只监控 characters/scenes 目录，project.yaml 等变化不触发失效 |
| 61 | `infra/database/schema.py:25` | 逻辑缺陷 | shots 表无 `updated_at` 列，无法追踪修改时间 |
| 62 | `infra/database/pool.py:37-43` | 逻辑缺陷 | 连接归还不检查实际可用性（DB 可能已重启） |
| 63 | `infra/database/_db.py:27-37` | 逻辑缺陷 | `_get_project` mtime 检查在锁外，可能短暂使用过期值 |
| 64 | `infra/safe_executor.py:119-136` | 代码缺陷 | `safe_map` 不透传重试/超时参数 |
| 65 | `infra/concurrency.py:45-48` | 代码缺陷 | `on_progress` 回调在锁内执行，耗时长会阻塞其他任务 |

### api 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 66 | `api/__init__.py:33-47` | 逻辑缺陷 | `_ensure_registered()` 注册表加载失败仅 warning 不 raise |
| 67 | `api/registry.py:93-100` | 逻辑缺陷 | `_TYPE_KEY` 类变量缓存不会随 YAML 热重载更新 |
| 68 | `api/registry.py:106-120` | 逻辑缺陷 | `Container.get()` 锁内执行 `ModelRegistry()` 检查，可能阻塞 |
| 69 | `api/registry.py:140-150` | 逻辑缺陷 | `get_with_fallback()` 全部不可用时返回已缓存的不健康实例 |
| 70 | `api/registry.py:216-241` | 逻辑缺陷 | `reload()` 锁外执行 shutdown + create，两线程并发可能使用旧实例 |
| 71 | `api/backends/tts/fish_speech.py:25` | 功能缺陷 | `synthesize()` 忽略 emotion/language 参数，无 warning |
| 72 | `api/backends/tts/gpt_sovits.py:35` | 功能缺陷 | `synthesize()` 忽略 emotion 参数 |
| 73 | `api/backends/lipsync/musetalk.py:42-46` | 逻辑缺陷 | 文件字段名硬编码，不同部署版本可能不兼容 |
| 74 | `api/backends/image/comfyui.py:104-106` | 逻辑缺陷 | `_extract_error()` 可能抛异常导致原始错误丢失 |
| 75 | `api/backends/image/comfyui.py:143-158` | 功能缺陷 | 输出文件串行下载，批量生成时效率低 |
| 76 | `api/backends/video/animatediff.py:33-38` | 逻辑缺陷 | ComfyUI 构造参数 `timeout` 与实际读取的 `timeouts` key 不匹配 |
| 77 | `api/backends/llm/ollama.py:69-79` | 功能缺陷 | `chat()` 不支持 assistant 消息（few-shot 不可用） |
| 78 | `api/backends/music/musicgen.py:44-47` | 逻辑缺陷 | `config.get("music", {})` 与 Container 扁平化策略不一致 |
| 79 | `api/backends/music/template.py:28-32` | 功能缺陷 | ffmpeg 超时 30s 可能不够，duration 无上限 |
| 80 | `api/backends/seko/proposal.py:85-95` | 逻辑缺陷 | API 错误 code=500 应重试而非终止 |
| 81 | `api/backends/training/ai_toolkit.py:218-226` | 逻辑缺陷 | 文件句柄在异常时可能泄漏 |
| 82 | `api/backends/training/ai_toolkit.py:328-360` | 逻辑缺陷 | 从日志提取 safetensors 路径可能匹配到中间 checkpoint |

### web 层

| # | 文件:行号 | 类型 | 描述 |
|---|-----------|------|------|
| 83 | `web/routers/storyboard.py:55-66` | 逻辑缺陷 | 每次 API 调用都扫描文件系统判断镜头完成状态，性能差 |
| 84 | `web/routers/storyboard.py:152-160` | 逻辑缺陷 | `batch_delete` 不检查 shot_id 是否属于当前 episode，可能误删 |
| 85 | `web/routers/imports.py:112-131` | 逻辑缺陷 | Seko 导入回滚删除项目时缓存状态不一致 |
| 86 | `web/routers/deps.py:160-166` | 逻辑缺陷 | `yaml_save()` 中 entity_key 嵌套可能导致数据丢失 |
| 87 | `web/schemas/__init__.py:多处` | 逻辑缺陷 | `min_length=1` 在可选字段上导致传空字符串报错 |

---

## P2 — 优化（代码质量、可读性、性能）

| # | 文件 | 描述 |
|---|------|------|
| 88 | `infra/config.py:143,169` | 函数内重复 `import yaml`，模块顶层已有 |
| 89 | `infra/config.py:336-346` | `_do_reload` 中 `_cache.pop()` 冗余，`load_config` 自然处理 |
| 90 | `infra/constants.py:68-76` | `contains_non_ascii` 和 `is_ascii_only` 互为补集，用 `text.isascii()` 替代 |
| 91 | `infra/models.py:36-41,61-66` | `validate_id` 重复实现，应提取为共享函数 |
| 92 | `infra/watchdog.py:173-185` | `get_or_check_full` 与 `get_or_check` 异常处理策略不一致 |
| 93 | `infra/json_parse.py:127-132` | `ast.literal_eval` 可能接受非 JSON 结构（Python tuple/set） |
| 94 | `infra/batch_processor.py:29-31` | `estimate_tokens` 对英文严重高估（len//2 vs 实际 ~4 字符/token） |
| 95 | `infra/asset_tracker.py:20` | MD5 哈希，建议改 blake2b 或更长前缀 |
| 96 | `infra/database/__init__.py:2` | 导出 `_reset_project_cache` 下划线前缀私有函数 |
| 97 | `infra/database/generation.py:10-16` | `StatusRecord` dataclass 定义但从未使用 |
| 98 | `infra/database/storyboard_db.py:86,123` | 函数内多次 `import math` |
| 99 | `engines/prompt_compiler.py:33-36` | `get_compiler()` 单例无线程锁保护 |
| 100 | `engines/prompt_compiler.py:104-107` | `${}` 和 `{{}}` 两套语法增加不必要复杂度 |
| 101 | `engines/shot_utils.py:41-43` | 引号清理只处理英文引号，缺中文引号 |
| 102 | `engines/workflow_builder.py:137-156` | `_apply_gpu` 每次构建 `_sampler_types` 集合 |
| 103 | `engines/workflow_builder.py:175-191` | 最小 64px 分辨率可能太小，建议 256+ |
| 104 | `engines/workflow_inject.py:82-87` | suffix 用 `random.randint` 理论可能碰撞 |
| 105 | `engines/portrait.py:15-22` | `_generating` dict 多进程环境不起作用 |
| 106 | `pipeline/celery_app.py:41-51` | `format_task_error` 定义但从未使用 |
| 107 | `pipeline/tasks/__init__.py:37` | `_download_seko_image` 内部函数不应出现在 `__all__` |
| 108 | `pipeline/tasks/pipeline.py:78` | 条件表达式赋值 logger 方法可读性差 |
| 109 | `pipeline/tasks/steps.py:12-19` | `FirstFrameParams` dataclass 放在 import 块中间 |
| 110 | `pipeline/tasks/ai.py:220-222` | `MAX_SHOTS_FOR_EDIT` 定义在函数之后 |
| 111 | `pipeline/tasks/seko.py:10` | `import yaml` 未使用 |
| 112 | `pipeline/tasks/helpers.py:84-85` | `_load_shots` 的 `config_path` 参数从未使用 |
| 113 | `pipeline/tasks/helpers.py:252` | `_db_record_step` 静默吞异常，建议 `logger.warning` |
| 114 | `pipeline/preview.py:28-31` | 每次 `run_preview` 创建新 Config + Container |
| 115 | `pipeline/portraits.py:33-36` | Container 失败后 N 条相同 warning |
| 116 | `post/effects.py:全文件` | 整个模块只有 8 行函数，且从未被调用（死代码） |
| 117 | `post/distributor.py:31-35` | `get_platform_presets` 函数属性缓存永不过期 |
| 118 | `post/distributor.py:50-53` | ffprobe 逻辑重复实现，应抽取为共享工具 |
| 119 | `post/__init__.py` | 空文件，无 `__all__` 定义 |
| 120 | `api/__init__.py:49-52` | `get_container` 每次 import Container |
| 121 | `api/registry.py:119-120` | `except: pass` 中 `pass` 多余 |
| 122 | `api/registry.py:173-180` | `_resolve` 不做 name normalize（连字符 vs 下划线） |
| 123 | `api/backends/tts/_mimo_common.py:20-33` | WAV fmt chunk cbSize 值缺注释 |
| 124 | `api/backends/llm/ollama.py:51-63` | `context_length` 查询失败不设置 `_ctx`，重复查询 |
| 125 | `api/backends/llm/ollama.py:65-68` | `num_predict` 与 `max_tokens` 语义不完全一致 |
| 126 | `api/backends/seko/proposal.py:32-42` | 每个请求创建/销毁 httpx 连接 |
| 127 | `api/backends/training/ai_toolkit.py:228-238` | MIME type 硬编码 `image/png` |
| 128 | `api/backends/training/ai_toolkit.py:307-320` | 状态字符串比较未 `.lower()` |
| 129 | `web/app.py:35` | 根路径挂载静态文件，未匹配路径返回 index.html 而非 404 |
| 130 | `web/routers/deps.py:25-31` | `_cfg()` 每次调用都重新加载 YAML |
| 131 | `web/routers/deps.py:85-88` | `_safe_path` URL 解码可能破坏含 `%` 的文件名 |
| 132 | `web/static/index.html` | 文件末尾无换行符 |

---

## 统计

| 严重程度 | 数量 | 说明 |
|----------|------|------|
| **P0** | 6 | 运行时必崩或逻辑严重错误 |
| **P1** | 81 | 潜在错误、性能问题、逻辑隐患 |
| **P2** | 45 | 代码质量、可读性、性能优化 |
| **合计** | **132** | |

## 按模块分布

| 模块 | P0 | P1 | P2 | 合计 |
|------|----|----|----|----|
| engines | 1 | 25 | 10 | 36 |
| pipeline | 2 | 10 | 11 | 23 |
| infra | 2 | 18 | 13 | 33 |
| api | 0 | 17 | 10 | 27 |
| post | 1 | 7 | 4 | 12 |
| web | 0 | 5 | 4 | 9 |
| **合计** | **6** | **82** | **52** | **140** |
