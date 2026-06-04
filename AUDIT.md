# 🔍 AI 短剧管线 v2 — 全项目深度审查报告

> 审查时间：2026-06-04
> 审查范围：全量 170 文件、24,106 行代码
> 审查维度：功能缺陷、逻辑缺陷、代码缺陷、架构设计、代码质量、优化之道符合度
> 前提：面向新用户、不兼容旧数据、个人使用不管安全

---

## 一、真实运行时崩溃（P0 — 必修）

### BUG-01: `produce_task` 质量门禁写入 list 用 str key
**文件**: `pipeline/tasks/pipeline.py:226`
```python
results = _iterate_shots(...)  # results 是 list
results["quality_issues"] = issues  # TypeError: list indices must be integers, not str
```
**影响**: 运行时必崩，produce 任务失败。
**修复**: 改为 `return {"status": STATUS_DONE, "episode": episode, "shots": results, "quality_issues": issues}`

---

### BUG-02: `post/vertical.py` blur_bg 模式前景缩放错误
**文件**: `post/vertical.py:97-100`
```python
vf = (f"split[original][blur];[blur]scale={target_w}:{target_h},boxblur=20[bg];"
      f"[original]scale={target_w}:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
```
**问题**:
1. 前景 `scale={target_w}:-1` 按宽度 1080 等比缩放，高度远小于 1920，overlay 后顶部/底部出现大面积模糊黑边
2. `scale=-1` 在某些 ffmpeg 版本中可能被拒绝（要求偶数尺寸）
**修复**: 前景应按 `scale=-1:{target_h}` 按高度缩放，或用 `force_original_aspect_ratio=decrease` + 居中。

---

### BUG-03: `infra/safe_executor.py` 超时后后台线程无法取消
**文件**: `infra/safe_executor.py:54-61`
```python
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as te:
    future = te.submit(fn, *args, **kwargs)
    return future.result(timeout=timeout)
```
**问题**: `future.result(timeout)` 超时后抛 `TimeoutError`，但 `fn` 在后台线程中继续运行直到自然结束。ComfyUI 生成任务可能耗时 10 分钟+，超时后线程泄漏。
**修复**: 引入 `threading.Event` 作为取消标志，传入 `fn` 内部检查。Python 无法强制终止线程，只能协作取消。

---

## 二、逻辑缺陷（P0/P1 — 会导致静默错误或数据污染）

### LOGIC-01: `normalize_character` 就地修改输入 dict
**文件**: `infra/models.py:196-220`
```python
def normalize_character(char: dict) -> dict:
    char["bible"] = ...        # 就地修改
    char["reference_images"] = [...]  # 就地修改
    char["outfits"] = {...}    # 就地修改
```
**影响**: 调用方的引用被污染。LLM 返回的原始 dict 被多处引用时，normalize 后所有引用都变了。
**修复**: 函数入口 `char = dict(char)` 浅拷贝，outfits 等子 dict 需要 `copy.deepcopy`。
**严重程度**: P1

---

### LOGIC-02: `_truncate_tag_prompt` token/字符单位混用
**文件**: `engines/prompt.py:178-180`
```python
est_tokens = len(prompt) / 4
tag_cost = len(tag) / 4 + 1
if char_count + tag_cost > max_tokens * 4:  # max_tokens=75, 75*4=300 字符
```
**问题**: `max_tokens * 4` 把 token 限制换算成字符限制，逻辑方向对但常数不精确。SD1.5 CLIP 的 75 token 限制约对应 300-375 英文字符。
**影响**: 轻微，截断阈值约 4 倍宽松，但实际 prompt 很少超长。
**严重程度**: P2

---

### LOGIC-03: `strip_dialogue` 中文动词列表不全
**文件**: `engines/shot_utils.py:56-78`
```python
_VERB = r'[说喊道问答呼吼叫骂叹叫嚷]'
```
**缺失**: 讲、念、嘟囔、嘀咕、唠叨、念叨、絮叨、嚷嚷、吼叫、咆哮、嘶吼、低语、呢喃、喃喃、自言自语 等。
**影响**: 遗漏的动词频率较低，但高频的"讲""念"应补充。
**严重程度**: P2

---

### LOGIC-04: `inject_lora` 后 clip 连接未更新
**文件**: `engines/workflow_inject.py:259-273`
```python
wf[lora_node_id] = {
    "inputs": {
        "clip": [clip_source, clip_output_idx] if clip_source else [model_source, 0],
    }
}
wf[ksampler]["inputs"]["model"] = [lora_node_id, 0]
# ❌ KSampler.clip 未更新，仍直连原始 clip_source
```
**影响**: LoRA 对 CLIP 的微调被绕过。KSampler 的 `clip` 输入仍直连原始 CLIP 加载器，而非通过 LoRA 节点。LoRA 的文本编码微调不生效。
**修复**: 添加 `wf[ksampler]["inputs"]["clip"] = [lora_node_id, 1]`
**严重程度**: P0

---

### LOGIC-05: `inject_pulid_flux` 第一个角色无参考图时跳过所有后续角色
**文件**: `engines/workflow_inject.py:181-215`
```python
primary_refs = builder._get_character_refs(char_ids[0], ...) if char_ids else []
if not primary_refs:
    logger.warning(...)
    return wf  # ❌ 直接返回，跳过 char_ids[1:]
```
**影响**: 多角色场景中，如果主角色无定妆照，所有次要角色的一致性注入也被跳过。
**修复**: 改为 `continue` 处理后续角色。
**严重程度**: P0

---

### LOGIC-06: `_enrich_stage` 50% 阈值硬编码
**文件**: `engines/shot_calibrator.py:100-108`
```python
if missing > len(merged) * 0.5:
    logger.warning(...)
    return None
```
**问题**: 49% 镜头缺少必填字段仍视为成功。阈值不可配置。
**修复**: 改为可配置阈值或更严格的检查（如 100% 必填）。
**严重程度**: P2

---

### LOGIC-07: `workflow.py:resolve_node_aliases` 用 `pop()` 直接修改传入 dict
**文件**: `engines/workflow.py:16-21`
```python
def resolve_node_aliases(workflow: dict, available_nodes: set[str]) -> dict:
    aliases = workflow.pop("_node_aliases", {})  # 破坏性操作
```
**问题**: 函数签名暗示非破坏性，但 `pop()` 会删除 `_node_aliases` 键。当前代码中每次 `copy.deepcopy` 后调用所以不会触发，但设计脆弱。
**修复**: 改为 `workflow.get("_node_aliases", {})` + 手动删除。
**严重程度**: P2

---

### LOGIC-08: `generate_multi_char_prompt` token 估算与 `estimate_tokens` 不一致
**文件**: `engines/multi_char.py:31-35`
```python
est_tokens = len(prompt) // 4  # 约 4 字符/token
```
**对比**: `infra/batch_processor.py:estimate_tokens` 用 `len(text) // 2`（约 2 字符/token）。
**影响**: 多人 prompt 的 token 估算比批处理器宽松 2 倍，可能导致警告阈值不准。
**严重程度**: P2

---

### LOGIC-09: `inject_ip_adapter_chain` 函数签名混乱
**文件**: `engines/workflow_inject.py`
```python
def inject_ip_adapter_chain(builder: object, wf: dict, char_id: str, ...)
```
文档注释说第一个参数是 `builder`，但函数名和调用模式暗示应以 `wf` 为第一参数。
**影响**: 可读性差，新开发者容易传错参数。
**严重程度**: P2

---

## 三、死代码与残余（P2）

### DEAD-01: `post/effects.py` — 整个模块从未被调用
```python
def build_color_grade_filter(params: dict) -> str | None:
    """构建调色过滤器"""
```
整个文件只有这一个函数，搜索全项目无任何调用点。
**判定**: ✅ 死代码，应删除。

### DEAD-02: `pipeline/celery_app.py:format_task_error` 从未使用
```python
def format_task_error(exc, task_id, ...):  # 定义但从未调用
```
**判定**: ✅ 死代码。

### DEAD-03: `infra/database/generation.py:StatusRecord` dataclass 从未使用
```python
@dataclass
class StatusRecord:
    ...
```
**判定**: ✅ 死代码。

### DEAD-04: `pipeline/tasks/__init__.py` 导出 `_download_seko_image` 内部函数
```python
__all__ = [..., "_download_seko_image"]
```
以下划线开头的内部函数不应出现在 `__all__` 中。
**判定**: ⚠️ 代码质量问题。

### DEAD-05: `infra/constants.py:contains_non_ascii` 和 `is_ascii_only` 互为补集
```python
def contains_non_ascii(text: str) -> bool:
    return not text.isascii()

def is_ascii_only(text: str) -> bool:
    return text.isascii()
```
两个函数完全等价（`contains_non_ascii(x) == not is_ascii_only(x)`）。应只保留 `is_ascii_only`。
**判定**: ⚠️ 冗余代码。

---

## 四、重复功能 / 重复代码（P2）

### DUP-01: 角色/场景加载逻辑重复 4 处
| 位置 | 代码 |
|------|------|
| `engines/shot_manager.py:43-48` | `load_yaml_entities(paths.characters_dir, "character")` |
| `engines/consistency_checker.py` | 同上模式 |
| `engines/quality_gate.py` 多个 `_check_*` | 同上模式 |
| `pipeline/tasks/pipeline.py:_check_portrait_readiness` | 同上模式 |

**修复**: 统一为 `ShotManager` 或 `engines/storyboard.py` 中的共享函数。

### DUP-02: `Container` 重复实例化
| 位置 | 代码 |
|------|------|
| `post/music.py:27-33` | `Container(self._config)` 每次 `generate()` 都新建 |
| `pipeline/preview.py:28-31` | 每次 `run_preview` 创建新 Config + Container |

**修复**: `MusicGenerator` 应注入 Container 或缓存。

### DUP-03: `.env` 加载逻辑重复
- `cli/__init__.py:_load_env()` 手动解析 `.env`
- `infra/config.py` 用 `dotenv.load_dotenv()` 加载 `.env`

**影响**: 两套加载逻辑可能导致环境变量覆盖不一致。

### DUP-04: `validate_id` 重复实现
- `infra/models.py:ImportCharacter.validate_id`
- `web/schemas/__init__.py` 中多个 Schema 的 `validate_id`

两处都有 `re.match(r"^[a-zA-Z0-9_-]+$", v)` 校验。
**修复**: 提取为 `infra/models.py:validate_id()` 共享函数。

### DUP-05: `ffprobe` 逻辑重复
- `infra/ffmpeg.py:probe()` — 标准实现
- `post/distributor.py:get_video_info()` — 重复实现，只多了 size_mb

**修复**: `distributor.py` 应复用 `infra.ffmpeg.probe()`。

---

## 五、架构设计问题（P1/P2）

### ARCH-01: `Container._TYPE_KEY` 类变量缓存不随 YAML 热重载更新
**文件**: `api/registry.py:93-100`
```python
class Container:
    _TYPE_KEY: dict[str, str] = {}  # 类变量，首次加载后永不更新
```
**影响**: 用户在 `models_registry.yaml` 中新增服务类型后，`_TYPE_KEY` 不会更新。
**修复**: ✅ 已确认 `reload()` 中 `Container._TYPE_KEY.clear()` 后，`_get_type_key()` 会从 ModelRegistry 重新构建。无需额外修改。
**严重程度**: P2

### ARCH-02: 两个深度合并函数行为不同
- `deep_merge(base, override)` — 返回新 dict（调用 `copy.deepcopy`）
- `Config._deep_merge_inplace(base, override)` — 就地修改

**影响**: 调用方需要清楚知道用哪个，容易混淆。
**严重程度**: P2

### ARCH-03: 模块级 YAML 加载在 import 时执行
**文件**: `engines/llm_generator.py:27`, `engines/shot_calibrator.py:19-31`
```python
STORYBOARD_SYSTEM = _tpl("storyboard_system")  # 模块加载时执行
```
**影响**: YAML 文件不存在或格式错误时，模块导入就失败（当前有 try/except 兜底为空字符串）。
**修复**: ✅ 已改为惰性加载 — 模块级常量替换为 `_get_xxx_system()` 函数，首次调用时加载并缓存。
**严重程度**: P2

### ARCH-04: `post/music.py` 模板回退方案生成 sine 波当配乐
```python
cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
       f"sine=frequency={freq}:duration={duration}",
       "-af", "volume=0.1,tremolo=f=3:d=0.4", output]
```
**影响**: 用户体验极差（纯正弦波），但只有 `logger.debug` 级别日志。
**修复**: ✅ 已在 2bc636a 中升级为 `logger.warning`，并提示用户安装 MusicGen。
**严重程度**: P2

### ARCH-05: `infra/file_watcher.py` 只监控 characters/scenes 目录
**影响**: `project.yaml`、`system.yaml`、`models_registry.yaml` 等配置文件变化不触发缓存失效。
**修复**: ✅ 已扩展监控范围，添加对 config_dir 本身的监控（包含 project.yaml、system.yaml 等顶层配置文件）。
**严重程度**: P2

---

## 六、代码质量问题（P2）

### QUALITY-01: `infra/http_pool.py` 访问 httpx 私有属性
**文件**: `infra/http_pool.py:56-58` — 已修为 `is_closed` ✅

### QUALITY-02: `infra/concurrency_groups.py` 访问 Semaphore 私有 `_value`
**风险**: Python 版本升级可能失效。
**修复**: 改用 `threading.Semaphore._value` 的公开替代方案或计数器。

### QUALITY-03: `infra/batch_processor.py:estimate_tokens` 对英文高估
```python
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)  # 英文实际约 4 字符/token
```
**影响**: 分批更细，增加 API 调用次数。
**修复**: 区分中英文：中文 `len//1.5`，英文 `len//4`。

### QUALITY-04: `engines/prompt_compiler.py:get_compiler()` 单例无线程锁
```python
_compiler_instance: PromptCompiler | None = None
def get_compiler() -> PromptCompiler:
    global _compiler_instance
    if _compiler_instance is None:
        _compiler_instance = PromptCompiler()
```
**影响**: GIL 保证不会出数据竞争，但可能重复加载 YAML。
**修复**: 加 `threading.Lock()`。

### QUALITY-05: `engines/workflow_builder.py:_apply_gpu` 每次构建 `_sampler_types` 集合
```python
_sampler_types = {"KSampler", "KSamplerAdvanced", "BasicScheduler"}
for svc in ("image", "video"):
    for bname in self.registry.list_backend_names(svc):
        ...
```
**影响**: 每次调用都遍历所有后端。应缓存为类属性。

### QUALITY-06: `web/routers/deps.py:_cfg()` 每次调用都创建新 Config
```python
def _cfg() -> Config:
    return Config(resolve_project_config())
```
**影响**: 每个 API 请求都创建新 Config 对象。Config 内部有 mtime 缓存，但对象创建有开销。
**修复**: 缓存 Config 实例，仅在 mtime 变化时重建。

### QUALITY-07: `infra/gpu.py` 每次调用创建新 Config 实例
**修复**: 缓存 Config 实例。

### QUALITY-08: `infra/database/storyboard_db.py` 函数内多次 `import math`
**文件**: `infra/database/storyboard_db.py:86,123`
**修复**: 移到模块顶层。

### QUALITY-09: `infra/config.py` 函数内重复 `import yaml`
**文件**: `infra/config.py:143,169` — 模块顶层已有 `import yaml`。

---

## 七、优化之道符合度评估

| 维度 | 评分 | 说明 |
|------|------|------|
| **简洁** | ⭐⭐⭐⭐ | 注册表驱动、DI 容器、数据类封装参数 — 整体简洁 |
| **优雅** | ⭐⭐⭐⭐ | WorkflowBuilderConfig、PromptBuildParams、ViewGenParams 消除多参数函数 |
| **可视** | ⭐⭐⭐⭐⭐ | Rich 终端输出、Web SPA、进度反馈完善 |
| **可重用** | ⭐⭐⭐⭐ | engines/ 层可独立使用，infra/ 层通用 |
| **可扩展** | ⭐⭐⭐⭐⭐ | 注册表驱动，新增后端只改 YAML |
| **可用** | ⭐⭐⭐⭐ | CLI + Web 双入口，错误提示友好 |
| **可集成** | ⭐⭐⭐⭐ | FastAPI REST API，Swagger 文档 |
| **可测试** | ⭐⭐⭐ | 143 项测试，但 Celery 任务测试依赖 mock |

---

## 八、优先级排序

| 优先级 | 编号 | 问题 | 影响 |
|--------|------|------|------|
| **P0** | BUG-01 | `results["quality_issues"]` 写入 list | 运行时崩溃 |
| **P0** | LOGIC-04 | LoRA 注入后 clip 未更新 | LoRA 文本微调失效 |
| **P0** | LOGIC-05 | PuLID 第一角色无图跳过全部 | 多角色场景一致性丢失 |
| **P1** | BUG-02 | blur_bg 前景缩放错误 | 横转竖输出质量差 |
| **P1** | BUG-03 | 超时后线程泄漏 | 资源泄漏 |
| **P1** | LOGIC-01 | normalize_character 就地修改 | 数据污染 |
| **P1** | LOGIC-03 | strip_dialogue 动词不全 | 对话残留在 action 中 |
| **P2** | DEAD-01~05 | 死代码 | 代码维护负担 |
| **P2** | DUP-01~05 | 重复代码 | 可维护性差 |
| **P2** | ARCH-01~05 | 架构设计问题 | 健壮性/可维护性 |
| **P2** | QUALITY-01~09 | 代码质量问题 | 性能/健壮性 |

---

## 九、统计

| 严重程度 | 数量 | 说明 |
|----------|------|------|
| **P0** | 3 | 运行时崩溃或核心功能失效 |
| **P1** | 4 | 潜在错误、数据污染、资源泄漏 |
| **P2** | 20+ | 死代码、重复代码、架构/质量问题 |
| **合计** | **27+** | |

## 按模块分布

| 模块 | P0 | P1 | P2 | 合计 |
|------|----|----|----|----|
| pipeline | 1 | 0 | 1 | 2 |
| engines | 2 | 2 | 6 | 10 |
| infra | 0 | 1 | 7 | 8 |
| post | 0 | 1 | 2 | 3 |
| api | 0 | 0 | 1 | 1 |
| web | 0 | 0 | 1 | 1 |
| **合计** | **3** | **4** | **18+** | **25+** |
