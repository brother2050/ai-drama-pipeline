# TODO

> 全项目深度审查 — 2026-06-05

---

## P0 — 运行时崩溃

- [x] `cli/__init__.py:80` — `logger.debug()` 调用但 `logger` 未定义，`_ensure_deps_no_db()` 异常时必崩 `NameError` → `b5d9612`

## P1 — 重复代码（违反 DRY）

- [x] `web/routers/characters.py` vs `scenes.py` — save/delete/batch_delete 3 个函数结构完全相同，仅实体名不同 → `c17c6be`
- [x] `web/routers/system_tools.py` — run_step_tts/first_frame/video/lipsync 4 个函数结构完全相同 → `b38a7a7`
- [x] `api/backends/tts/*` — health_check 5 个函数逻辑完全相同，仅服务名字符串不同 → `e2eb567`
- [x] `cli/generate.py` — `-c/--config` 选项在 6 个命令中重复声明 → `265a3bd`

## P2 — 静默异常（20 处）

- [ ] `infra/json_parse.py` 6 处 except:pass — JSON 解析失败应至少 log.warning
- [ ] `api/backends/training/ai_toolkit.py` 2 处 except:pass
- [ ] `api/registry.py:303` — Container.shutdown_all() 异常被吞
- [ ] `infra/database/pool.py:104` — 连接归还失败被吞
- [ ] `infra/http_pool.py:106` — HTTP 客户端关闭失败被吞
- [ ] `pipeline/celery_app.py:58` — 健康检查钩子异常被吞
- [ ] `pipeline/tasks/helpers.py:151,161` — 缓存失效钩子异常被吞
- [ ] `cli/__init__.py:197` — Celery 检查异常被吞
- [ ] `post/subtitle.py:77` — 临时文件清理失败被吞
- [ ] `scripts/ai_toolkit_api.py:173` — 训练状态解析异常被吞

## P3 — 逻辑隐患

- [x] `web/routers/deps.py` — `_merged_cfg()` 返回的 dict 包含 `_project_dir`，GET /config API 暴露服务器内部路径 → `c592087`
- [ ] `engines/portrait.py` — `_generating` 重入保护 TTL=1800s，ComfyUI 卡死时 30 分钟内无法重试
