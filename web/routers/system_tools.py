"""API 路由 — 系统状态 / 工具管理 / 配置 / 单步执行"""
from __future__ import annotations

from infra.constants import STATUS_RUNNING
import logging
import os

from fastapi import APIRouter, HTTPException

from web.routers.deps import (
    _merged_cfg, _merged_cfg_public, _cfg_path, _paths,
    _check_uuid, _check_episode, _check_id,
    _check_tool, _submit_task, raise_not_found,
)
from infra.config import cfg_get as _cfg_get, deep_merge as _deep_merge

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import (  # noqa: E402
    StepRequest, TTSRequest, PostRequest, MusicRequest, SubtitleRequest,
    ConfigUpdate, SystemConfigUpdate,
)


# ══════════════════════════════════════════════════════════
# 系统
# ══════════════════════════════════════════════════════════

@router.get("/system/status")
def system_status() -> dict:
    """全量服务状态"""
    cfg = _merged_cfg()
    return {"version": "2.0.0", "tools": _collect_tools(cfg)}


from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402

_tool_executor = ThreadPoolExecutor(max_workers=5)

# 注册清理钩子：进程退出时关闭线程池
from infra.hooks import on_cleanup  # noqa: E402

@on_cleanup(priority=90)
def _shutdown_tool_executor():
    _tool_executor.shutdown(wait=False)


def _collect_tools(cfg: dict) -> dict:
    """收集所有工具状态（并行检测，避免串行超时累积）"""
    from infra.config.registry import ModelRegistry
    try:
        _reg = ModelRegistry()
        names = _reg.get_registered_service_types()
        for method_name, method_meta in _reg.get_consistency_check_map().items():
            if method_meta.get("config_key"):
                names.append(method_name)
    except Exception:
        names = ["redis", "celery", "tts", "comfyui", "lipsync", "llm", "music", "ffmpeg", "seko", "training", "ip_adapter", "pulid_flux"]
    tools = {}
    futures = {_tool_executor.submit(_check_tool, name, cfg): name for name in names}
    try:
        for fut in as_completed(futures, timeout=15):
            name = futures[fut]
            try:
                tools[name] = fut.result(timeout=10)
            except TimeoutError:
                tools[name] = {"available": False, "backend": "unknown", "type": "unknown", "reason": "检测超时"}
            except Exception as e:
                tools[name] = {"available": False, "backend": "unknown", "type": "unknown", "reason": str(e)}
    except TimeoutError:
        # 部分健康检查超时，标记为不可用而非静默丢失
        for fut, name in futures.items():
            if name not in tools:
                tools[name] = {"available": False, "backend": "unknown", "type": "unknown", "reason": "检测超时"}
    return tools


@router.get("/system/env")
def system_env() -> dict:
    import platform
    return {"os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version()}


@router.get("/system/config")
def get_system_config() -> dict:
    """读取系统全局配置"""
    from infra.config import SYSTEM_CONFIG_PATH, load_config
    if not os.path.isfile(SYSTEM_CONFIG_PATH):
        return {}
    try:
        return load_config(SYSTEM_CONFIG_PATH)
    except Exception as e:
        logger.warning(f"系统配置读取失败: {e}")
        return {}


@router.post("/system/config")
def update_system_config(req: SystemConfigUpdate) -> dict:
    """更新系统全局配置（Pydantic 校验 + 白名单）"""
    from infra.config import save_config, load_config, SYSTEM_CONFIG_PATH
    filtered = req.to_filtered_dict()
    if not filtered:
        raise HTTPException(400, "无有效的配置字段")
    try:
        existing = load_config(SYSTEM_CONFIG_PATH)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, filtered)
    save_config(SYSTEM_CONFIG_PATH, merged)
    # 通知 Config 实例热重载
    try:
        from infra.config import invalidate_config_cache
        invalidate_config_cache(SYSTEM_CONFIG_PATH)
    except Exception:
        pass
    return {"status": "ok"}


@router.get("/system/workers")
def get_worker_status() -> dict:
    """获取 Celery Worker 状态"""
    try:
        from pipeline.app import app as celery_app
        inspect = celery_app.control.inspect(timeout=0.5)
        active = inspect.active() or {}
        active_tasks = sum(len(v) for v in active.values())
        return {"status": "online", "active": active_tasks, "workers": list(active.keys())}
    except Exception as e:
        logger.debug(f"Worker 状态检查失败: {e}")
        return {"status": "offline", "active": 0, "workers": []}


# ══════════════════════════════════════════════════════════
# 工具管理
# ══════════════════════════════════════════════════════════

@router.get("/tools")
def list_tools() -> dict:
    """列出所有工具及其可用状态"""
    cfg = _merged_cfg()
    return {"tools": _collect_tools(cfg)}


@router.get("/backends")
def list_backends() -> dict:
    """列出所有可用后端（从模型注册表读取）"""
    try:
        from infra.config.registry import ModelRegistry
        reg = ModelRegistry()
        return {
            "tts": reg.get_tts_backends(),
            "lipsync": reg.get_lipsync_backends(),
            "llm": reg.get_llm_backends(),
            "music": reg.get_music_backends(),
            "image": {k: {"workflow": v.get("workflow", "")} for k, v in reg.get_backends("image").items()},
            "video": {k: {"workflow": v.get("workflow", "")} for k, v in reg.get_backends("video").items()},
        }
    except Exception as e:
        logger.debug(f"加载模型注册表失败: {e}")
        return {"tts": {}, "lipsync": {}, "llm": {}, "music": {}, "image": {}, "video": {}}


@router.get("/tools/{name}")
def check_tool(name: str) -> dict:
    """检测单个工具状态"""
    cfg = _merged_cfg()
    result = _check_tool(name, cfg)
    return {"name": name, **result}


@router.post("/tools/{name}/test")
def test_tool(name: str):
    """测试三方工具连接（注册表驱动，消除 if-elif 链）"""
    cfg = _merged_cfg()
    result = _check_tool(name, cfg)

    if name == "llm":
        return _test_llm(cfg, result)

    if not result.get("available"):
        return {"ok": False, "name": name, "message": result.get("reason", "不可用"), **result}

    try:
        from api.registry import registry as _svc_reg
        from api import _ensure_registered
        _ensure_registered()
        handler = _svc_reg.find_test_handler(name)
        if handler:
            return handler(name, result, cfg)

        from infra.config.registry import ModelRegistry
        _reg = ModelRegistry()
        hc = _resolve_health_check(name, _reg, cfg)

        if hc:
            return _run_health_check(name, hc, cfg, result, _reg)

        return {"ok": True, "name": name, "message": "可用", **result}

    except Exception as e:
        return {"ok": False, "name": name, "message": f"测试失败: {e}", **result}


def _resolve_health_check(name: str, reg, cfg: dict) -> dict | None:
    """从注册表解析工具的健康检查配置"""
    hc = reg.get_service_health_check(name)
    if hc:
        return hc

    backend_map = {
        "tts": ("tts", cfg.get("models", {}).get("tts_backend")),
        "lipsync": ("lipsync", cfg.get("models", {}).get("lip_sync_backend")),
        "music": ("music", cfg.get("models", {}).get("music_backend")),
    }
    if name in backend_map:
        svc_type, backend_name = backend_map[name]
        if backend_name:
            hc = reg.get_health_check(svc_type, backend_name)
            if hc:
                hc["_backend_name"] = backend_name
                hc["_service_type"] = svc_type
                return hc

    consistency_map = reg.get_consistency_check_map()
    if name in consistency_map:
        method_meta = consistency_map[name]
        config_key = method_meta.get("config_key", name)
        method_cfg = cfg.get(config_key, {})
        model = method_cfg.get("model", "")
        weight = method_cfg.get("weight", "")
        comfyui_ok = _check_tool("comfyui", cfg).get("available")
        if not method_cfg.get("enabled", True):
            return {"ok": False, "name": name, "message": f"{name} 未启用"}
        if not comfyui_ok:
            return {"ok": False, "name": name, "message": f"ComfyUI 不可达（{name} 依赖 ComfyUI）"}
        return {"ok": True, "name": name,
                "message": f"{name}: {model} (weight={weight})",
                "model": model, "weight": weight}

    return None


def _hc_handle_http(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """HTTP 健康检查"""
    api_url = _cfg_get(cfg, hc.get("config_key", ""))
    if not api_url:
        return {"ok": False, "name": name, "message": f"{hc.get('_backend_name', name)} 服务地址未配置", **result}
    from infra.http_pool import get_fast_client, auth_headers
    api_key_from = hc.get("api_key_from", "")
    api_key = _cfg_get(cfg, api_key_from) if api_key_from else ""
    headers = auth_headers(api_key, content_type="") if api_key else {}
    r = get_fast_client().get(api_url + hc.get("path", "/"), headers=headers)
    if name == "comfyui" and r.status_code == 200:
        data = r.json()
        vram = data.get("devices", [{}])[0].get("vram_total", 0) if data.get("devices") else 0
        msg = "连接成功" + (f" · VRAM {vram // 1024 // 1024}MB" if vram else "")
        return {"ok": True, "name": name, "message": msg, **result}
    return {"ok": True, "name": name, "message": f"{hc.get('_backend_name', name)} 连接成功 (HTTP {r.status_code})", **result}


def _hc_handle_command(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """命令行版本检测"""
    import subprocess
    cmd = hc.get("command", name)
    v = subprocess.run([cmd, "-version"], capture_output=True, text=True, timeout=5)
    ver = v.stdout.split("\n")[0] if v.returncode == 0 else "unknown"
    return {"ok": True, "name": name, "message": ver, **result}


def _hc_handle_port(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """端口可达性检测"""
    import socket
    host = hc.get("host", "127.0.0.1")
    port = hc.get("port", 0)
    with socket.create_connection((host, port), timeout=3) as s:
        if name == "redis":
            s.send(b"PING\r\n")
            resp = s.recv(64).decode().strip()
            ok = resp in ("+PONG", "PONG")
            return {"ok": ok, "name": name, "message": f"Redis: {resp}", **result}
    return {"ok": True, "name": name, "message": f"{host}:{port} 可达", **result}


def _hc_handle_celery(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """Celery Worker 状态检测"""
    from pipeline.app import app
    insp = app.control.inspect(timeout=3)
    active = insp.active() or {}
    workers = list(active.keys())
    return {"ok": True, "name": name, "message": f"Celery Worker: {', '.join(workers) or 'none'}", **result}


def _hc_handle_ollama(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """Ollama 模型列表检测"""
    base_url = _cfg_get(cfg, hc.get("config_key", ""))
    from infra.http_pool import get_fast_client
    r = get_fast_client().get(f"{base_url}/api/tags")
    models = [m.get("name", "") for m in r.json().get("models", [])]
    return {"ok": True, "name": name, "message": f"Ollama 连接成功 · {len(models)} 模型", "models": models, **result}


def _hc_handle_openai_chat(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """OpenAI 兼容 API 连接检测（POST /chat/completions，适用所有服务商）"""
    from infra.toolcheck import ping_openai_chat
    base_url = _cfg_get(cfg, hc.get("config_key", ""))
    api_key = _cfg_get(cfg, hc.get("api_key_from", ""))
    model = cfg.get("llm", {}).get("model", "unknown")
    ok, reason = ping_openai_chat(base_url, api_key=api_key, model=model, env_key="LLM_API_KEY")
    if not ok:
        return {"ok": False, "name": name, "message": reason or f"连接失败: {base_url}", **result}
    return {"ok": True, "name": name, "message": f"LLM 连接成功 · {model}", **result}


def _hc_handle_training(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """训练后端状态检测"""
    api_url = _cfg_get(cfg, hc.get("config_key", ""))
    if not api_url:
        return {"ok": False, "name": name, "message": "训练服务地址未配置", **result}
    try:
        from api import get_container
        cont = get_container(cfg)
        trainer = cont.get("training")
        status = trainer.check_status()
        if status.get("status") == "connected":
            return {"ok": True, "name": name, "message": status.get("message", "AI Toolkit 就绪"), **result}
        return {"ok": False, "name": name, "message": status.get("error", "连接失败"), **result}
    except Exception as e:
        return {"ok": False, "name": name, "message": f"训练后端不可用: {e}", **result}


def _run_health_check(name: str, hc: dict, cfg: dict, result: dict, reg) -> dict:
    """根据 health_check.type 执行实际连接测试"""
    if hc.get("ok") is not None:
        return {**result, **hc}

    hc_type = hc.get("type", "")
    service_type = hc.get("_service_type", "")

    if hc_type == "api_key_env":
        env_name = hc.get("env", "")
        env_val = os.environ.get(env_name, "")
        cfg_val = _cfg_get(cfg, hc.get("config_key", "")) if hc.get("config_key") else ""
        source = "配置文件" if cfg_val else ("环境变量" if env_val else "未配置")
        return {"ok": True, "name": name, "message": f"{hc.get('_backend_name', name)} API Key ({source})", **result}

    _HC_ARGS = (name, hc, cfg, result)
    _HANDLERS = {
        "http": lambda: _hc_handle_http(*_HC_ARGS),
        "command": lambda: _hc_handle_command(*_HC_ARGS),
        "port": lambda: _hc_handle_port(*_HC_ARGS),
        "celery_active": lambda: _hc_handle_celery(*_HC_ARGS),
        "ollama_tags": lambda: _hc_handle_ollama(*_HC_ARGS),
        "openai_chat": lambda: _hc_handle_openai_chat(*_HC_ARGS),
    }

    handler = _HANDLERS.get(hc_type)
    if handler:
        return handler()
    if name == "training" or service_type == "training":
        return _hc_handle_training(name, hc, cfg, result)
    return {"ok": True, "name": name, "message": "可用", **result}


def _test_llm(cfg: dict, result: dict) -> dict:
    """LLM 连接测试（忽略 enabled 开关，直接测）"""
    name = "llm"
    llm_cfg = cfg.get("llm", {})
    base_url = llm_cfg.get("base_url", "")
    if not base_url:
        return {"ok": False, "name": name, "message": "未配置 API URL", **result}

    from infra.config.registry import ModelRegistry
    reg = ModelRegistry()
    backend = llm_cfg.get("backend", "openai")
    hc = reg.get_health_check("llm", backend)
    hc_type = hc.get("type", "") if hc else ""

    # 构造临时 hc dict，复用 _hc_handle_ollama / _hc_handle_openai
    fake_hc = {"config_key": "llm.base_url"}
    try:
        if hc_type == "ollama_tags":
            return _hc_handle_ollama(name, fake_hc, cfg, result)
        return _hc_handle_openai_chat(name, fake_hc, cfg, result)
    except Exception as e:
        ename = type(e).__name__
        if "Connect" in ename:
            return {"ok": False, "name": name, "message": f"连接被拒绝: {base_url}", **result}
        if "Timeout" in ename:
            return {"ok": False, "name": name, "message": f"连接超时: {base_url}", **result}
        return {"ok": False, "name": name, "message": f"连接失败: {e}", **result}


# ══════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════

@router.get("/config")
def get_config() -> dict:
    return _merged_cfg_public()


@router.post("/config")
def update_config(req: ConfigUpdate) -> dict:
    """更新配置（接受 {"data": {...}} 格式）"""
    data = req.get_config_data()
    cfg_path = _cfg_path()
    from infra.config import save_config, load_config
    try:
        existing = load_config(cfg_path)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, data)
    save_config(cfg_path, merged)
    # 通知 Config 实例热重载
    try:
        from infra.config import invalidate_config_cache
        invalidate_config_cache(cfg_path)
    except Exception:
        pass
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════
# 单步执行
# ══════════════════════════════════════════════════════════

def _find_shot_for_api(episode: int, shot_id: str) -> dict | None:
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_shot
        return get_shot(get_pool(), episode, shot_id)
    except Exception as e:
        logger.warning(f"获取生成状态失败: {e}")
    return None


# ── 单步执行（4 个步骤共用同一模式）──

_STEP_TASKS = {
    "tts": ("step_tts", "🎤 TTS 语音合成"),
    "first-frame": ("step_first_frame", "🖼️ 首帧生成"),
    "video": ("step_video", "🎬 视频生成"),
    "lipsync": ("step_lipsync", "👄 口型同步"),
}

def _make_step_handler(task_name: str, summary: str):
    def handler(req: StepRequest):
        _check_episode(req.episode)
        _check_id(req.shot_id, "shot_id")
        import pipeline.tasks as tasks
        task_fn = getattr(tasks, task_name)
        return _submit_task(task_fn, _cfg_path(), req.episode, req.shot_id, req.force)
    handler.__name__ = f"run_step_{task_name}"
    handler.__doc__ = summary
    return handler

for _step_path, (_task_name, _summary) in _STEP_TASKS.items():
    router.add_api_route(f"/steps/{_step_path}", _make_step_handler(_task_name, _summary),
                         methods=["POST"], summary=_summary)


@router.post("/steps/shot")
def run_step_shot(req: StepRequest):
    from pipeline.tasks import shot_task
    shot = _find_shot_for_api(req.episode, req.shot_id)
    if not shot:
        raise_not_found("镜头", req.shot_id)
    return _submit_task(shot_task, _cfg_path(), req.episode, shot, req.force)


# ══════════════════════════════════════════════════════════
# 独立工具执行
# ══════════════════════════════════════════════════════════

@router.post("/tools/tts")
def run_tts(req: TTSRequest):
    from pipeline.tasks import tts_single_task
    return _submit_task(tts_single_task, _cfg_path(), req.text,
                        req.voice_config, req.emotion, req.language)


@router.post("/tools/portraits")
def gen_portraits(force: bool = False):
    from pipeline.tasks import portraits_task
    return _submit_task(portraits_task, _cfg_path(), force=force)


@router.post("/tools/scene-images")
def gen_scene_images(force: bool = False):
    from pipeline.tasks import scene_images_task
    return _submit_task(scene_images_task, _cfg_path(), force=force)


@router.post("/tools/post")
def run_post(req: PostRequest):
    from pipeline.tasks import post_task
    return _submit_task(post_task, _cfg_path(), req.episode, req.vertical)


@router.post("/tools/music")
def run_music(req: MusicRequest):
    from pipeline.tasks import music_task
    import time
    output = str(_paths().bgm_file(str(int(time.time()))))
    return _submit_task(music_task, _cfg_path(), req.duration, req.mood, output)


@router.post("/tools/subtitle")
def run_subtitle(req: SubtitleRequest):
    from pipeline.tasks import subtitle_task
    return _submit_task(subtitle_task, _cfg_path(), req.episode)


# ══════════════════════════════════════════════════════════
# Celery 任务查询
# ══════════════════════════════════════════════════════════

@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    _check_uuid(task_id)
    from pipeline.app import app
    result = app.AsyncResult(task_id)
    info = result.info if result.info else {}
    state_map = {"PENDING": "pending", "STARTED": "running", "PROGRESS": "running",
                 "SUCCESS": "success", "FAILURE": "failed", "REVOKED": "cancelled"}
    status = state_map.get(result.state, result.state.lower())
    task_info = {
        "task_id": task_id, "status": status,
        "progress": info.get("progress", 0) if isinstance(info, dict) else 0,
        "stage": info.get("step", "") if isinstance(info, dict) else "",
        "message": info.get("message", "") if isinstance(info, dict) else "",
    }
    if result.state == "SUCCESS":
        raw = result.result
        if isinstance(raw, dict):
            # 只返回安全字段，避免暴露内部路径和配置细节
            safe_keys = {"status", "episode", "count", "shots", "message", "reason",
                         "characters", "scenes", "generated_characters", "generated_scenes",
                         "total_duration", "done", "skipped", "errors", "details",
                         "results", "quality_issues", "translation_warnings",
                         "removed_shots", "cleared_files", "preset"}
            task_info["result"] = {k: v for k, v in raw.items() if k in safe_keys}
        else:
            task_info["result"] = raw
    elif result.state == "FAILURE":
        raw = result.result
        if isinstance(raw, dict) and raw.get("reason"):
            task_info["error"] = raw["reason"]
        elif isinstance(raw, dict) and raw.get("error"):
            task_info["error"] = raw["error"]
        elif isinstance(raw, Exception):
            task_info["error"] = f"{type(raw).__name__}: {str(raw).splitlines()[0]}"
        else:
            task_info["error"] = str(raw)[:200] if raw else ""
    return task_info


@router.get("/tasks")
def list_tasks() -> dict:
    from pipeline.app import app
    try:
        insp = app.control.inspect(timeout=2)
        active = insp.active() or {}
        tasks = []
        for worker, tl in active.items():
            for t in tl:
                tasks.append({"task_id": t.get("id"), "name": t.get("name"),
                              "status": STATUS_RUNNING, "worker": worker})
        return {"tasks": tasks}
    except Exception as e:
        logger.debug(f"获取任务列表失败: {e}")
        return {"tasks": []}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    _check_uuid(task_id)
    from pipeline.app import app
    # 先查询任务状态
    result = app.AsyncResult(task_id)
    state = result.state
    # PROGRESS 是自定义状态（update_state 设置），表示任务正在执行中
    if state in ("PENDING", "STARTED", "RETRY", "PROGRESS"):
        app.control.revoke(task_id, terminate=True)
        return {"status": "cancelled", "task_id": task_id}
    return {"status": "already_finished", "task_id": task_id, "state": state}


# ══════════════════════════════════════════════════════════
# 质量检查
# ══════════════════════════════════════════════════════════

@router.get("/quality/status")
def get_quality_status() -> dict:
    """查询当前项目各阶段的质量检查状态（持久化检查，页面加载和任务完成时调用）"""
    from engines.quality_gate import check_quality
    project_dir = str(_paths().root)
    results = {}
    has_warnings = False
    # 检查所有已启用的阶段
    for stage in ("after_prepare", "after_portrait", "after_produce", "after_post"):
        try:
            issues = check_quality(stage, project_dir)
            if issues:
                warnings = [i for i in issues if i["severity"] == "warning"]
                errors = [i for i in issues if i["severity"] == "error"]
                results[stage] = {"warnings": warnings, "errors": errors}
                if warnings or errors:
                    has_warnings = True
        except Exception:
            continue
    return {"has_warnings": has_warnings, "stages": results}
