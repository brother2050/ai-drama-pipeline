# TODO

> 全项目深度审查 — 2026-06-05（未修复项）

---

## 已修复（14 次提交）

| # | 问题 | 提交 |
|---|------|------|
| P0 | `cli/__init__.py` logger 未定义必崩 | `b5d9612` |
| P1 | characters/scenes batch_delete 重复 | `c17c6be` |
| P1 | 4 个 step 路由重复 | `b38a7a7` |
| P1 | 5 个 health_check 重复 | `e2eb567` |
| P1 | 11 处 config_option 重复 | `265a3bd` |
| P1 | ProjectPaths 类型注解未导入 | `f7357de` |
| P2 | json_parse/registry/helpers 静默异常添加日志 | `10040c7` |
| P2 | json_parse.py f-string 双花括号 bug | `b9a405e` |
| P2 | batch_processor _last_error 类变量→实例变量 | `5b599e6` |
| P2 | distributor hasattr 缓存→lru_cache | `5b599e6` |
| P2 | max_tokens*4 循环不变量提取 | `11ff8b7` |
| P3 | GET /config 暴露 _project_dir | `c592087` |
| P3 | portrait.py TTL 30min→5min | `2c9ed5f` |
| P3 | step 路由 Swagger summary 丢失 | `b47421c` |

---

## 未修复

### 代码质量

- [ ] `cli/generate.py:15` — `register_generate_commands` 过长（238 行），可拆分为子函数
- [ ] `cli/pipeline.py:14` — `register_pipeline_commands` 过长（138 行），可拆分为子函数
- [ ] `cli/system.py:18` — `register_system_commands` 过长（184 行），可拆分为子函数
- [ ] `infra/safe_executor.py:49` — `safe_run` 过长（103 行），可拆分超时/重试/降级逻辑

### 静默异常（操作性代码应添加日志）

- [ ] `api/backends/training/ai_toolkit.py:461` — 训练状态解析 except:pass
- [ ] `scripts/ai_toolkit_api.py:172` — 训练进度解析 except:pass
- [ ] `scripts/project_mgr.py:166,276` — 项目操作 except:pass
- [ ] `web/routers/storyboard.py:162` — 分镜导入 except:pass
- [ ] `web/routers/storyboard.py:72` — CSV 导出 except:pass
- [ ] `web/routers/system_tools.py:478` — 配置更新 except:pass
- [ ] `web/routers/deps.py:167` — 任务提交 except:pass

### 可接受的静默异常（无需修改）

- [x] `infra/json_parse.py` 6 处 — JSON 多策略解析的正常回退，预期失败
- [x] `cli/__init__.py:202` — Celery 检查降级（Worker 未启动时合理）
- [x] `pipeline/tasks/seko.py:145` — Seko 数据解析回退
