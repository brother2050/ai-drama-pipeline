"""API 路由 — 系统状态 / 工具管理 / 配置 / 单步执行"""
from __future__ import annotations

from infra.constants import STATUS_RUNNING
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from web.routers.deps import (
    _cfg, _merged_cfg, _cfg_path, _paths,
    _check_uuid,
    _check_tool, _submit_task,
    _deep_merge,
)
from infra.config import cfg_get as _cfg_get

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import (
    StepRequest, TTSRequest, PostRequest, MusicRequest, SubtitleRequest,
    ConfigUpdate,
)


# ══════════════════════════════════════════════════════════
# 系统
# ══════════════════════════════════════════════════════════

@router.get("/system/status")
def system_status() -> dict:
    """全量服务状态"""
    cfg = _merged_cfg()
    return {"version": "2.0.0", "tools": _collect_tools(cfg)}


from concurrent.futures import ThreadPoolExecutor, as_completed

_tool_executor = ThreadPoolExecutor(max_workers=5)


def _collect_tools(cfg: dict) -> dict:
    """收集所有工具状态（并行检测，避免串行超时累积）"""
    from flow.model_registry import ModelRegistry
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
    for fut in as_completed(futures, timeout=15):
        name = futures[fut]
        try:
            tools[name] = fut.result(timeout=10)
        except Exception as e:
            tools[name] = {"available": False, "backend": "unknown", "type": "unknown", "reason": str(e)}
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


_ALLOWED_SYS_KEYS = {"models", "comfyui", "llm", "seko", "training", "server", "post_production", "timeouts", "generation"}


@router.post("/system/config")
def update_system_config(data: dict = Body(...)):
    """更新系统全局配置（仅允许白名单字段）"""
    from infra.config import save_config, load_config, SYSTEM_CONFIG_PATH, Config
    import tempfile
    filtered = {k: v for k, v in data.items() if k in _ALLOWED_SYS_KEYS}
    if not filtered:
        raise HTTPException(400, "无有效的配置字段")
    try:
        existing = load_config(SYSTEM_CONFIG_PATH)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, filtered)
    # 校验合并后的配置合法性
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".yaml", dir=str(Path(SYSTEM_CONFIG_PATH).parent))
        os.close(fd)
        save_config(tmp, merged)
        Config(tmp)
    except ValueError as e:
        raise HTTPException(400, f"配置校验失败: {e}")
    except Exception as e:
        raise HTTPException(500, f"配置校验异常: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                logger.debug("临时文件清理")
                pass
    save_config(SYSTEM_CONFIG_PATH, merged)
    return {"status": "ok"}


@router.get("/system/workers")
def get_worker_status() -> dict:
    """获取 Celery Worker 状态"""
    try:
        from pipeline.celery_app import app as celery_app
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
        from flow.model_registry import ModelRegistry
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
        from api import _ensure_registered; _ensure_registered()
        handler = _svc_reg.find_test_handler(name)
        if handler:
            return handler(name, result, cfg)

        from flow.model_registry import ModelRegistry
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

    defaults = reg.get_defaults()
    backend_map = {
        "tts": ("tts", cfg.get("models", {}).get("tts_backend", defaults.get("tts_backend"))),
        "lipsync": ("lipsync", cfg.get("models", {}).get("lip_sync_backend", defaults.get("lip_sync_backend"))),
        "music": ("music", cfg.get("models", {}).get("music_backend", defaults.get("music_backend"))),
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
    from pipeline.celery_app import app
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


def _hc_handle_openai(name: str, hc: dict, cfg: dict, result: dict) -> dict:
    """OpenAI 兼容 API 模型列表检测"""
    base_url = _cfg_get(cfg, hc.get("config_key", ""))
    api_key = _cfg_get(cfg, hc.get("api_key_from", ""))
    from infra.http_pool import get_fast_client, auth_headers
    headers = auth_headers(api_key) if api_key else {}
    check_url = base_url.rstrip("/")
    if not check_url.endswith("/v1"):
        check_url += "/v1"
    r = get_fast_client().get(f"{check_url}/models", headers=headers)
    if r.status_code != 200:
        return {"ok": False, "name": name, "message": f"HTTP {r.status_code}", **result}
    count = len(r.json().get("data", []))
    return {"ok": True, "name": name, "message": f"LLM 连接成功 · {count} 模型", **result}


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
        "openai_models": lambda: _hc_handle_openai(*_HC_ARGS),
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
    from flow.model_registry import ModelRegistry as _MR
    _reg = _MR()
    _defaults = _reg.get_defaults()
    backend = llm_cfg.get("backend", _defaults.get("llm_backend"))
    api_key = llm_cfg.get("api_key", "")

    if not base_url:
        return {"ok": False, "name": name, "message": "未配置 API URL", **result}
    backend_meta = _reg.get_backend("llm", backend)
    needs_key = backend_meta.get("requires_api_key", True) if backend_meta else True

    if not api_key and needs_key:
        return {"ok": False, "name": name, "message": "未配置 API Key", **result}

    from infra.http_pool import get_fast_client, auth_headers
    headers = auth_headers(api_key) if api_key else None
    _http = get_fast_client()
    try:
        hc = _reg.get_health_check("llm", backend)
        hc_type = hc.get("type", "") if hc else ""

        if hc_type == "ollama_tags":
            r = _http.get(f"{base_url}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"ok": True, "name": name, "message": f"Ollama 连接成功 · {len(models)} 模型", "models": models, **result}
        else:
            check_url = base_url.rstrip("/")
            if not check_url.endswith("/v1"):
                check_url += "/v1"
            r = _http.get(f"{check_url}/models", headers=headers)
            if r.status_code in (401, 403):
                return {"ok": False, "name": name, "message": f"API Key 无效 ({r.status_code})", **result}
            if r.status_code == 404:
                return {"ok": False, "name": name, "message": f"接口不存在 (404)，检查 API URL: {check_url}", **result}
            if r.status_code != 200:
                return {"ok": False, "name": name, "message": f"HTTP {r.status_code}", **result}
            data = r.json()
            count = len(data.get("data", []))
            return {"ok": True, "name": name, "message": f"LLM 连接成功 · {count} 模型", **result}
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
    cfg = _cfg()
    return cfg


@router.post("/config")
def update_config(req: ConfigUpdate):
    """更新配置（接受 {"data": {...}} 格式）"""
    data = req.get_config_data()
    cfg_path = _cfg_path()
    from infra.config import save_config, load_config
    try:
        existing = load_config(cfg_path)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, data)
    from infra.config import Config
    import tempfile
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".yaml", dir=str(Path(cfg_path).parent))
        os.close(fd)
        save_config(tmp, merged)
        Config(tmp)
    except ValueError as e:
        raise HTTPException(400, f"配置校验失败: {e}")
    except Exception as e:
        raise HTTPException(500, f"配置校验异常: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError as e:
                logger.debug(f"{type(e).__name__}: {e}")
    save_config(cfg_path, merged)
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════
# 单步执行
# ══════════════════════════════════════════════════════════

def _find_shot_for_api(episode: int, shot_id: str) -> dict | None:
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_episode_shots
        for row in get_episode_shots(get_pool(), episode):
            if row.get("shot_id") == shot_id:
                return row
    except Exception:
        logger.debug("获取生成状态失败")
        pass
    return None


@router.post("/steps/tts")
def run_step_tts(req: StepRequest):
    from pipeline.tasks import step_tts
    return _submit_task(step_tts, _cfg_path(), req.episode, req.shot_id, req.force)


@router.post("/steps/first-frame")
def run_step_first_frame(req: StepRequest):
    from pipeline.tasks import step_first_frame
    return _submit_task(step_first_frame, _cfg_path(), req.episode, req.shot_id, req.force)


@router.post("/steps/video")
def run_step_video(req: StepRequest):
    from pipeline.tasks import step_video
    return _submit_task(step_video, _cfg_path(), req.episode, req.shot_id, req.force)


@router.post("/steps/lipsync")
def run_step_lipsync(req: StepRequest):
    from pipeline.tasks import step_lipsync
    return _submit_task(step_lipsync, _cfg_path(), req.episode, req.shot_id, req.force)


@router.post("/steps/shot")
def run_step_shot(req: StepRequest):
    from pipeline.tasks import shot_task
    shot = _find_shot_for_api(req.episode, req.shot_id)
    if not shot:
        raise HTTPException(404, f"镜头 {req.shot_id} 不存在")
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
    from pipeline.celery_app import app
    result = app.AsyncResult(task_id)
    info = result.info if result.info else {}
    state_map = {"PENDING": "pending", "STARTED": "running", "PROGRESS": "running",
                 "SUCCESS": "success", "FAILURE": "failed", "REVOKED": "cancelled"}
    status = state_map.get(result.state, result.state.lower())
    task_info = {
        "task_id": task_id, "status": status,
        "progress": info.get("progress", 0) if isinstance(info, dict) else 0,
        "stage": info.get("stage", "") if isinstance(info, dict) else "",
        "message": info.get("message", "") if isinstance(info, dict) else "",
    }
    if result.state == "SUCCESS":
        task_info["result"] = result.result
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
    from pipeline.celery_app import app
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
    from pipeline.celery_app import app
    app.control.revoke(task_id, terminate=True)
    return {"status": "cancelled", "task_id": task_id}
