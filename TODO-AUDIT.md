# TODO — 代码审查问题清单

> 审查日期: 2026-06-04
> 审查范围: infra/config, database, engines, pipeline, web, api, cli 全栈

---

## 🔴 高严重性

### 1. ~~shot_task 使用排队时的旧数据~~ ✅ 已修复
- **类型**: 功能
- **文件**: `pipeline/tasks/pipeline.py` — `_shot_task_inner`
- **修复**: 在 `_shot_task_inner` 开始时从 DB 读取最新 shot 数据，覆盖 Celery 参数中的旧数据。
- **问题**: `shot_task` 从 Celery 参数获取 `shot_data`，但用户可能在任务排队期间修改了分镜，导致任务使用过时数据。
- **影响**: 所有异步管线任务
- **修复**: 在 `_prepare` 中强制从 DB 读取最新 shot，忽略传入参数；或在 `shot_task` 开始时从 DB 重新读取。

### 2. ~~_build_ctx 多线程竞态~~ ✅ 已修复
- **类型**: 逻辑
- **文件**: `pipeline/tasks/helpers.py` — `_build_ctx`
- **修复**: 完善 double-checked locking：第二次加锁后比较 `_mtimes` 而非再次触发重载，避免重复创建实例。
- **问题**: Config 热重载时，两个线程可能同时进入慢路径，各自创建不同的 Config/Container。释放锁后创建对象再加锁写入的模式存在间隙。
- **影响**: 多线程 Celery worker（`--pool=threads`）配置热重载时的竞态
- **修复**: 将 Config + Container 创建放在锁内，或使用完整的 double-checked locking。

### 3. ~~ensure_portrait 重入 + 间接递归~~ ✅ 已修复
- **类型**: 逻辑
- **文件**: `engines/portrait.py` / `engines/workflow_builder.py`
- **修复**: 在 `WorkflowBuilderConfig` 添加 `no_auto_gen` 标志。`ensure_portrait` 创建 WorkflowBuilder 时设置 `no_auto_gen=True`，`_get_character_refs` 在此标志下跳过自动定妆照生成，彻底切断递归链。
- **问题**: `_get_character_refs` → `ensure_portrait` → `build_first_frame` → `_get_character_refs` 形成间接递归。`_generating` 锁防止了直接重入，但并发场景下第二个线程会跳过返回空，导致定妆照不完整。
- **影响**: 定妆照自动生成，首次运行时可能不完整
- **修复**: 在 `build_first_frame` 中传入 `disable_portrait_auto_gen=True` 标志位，或在 `shot_task` 开始时预先确保定妆照就绪。

### 4. ~~Config._check_reload 锁内耗时操作~~ ✅ 已修复
- **类型**: 逻辑
- **文件**: `infra/config.py` — `Config._check_reload`
- **修复**: 将 `_do_reload()` 调用移到 `_reload_lock` 外执行。锁内仅做 `_reloading` 标记的双重检查，耗时的 merge+validate 不再阻塞其他线程。
- **问题**: `_do_reload` 在 `_reload_lock` 内调用 `ModelRegistry()` 和 `load_config()`，可能耗时较长，阻塞其他线程的 `Config.get()` 调用。
- **影响**: 高并发场景下的性能抖动
- **修复**: 将耗时操作移到锁外执行，只在更新 `self._data` 时加锁（copy-on-write）。

### 5. ~~_get_character_refs 并发无缓存~~ ✅ 已修复
- **类型**: 逻辑
- **文件**: `engines/workflow_builder.py` — `_get_character_refs`
- **修复**: 添加实例级 `_refs_cache` 字典。同一 WorkflowBuilder 内对相同 `char_id:outfit` 的重复查找直接返回缓存结果，避免并发场景下重复触发 ensure_portrait。
- **问题**: 两个并发 shot 处理同一角色时，都触发 `_get_character_refs` → `ensure_portrait`，第二个会因 `_generating` 锁跳过返回空，导致缺少参考图。
- **影响**: 并发处理多镜头时部分镜头缺少角色一致性参考图
- **修复**: 在 `_get_character_refs` 中添加实例级缓存，或在 `shot_task` 开始时预先确保定妆照。

---

## 🟡 中严重性

### 6. batch_translate_to_english 空批次崩溃
- **类型**: 功能
- **文件**: `engines/prompt.py` — `_merge_translate_results`
- **问题**: `batch_data` 为 None 时，`len(batch_data)` 抛出 TypeError。
- **影响**: 批量翻译中某批次完全失败时崩溃
- **修复**: 添加 None 检查，从 `batch_result` 额外记录每批大小。

### 7. _apply_preset resolution 格式校验缺失
- **类型**: 逻辑
- **文件**: `pipeline/tasks/pipeline.py` — `_apply_preset`
- **问题**: `base_res` 可能是 `[1024]`（单元素列表），`base_res[1]` 会 IndexError。
- **影响**: preset=high 且 generation.resolution 配置不完整时崩溃
- **修复**: 添加 `if not isinstance(base_res, list) or len(base_res) != 2: return config_path`

### 8. project_scope 非线程安全
- **类型**: 逻辑
- **文件**: `infra/database/_db.py` — `project_scope`
- **问题**: 全局 `_project_cache` 在多线程环境下被并发修改。线程 A 设置为 "project_a"，线程 B 立即覆盖为 "project_b"，导致 A 的 DB 操作写入错误项目。
- **影响**: 多线程并发项目切换时 DB 写入错误项目
- **修复**: 使用 `threading.local()` 存储每个线程的 project 上下文。

### 9. _reset_proj_cache 直接修改其他模块全局变量
- **类型**: 功能
- **文件**: `web/routers/deps.py` — `_reset_proj_cache`
- **问题**: 直接 import 并修改 `pipeline.tasks.helpers._ctx_cache`，可能触发意外的模块导入副作用。
- **影响**: 项目切换时的脆弱性
- **修复**: 使用信号/事件机制或版本号检查。

### 10. 五视图右侧视图使用左侧 prompt
- **类型**: 逻辑
- **文件**: `engines/portrait.py` — `_generate_five_views` / `get_view_appearance`
- **问题**: `_FIVE_VIEWS` 中 `right_side` 的 `shot_type` 是 "侧面特写"，`get_view_appearance` 中 "侧面" 映射到 `left_side`，导致右侧视图使用了左侧 prompt。
- **影响**: 五视图生成，右侧视图与左侧视图 prompt 相同
- **修复**: 在 `_generate_view` 中直接使用 `build_view_prompt(base_en, body_features, p.view_key)` 而不是 `get_view_appearance`。

### 11. 参考图上传失败不阻止工作流
- **类型**: 功能
- **文件**: `pipeline/tasks/steps.py` — `_upload_reference_images`
- **问题**: 上传失败只记录 warning，不阻止工作流执行。ComfyUI 使用不存在的文件名可能报错或生成质量差。
- **影响**: 首帧生成质量
- **修复**: 上传失败时抛出异常或返回错误状态。

### 12. Container.reload 锁内耗时操作
- **类型**: 逻辑
- **文件**: `api/registry.py` — `Container.reload`
- **问题**: `inst.shutdown()` 和 `registry.create()` 在 `_lock` 内执行，阻塞其他线程的 `get()` 调用。
- **影响**: 配置热重载时的服务中断
- **修复**: 将 shutdown + create 移到锁外执行。

### 13. append_storyboard episode=0 逻辑错误
- **类型**: 逻辑
- **文件**: `engines/storyboard.py` — `append_storyboard`
- **问题**: `episode = episode or int(...)` 中，episode=0 是 falsy，会回退到 shot 中的 episode。
- **影响**: 追加分镜时 episode=0 行为不符合预期
- **修复**: 改为 `episode = episode if episode is not None else int(...)`

### 14. save_storyboard episode 类型不一致
- **类型**: 功能
- **文件**: `web/routers/storyboard.py` — `save_storyboard`
- **问题**: `shot["episode"] = str(episode)` 将 int 转为 str，但 DB schema 中 episode 是 INTEGER。
- **影响**: 类型混淆的潜在风险
- **修复**: 统一 episode 类型为 int。

---

## 🟢 低严重性

### 15. _inject_consistency_method 命名不一致
- **类型**: 代码
- **文件**: `engines/workflow_builder.py`
- **问题**: `_INJECT_DISPATCH` 中 `"_inject_ip_adapter_plus"` 映射到 `_inject_character_refs`，命名误导。
- **修复**: 改 key 为 `"inject_character_refs"` 或使用函数引用。

### 16. Config._merge 静默吞掉所有异常
- **类型**: 代码
- **文件**: `infra/config.py`
- **问题**: `except Exception` 可能掩盖配置格式错误等真正问题。
- **修复**: 缩小异常捕获范围，或记录更详细日志。

### 17. _truncate_tag_prompt 中文 token 估算不准
- **类型**: 代码
- **文件**: `engines/prompt.py`
- **问题**: `len(prompt) / 4` 对中文严重不准确。
- **修复**: 添加注释说明仅适用于英文 tag。

### 18. _is_default_storyboard 只检查前 5 个镜头
- **类型**: 逻辑
- **文件**: `pipeline/tasks/helpers.py`
- **问题**: 可能误判或漏判默认分镜。
- **修复**: 改为检查交集比例。

### 19. _tool_executor 全局线程池未清理
- **类型**: 代码
- **文件**: `web/routers/system_tools.py`
- **问题**: 模块级 ThreadPoolExecutor 不会在应用关闭时自动清理。
- **修复**: 在 `_lifespan` shutdown 阶段调用 `_tool_executor.shutdown(wait=False)`。

### 20. Container._resolve 静默回退
- **类型**: 逻辑
- **文件**: `api/registry.py`
- **问题**: 配置的后端名不是已注册 API 后端时，静默回退到 auto_select，可能选择非预期后端。
- **修复**: 在回退时记录 warning 日志。

### 21. _check_lora_availability 检查结果不阻断
- **类型**: 代码
- **文件**: `pipeline/tasks/steps.py`
- **问题**: 检查结果只记录 warning，不阻止工作流。
- **修复**: 将结果返回给调用方。

### 22. _ensure_redis 参数被忽略
- **类型**: 代码
- **文件**: `cli/__init__.py`
- **问题**: 函数参数 `port_ok` 和 `redis_port` 被忽略，内部重新 import。
- **修复**: 删除参数或删除内部 import。

### 23. init_schema 使用 split(";") 分割 SQL
- **类型**: 代码
- **文件**: `infra/database/schema.py`
- **问题**: 如果 SQL 中包含分号，分割会产生无效语句。
- **修复**: 逐条执行已知 CREATE 语句。

### 24. _clean_empty_values 循环次数硬编码
- **类型**: 代码
- **文件**: `engines/prompt_compiler.py`
- **问题**: 3 次循环可能不够覆盖所有嵌套情况。
- **修复**: 改为 `while changed` 循环。

### 25. upload_entity_image ext 未用检测结果
- **类型**: 代码
- **文件**: `web/routers/assets.py`
- **问题**: 保存文件名使用原始 ext 而不是 magic bytes 检测到的 ext。
- **修复**: 使用检测到的 ext。
