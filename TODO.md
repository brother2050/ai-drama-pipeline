# TODO

> 全项目深度审查 — 2026-06-05

---

## P0 — 运行时崩溃

- [x] `cli/__init__.py:80` — `logger.debug()` 调用但 `logger` 未定义 → `b5d9612`

## P1 — 重复代码（违反 DRY）

- [x] `web/routers/characters.py` vs `scenes.py` — batch_delete 重复 → `c17c6be`
- [x] `web/routers/system_tools.py` — 4 个 step 路由重复 → `b38a7a7`
- [x] `api/backends/tts/*` — 5 个 health_check 重复 → `e2eb567`
- [x] `cli/generate.py` + `pipeline.py` — 11 处 config_option 重复 → `265a3bd`

## P2 — 静默异常（关键路径已修复）

- [x] `infra/json_parse.py` — JSON 解析失败添加 debug 日志 → `10040c7`
- [x] `api/registry.py` — Container shutdown 异常添加 debug 日志 → `10040c7`
- [x] `pipeline/tasks/helpers.py` — ctx 缓存失效异常添加 debug 日志 → `10040c7`
- [ ] 其余 17 处 except:pass — 清理代码/可选依赖导入，保持静默合理

## P3 — 逻辑隐患

- [x] `web/routers/deps.py` — GET /config 暴露 _project_dir → `c592087`
- [x] `engines/portrait.py` — 重入保护 TTL 30min→5min → `2c9ed5f`
