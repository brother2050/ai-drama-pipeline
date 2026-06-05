# TODO

> 待办清单。已修复/误判/设计意图的已移除。

---

## P0 — bible / bible_en 解耦

> commit d5c53e6 将 bible 拆为 `bible`（中文）和 `bible_en`（英文）两个 YAML 区块，
> 但逻辑上 bible_en 仍是 bible 的"翻译产物"，未真正独立。

| # | 文件 | 描述 |
|---|------|------|
| B1 | `engines/character_bible.py` | `get_tags()` 中文打底英文覆盖，bible_en 为空时回退中文 → 应去掉回退，bible_en 为空返回空 |
| B2 | `pipeline/tasks/ai.py` | `_collect_bible_texts()` 从 bible 读中文翻译写入 bible_en → 需支持 bible_en 独立生成（LLM 直接英文） |
| B3 | `pipeline/tasks/pipeline.py` | `run_all_task` 强制 bible → prepare 顺序 → 解耦后 bible_en 有内容时可跳过 prepare 翻译 |
| B4 | `web/static/js/pipeline.js` | 前端 prepare 按钮无独立提示 → 需支持 bible_en 直接编辑/生成，不依赖 bible 按钮 |
| B5 | `web/static/js/characters.js` | 角色编辑页无 bible_en 编辑入口 → 需增加英文圣经独立编辑区域 |

**解耦目标**：bible_en 可独立存在、独立生成、独立编辑，不依赖 bible 按钮。

---

## P2 — 优化（边缘场景 / 代码质量）

| # | 文件 | 描述 |
|---|------|------|
| 62 | `infra/database/pool.py` | 连接归还不检查实际可用性（DB 可能已重启） |
| 73 | `api/backends/lipsync/musetalk.py` | 文件字段名硬编码，不同部署版本可能不兼容 |
| 82 | `api/backends/training/ai_toolkit.py` | 从日志提取 safetensors 路径可能匹配到中间 checkpoint |
| 131 | `web/routers/deps.py` | `_safe_path` URL 解码可能破坏含 `%` 的文件名 |

---

## 保留模块（独立部署脚本）

| # | 文件 | 用途 |
|---|------|------|
| D5 | `scripts/ai_toolkit_api.py` | LoRA 训练服务 |
| D6 | `scripts/musicgen_server.py` | 配乐生成服务 |
