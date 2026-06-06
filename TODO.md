# TODO — 全项目代码审查（2026-06-06 第二轮）

> 5 个维度并行审查：前端↔API 契约、Celery 任务流、YAML 配置、LLM 交互、文件 I/O。
> 按优先级排列。已修复的项不在此列。

---

## ✅ 全部已修复

| # | 文件 | 问题 | 提交 |
|---|------|------|------|
| 4 | `infra/batch_processor.py` | `estimate_tokens` 低估 CJK 标点 | `b60023b` |
| 5 | `engines/llm_generator.py` | `generate_storyboard` 不校验返回镜头数 | `491bce6` |
| 6 | `infra/config.py` | `.active` 文件路径遍历 | `b60023b` |
| 7 | `engines/portrait.py` | `os.replace` 跨文件系统 | `b60023b` |
| 8 | `web/routers/assets.py` | 上传文件非原子写入 | `b60023b` |
| 10 | `config/system.yaml` | cosyvoice/fish_speech 配置缺失 | `b60023b` |
| 11 | `config/default_storyboard.py` | outfits 缺 default key | `b60023b` |
| 12 | `web/routers/imports.py` | presets 只传 key 不传描述 | `b60023b` |
| 13 | `web/routers/assets.py` | get_entity_asset 缺 _safe_path | `b60023b` |
| 14 | `post/production.py` | _rename_final 跨文件系统源文件未清理 | `491bce6` |
| 15 | `config/models_registry.yaml` | config_paths 缺 seko/training | `b60023b` |
| 17 | `engines/shot_calibrator.py` | _enrich_stage 未匹配静默跳过 | `491bce6` |
| 18 | `engines/prompt.py` | batch_len 回退防御性不足 | `491bce6` |
| 20 | `post/vertical.py` | 导入 _FFMPEG 内部变量 | `b60023b` |
| 21 | `web/routers/deps.py` | rmtree ignore_errors 静默失败 | `491bce6` |

**跳过（误报/无需修复）**:
- #9 FFmpeg input/output 路径：subprocess 列表参数，OS 直接传递，不受特殊字符影响
- #16 llm.model 键名：Container._backend_config 已正常传递

---

## ⏳ 待补充

- audit2-frontend-api（前端 JS ↔ 后端 API 契约）— 进行中
- audit2-celery（Celery 任务流）— 进行中
