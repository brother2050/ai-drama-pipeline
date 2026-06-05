# TODO

> 从 REVIEW.md 交叉验证后筛选出的有效问题。已修复/误判/设计意图的已剔除。

---

## P1 — 建议修（潜在错误、逻辑隐患）

| # | 文件 | 描述 |
|---|------|------|
| 7 | `engines/storyboard.py` | `append_storyboard` 中 `int("")` 静默跳过，用户无感知丢弃镜头 |
| 12 | `engines/llm_generator.py` | `_generate_entities` 不检查空 dict `{}`，空结果被当作成功 |
| 14 | `engines/shot_calibrator.py` | shot_id 有误时（"001" vs "1"）错误按索引匹配，字段写入错误镜头 |
| 17 | `engines/shot_utils.py` | `postprocess_shots` 去重和格式校验是 OR 关系，合法 sid 可能被覆盖 |
| 20 | `engines/workflow_builder.py` | 未知图像后端回退到空工作流，静默返回无输出 |
| 22 | `engines/workflow_builder.py` | `_setup_img2img` 文件名在上传前设置，ComfyUI 可能找不到文件 |
| 24 | `engines/workflow.py` | `set_clip_text_prompts` 将所有非 negative CLIPTextEncode 都设为 positive，第三节点被覆盖 |
| 26 | `engines/workflow_inject.py` | `inject_pulid_flux` 第一个角色无参考图时跳过所有后续角色 |
| 27 | `engines/workflow_inject.py` | LoRA 注入后 clip 连接未更新，绕过了 LoRA 对 CLIP 的微调 |
| 32 | `pipeline/tasks/pipeline.py` | 原地修改 `shot_data["duration"]`，共享 dict 被污染 |
| 34 | `pipeline/tasks/steps.py` | `tts_core` 中 `characters=None` 时每次都重建 ShotManager，批量处理时重复 IO |
| 35 | `pipeline/tasks/ai.py` | `_ai_prepare_inner` 两次加载 storyboard，中间被修改会导致回写错误数据 |
| 36 | `pipeline/tasks/ai.py` | `warnings` 用 `=` 赋值而非 `extend()`，前序 warnings 丢失 |
| 37 | `pipeline/tasks/portrait_tasks.py` | `outfits_batch_task` 未绑定 project_scope，DB 写入可能指向错误项目 |
| 44 | `post/subtitle.py` | `transition_duration > duration` 时字幕时间重叠为 0 |
| 45 | `post/music.py` | 每次 `generate()` 都创建新 Container，开销大 |
| 50 | `infra/watchdog.py` | 超时仅标记不中断，`except TimeoutError` 永不触发 |
| 61 | `infra/database/schema.py` | shots 表无 `updated_at` 列，无法追踪修改时间 |
| 62 | `infra/database/pool.py` | 连接归还不检查实际可用性（DB 可能已重启） |
| 66 | `api/__init__.py` | `_ensure_registered()` 注册表加载失败仅 warning 不 raise |
| 67 | `api/registry.py` | `_TYPE_KEY` 类变量缓存不会随 YAML 热重载更新 |
| 69 | `api/registry.py` | `get_with_fallback()` 全部不可用时返回已缓存的不健康实例 |
| 73 | `api/backends/lipsync/musetalk.py` | 文件字段名硬编码，不同部署版本可能不兼容 |
| 74 | `api/backends/image/comfyui.py` | `_extract_error()` 可能抛异常导致原始错误丢失 |
| 76 | `api/backends/video/animatediff.py` | ComfyUI 构造参数 `timeout` 与实际读取的 `timeouts` key 不匹配 |
| 80 | `api/backends/seko/proposal.py` | API 错误 code=500 应重试而非终止 |
| 81 | `api/backends/training/ai_toolkit.py` | 文件句柄在异常时可能泄漏 |
| 82 | `api/backends/training/ai_toolkit.py` | 从日志提取 safetensors 路径可能匹配到中间 checkpoint |
| 84 | `web/routers/storyboard.py` | `batch_delete` 不检查 shot_id 是否属于当前 episode，可能误删 |
| 86 | `web/routers/deps.py` | `yaml_save()` 中 entity_key 嵌套可能导致数据丢失 |
| 87 | `web/schemas/__init__.py` | `min_length=1` 在可选字段上导致传空字符串报错 |

## P2 — 优化（代码质量、可读性）

| # | 文件 | 描述 |
|---|------|------|
| 93 | `infra/json_parse.py` | `ast.literal_eval` 可能接受非 JSON 结构（Python tuple/set） |
| 94 | `infra/batch_processor.py` | `estimate_tokens` 对英文高估（len//4 是合理近似，但可优化） |
| 101 | `engines/shot_utils.py` | 引号清理只处理英文引号，缺中文引号 |
| 102 | `engines/workflow_builder.py` | `_apply_gpu` 每次构建 `_sampler_types` 集合 |
| 104 | `engines/workflow_inject.py` | suffix 用 `random.randint` 理论可能碰撞 |
| 113 | `pipeline/tasks/helpers.py` | `_db_record_step` 静默吞异常，建议 `logger.warning` |
| 118 | `post/distributor.py` | ffprobe 逻辑重复实现，应抽取为共享工具 |
| 128 | `api/backends/training/ai_toolkit.py` | 状态字符串比较未 `.lower()` |
| 131 | `web/routers/deps.py` | `_safe_path` URL 解码可能破坏含 `%` 的文件名 |

---

## 已修复

| 原编号 | 文件 | 修复 commit |
|--------|------|-------------|
| P0 #2 | `pipeline/tasks/training_tasks.py` | `3529965` — `_ROOT` 改为参数传递 |
| P0 #3 | `post/vertical.py` | `3529965` — 人脸裁剪使用 cy 垂直居中 |
| P1 #33 | `pipeline/tasks/pipeline.py` | `3529965` — `.apply()` → `.apply_async()` |
| P1 #30 | `infra/models.py` | `0abd4d0` — `normalize_character` 浅拷贝 |
| — | `engines/llm_generator.py` | `24793fe` — 已有实体上下文注入 |
