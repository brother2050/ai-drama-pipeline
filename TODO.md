# TODO — Web 层质量问题（2026-06-05 审查）

> 按优先级排列，每条标注文件:行号、问题描述、修复建议。

---

## 🔴 高优先级

### 1. 异常处理泄露内部信息
**文件**: `web/app.py:78`
**问题**: 全局异常处理器将 `type(exc).__name__` 和 `str(exc)` 直接返回给客户端，可能暴露文件路径、数据库结构、模块名等。
**修复**: 生产环境只返回通用错误信息，仅 `DEBUG=1` 时返回详情：
```python
debug = os.environ.get("DEBUG", "").lower() in ("1", "true")
detail = f"{type(exc).__name__}: {str(exc)}" if debug else "服务器内部错误"
```

### 2. CORS 默认允许所有来源
**文件**: `web/app.py:70`
**问题**: `CORS_ORIGINS` 默认 `"*"`，任意来源可跨域调用写接口。
**修复**: 默认值改为已知来源，或强制要求部署时配置。

### 3. /config 和 /system/config 无鉴权
**文件**: `web/routers/system_tools.py:73-93`（system config）、`:431-462`（project config）
**问题**: 两个配置端点无任何认证，任何人都可修改系统配置（含 API Key）。`_merged_cfg_public()` 只过滤 `_` 前缀字段，`llm.api_key` 等敏感字段会被返回。
**修复**:
- 添加基于 token 的简单认证中间件
- `_merged_cfg_public()` 额外过滤 `api_key`、`secret`、`token`、`password` 等敏感字段名

### 4. HTTP 方法语义不规范
**文件**: `characters.py`、`scenes.py`、`system_tools.py` 等
**问题**:
- `POST /characters` 同时用于创建和更新（应 `POST` 创建 + `PUT` 更新）
- `POST /config`、`POST /system/config` 是更新操作（应 `PUT` 或 `PATCH`）
- `POST /storyboard/{episode}` 是覆盖式保存（应 `PUT`）
**修复**: 语义化 HTTP 方法。

### 5. 前端大量函数/变量挂载 window 全局作用域
**文件**: `core.js`（33 个 window 赋值）、`characters.js`、`pipeline.js`、`ai-gen.js` 等
**问题**: 超过 80 个函数/变量直接挂 window，易命名冲突。`window.ep`/`window.shots` 通过 `Object.defineProperty` 同步模块变量，但其他模块可直接修改 `window.ep` 导致不同步。
**修复**: 仅通过 `Drama.*` 命名空间暴露必要 API。

---

## 🟡 中优先级

### 6. API 响应格式不一致
**文件**: 多处路由
**问题**:
- `POST /steps/*` → `{"status":"submitted","task_id":"...","poll_url":"..."}` ✓
- `POST /tools/tts` → `{"task_id":"..."}` ✗（缺 status/poll_url）
- `GET /pipeline/status/{episode}` → 直接透传底层原始结果，格式未定义
- 异常时有的返回 `{"detail":"..."}` 有的返回 `{"episodes":[]}` 静默降级
**修复**: 定义统一响应包装格式。

### 7. Schema 校验规则不一致
**文件**: `web/schemas/__init__.py`
**问题**:
- `StepRequest.shot_id`（:52）: `min_length=1`, 正则 `^[a-zA-Z0-9_-]+$`
- `StoryboardShotData.shot_id`（:232）: 允许空字符串，无 min_length
- `CharacterData.id`（:121）: `max_length=50`，`validate_id(allow_chinese=True)` 允许中文
- `ChatEditRequest.message`（:193）: 无 `max_length`，可发送超长文本
**修复**: 提取公共校验器；给 `ChatEditRequest.message` 加 `max_length=10000`。

### 8. 单删 vs 批量删除错误处理不一致
**文件**: `characters.py:24`（单删）vs `:30`（批量）
**问题**: 单个 `DELETE /characters/{id}` 对不存在的 ID 返回 404；批量 `POST /characters/batch-delete` 将不存在的 ID 收集到 `errors` 列表返回 200。行为不同但可接受，需确认是有意设计。
**修复**: 文档化行为差异，或统一为批量中对不存在的 ID 也返回 400。

### 9. 编辑面板动态覆盖 window 函数
**文件**: `characters.js:_editEntityPanel()` (~line 110-230)
**问题**: 每次打开编辑面板都动态创建 `window.save_ecEdit`、`window.ecUploadImg` 等函数。同类型面板会覆盖前一个的函数。虽然 overlay ID 固定（同一时间只能打开一个同类型面板），但模式脆弱。
**修复**: 使用闭包或实例化面板对象管理状态。

### 10. updateShotField 忽略参数，全量同步
**文件**: `ai-gen.js:~line 170`
**问题**: `onchange="updateShotField(this)"` 传入了元素引用，但函数签名 `function updateShotField()` 无参数。内部 `_debouncedSaveSB()` 遍历所有 `.sb-inline-input` 同步到内存。每个字段变化都触发全量同步+保存。
**修复**: 接收变化的元素，只同步该字段到 `shots[idx]`。

### 11. Drama.state 与模块级变量重复
**文件**: `app.js:13-26` vs `core.js:10-18`
**问题**: `Drama.state.batchCancelled` 和模块级 `batchCancelled` 是两个独立变量，未同步。实际代码只用模块级变量。`Drama.lang`（app.js:31）从未被 `setLang()` 更新，是死代码。
**修复**: 删除 `Drama.state` 中重复字段；删除或同步 `Drama.lang`。

### 12. 并行加载模块无错误处理
**文件**: `index.html:31-36`
**问题**: `_modules.forEach(f => { s.onerror = reject; })` — 并行加载时错误被静默吞掉（无 `.catch()`），页面部分初始化导致后续调用未定义函数。
**修复**: 添加 `Promise.allSettled` + 错误日志。

### 13. /training/trigger 用 query params 传业务数据
**文件**: `imports.py:210`
**问题**: `save_training_trigger(char_id: str, trigger: str = "")` — 写操作用 query parameters。
**修复**: 定义 `TrainingTriggerRequest` Pydantic model 作为 request body。

---

## 🟢 低优先级

### 14. i18n 硬编码中文
**文件**: 多处 JS
**问题**: 以下字符串未走 `t()` 国际化：
- `characters.js`: `"删除此图片？"`、`"批量训练完成"`
- `projects.js:305,309`: `"✅ 已复制到剪贴板"`
- `extras.js:414`: `"暂无剧集"`
- `pipeline.js`: `"⏳ 批量生成中..."`、`"选择要训练 LoRA 的角色"`
- `seko.js:143`: `"正在创建项目并导入..."`（有 fallback 但直接写了中文）
**修复**: 提取到 `I18N` 字典。

### 15. _getRefCounts 性能问题
**文件**: `extras.js:~line 140`
**问题**: 每次删除角色/场景时遍历所有集数的所有分镜计算引用计数，O(episodes × shots) 网络请求。
**修复**: 后端提供 `/api/stats/ref-counts` 端点一次性返回。

### 16. CSS 颜色值不一致
**文件**: `web/static/css/style.css:1450`
**问题**: `.task-status-badge.st-success` 使用 `var(--green-soft, rgba(34,197,94,.15))`，但 `:root` 中 `--green-soft` 定义为 `rgba(52,211,153,.12)`。fallback 值与变量值色值不同（34,197,94 vs 52,211,153）。
**修复**: 移除 fallback 或统一色值。

### 17. setInterval 定时器永不清理
**文件**: `tasks.js:~line 265`（3s）、`extras.js:~line 305`（15s）
**问题**: 两个全局定时器在 SPA 生命周期内永不清理。
**修复**: 页面卸载或 `_lifespan` 结束时 `clearInterval`。

### 18. _pollImportTask / _pollSekoImportTask 代码重复
**文件**: `projects.js:318`、`seko.js:167`
**问题**: 两段轮询逻辑几乎完全相同（轮询+超时+错误处理），仅超时时长和 toast 不同。
**修复**: 合并为通用 `pollImportTask(taskId, opts)`。

### 19. LANGUAGES 硬编码
**文件**: `pipeline.js:~line 120`
**问题**: 语言选项硬编码 7 种语言，label 未走 i18n。
**修复**: 移到配置或 `I18N`。

### 20. overlay onclick 字符串拼接
**文件**: `characters.js:_showOverlay()` 调用处
**问题**: `_showOverlay` 中 `deleteFn` 直接拼入 `onclick="${deleteFn}"`，模式不安全（虽然当前 entity ID 已经过 `esc()` 转义）。
**修复**: 改用 `addEventListener`。

---

## 排查后降级 / 非问题

### ~~内存泄漏：previewRes 的 keydown 监听器~~ ✅ 已正确处理
**文件**: `pipeline.js:~line 113-119`
**说明**: `previewRes` 通过 monkey-patch `o.remove` 在移除 overlay 时清理 `_keyHandler`。ESC 键触发全局处理器 → `o.remove()` → 调用 patched remove → 清理监听器。**不是泄漏**，但用 `AbortController` 模式更健壮。

### ~~PUT vs POST 安全问题~~ ✅ 无安全风险
**说明**: 虽然方法语义不规范，但当前所有写端点都用 POST，不影响功能。属于 API 设计规范问题（见 #4），非安全漏洞。
