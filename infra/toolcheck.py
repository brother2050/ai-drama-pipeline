"""工具可用性检测 — 注册表驱动，零硬编码

从 models_registry.yaml 读取每个后端/服务的 health_check 配置，
通用执行器根据 type 字段执行对应检测逻辑。

新增工具只需在 YAML 中声明 health_check，不改代码。
"""
from __future__ import annotations

import logging
import os
import shutil
import time

from infra.network import port_ok as _port_ok, redis_port as _redis_port

logger = logging.getLogger(__name__)

__all__ = ["check_tool", "reset_registry"]

# 工具状态缓存（避免短时间内重复检测外部服务）
_tool_cache: dict[str, tuple[float, dict]] = {}
_TOOL_CACHE_TTL = 30  # 秒


def _url_ok(url: str, path: str = "/", headers: dict | None = None) -> bool:
    """检测 URL 是否可达（http_pool 优先，urllib 回退）"""
    try:
        from infra.http_pool import get_fast_client
        from infra.retry import retry
        def _check():
            r = get_fast_client().get(f"{url}{path}", headers=headers)
            return r.status_code in (200, 401, 403)
        return retry(_check, max_retries=2, base_delay=0.5)
    except ImportError as e:
        logger.debug(f"{type(e).__name__}: {e}")
    except Exception:
        return False
    # http_pool 不可用时用 urllib 回退
    try:
        import urllib.request
        req = urllib.request.Request(f"{url}{path}")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 401, 403)
    except Exception:
        return False


def _get_cfg_value(cfg: dict, dot_path: str) -> str:
    """从配置 dict 中按 dot path 读取值"""
    from infra.config import cfg_get
    return cfg_get(cfg, dot_path, "")


def _resolve_auth(cfg: dict, api_key_from: str) -> dict | None:
    """从配置中解析认证 headers"""
    if not api_key_from:
        return None
    api_key = _get_cfg_value(cfg, api_key_from)
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return None


def check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性（注册表驱动，带 TTL 缓存）

    Args:
        name: 工具名。支持两种格式：
            - 后端名: tts / comfyui / lipsync / llm / music / ffmpeg / redis / celery / seko / training
            - 复合名: ip_adapter / pulid_flux（自动映射到一致性方案或服务）
        cfg: 项目配置 dict

    Returns:
        {"available": bool, "backend": str, "type": str, "reason": str, ...}
    """
    now = time.time()
    if name in _tool_cache:
        ts, result = _tool_cache[name]
        if now - ts < _TOOL_CACHE_TTL:
            return result
    result = _check_tool_inner(name, cfg)
    _tool_cache[name] = (now, result)
    return result


def _check_tool_inner(name: str, cfg: dict) -> dict:
    """内部检测逻辑（注册表驱动）"""
    from flow.model_registry import ModelRegistry
    registry = ModelRegistry()

    # 1. 一致性方案（从注册表读取，不硬编码）
    consistency_map = registry.get_consistency_check_map()
    if name in consistency_map:
        return _check_consistency(name, cfg, registry, consistency_map[name])

    # 2. 辅助服务（从注册表 services 段查询）
    hc = registry.get_service_health_check(name)
    if hc:
        meta = registry.get_service_meta(name) or {}
        return _execute_health_check(name, hc, cfg,
                                     backend=meta.get("backend", name),
                                     type=meta.get("type", "unknown"))

    # 3. 服务类型名（如 "tts"、"llm"）→ 查默认后端
    service_types = registry.get_registered_service_types()
    if name in service_types:
        return _check_service_type_backend(name, cfg, registry)

    # 4. 后端名（如 "mimo-voicedesign"）→ 遍历所有服务类型匹配
    for service_type in service_types:
        # 检查该服务类型下是否有此名称的后端
        backend_meta = registry.get_backend(service_type, name)
        if backend_meta:
            hc = backend_meta.get("health_check")
            if hc:
                return _execute_health_check(
                    name, hc, cfg,
                    backend=name, type=service_type)
            # 有后端但无 health_check（如纯本地模板）
            return _result(True, name, service_type, f"{name}（无需健康检查）")

    return {"available": False, "backend": "unknown", "type": "unknown",
            "reason": f"未注册的工具: {name}"}


def _hc_api_key(name: str, hc: dict, cfg: dict, backend: str) -> dict:
    """api_key_env 类型检查"""
    env = hc.get("env", "")
    config_key = hc.get("config_key", "")
    cfg_val = _get_cfg_value(cfg, config_key) if config_key else ""
    ok = bool(os.environ.get(env) or cfg_val)
    reason = "" if ok else f"{env} 未配置（设置页或环境变量）"
    return _result(ok, backend, "cloud", reason)


def _hc_http(name: str, hc: dict, cfg: dict, backend: str, result_type: str) -> dict:
    """http 类型检查"""
    url = _get_cfg_value(cfg, hc.get("config_key", ""))
    if not url:
        return _result(False, backend, result_type, f"服务地址未配置 ({hc.get('config_key', '')})")
    headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
    ok = _url_ok(url, hc.get("path", "/"), headers)
    reason = "" if ok else f"服务不可达 ({url})"
    return _result(ok, backend, result_type, reason)


def _hc_ollama(name: str, hc: dict, cfg: dict, backend: str, result_type: str = "cloud") -> dict:
    """ollama_tags 类型检查"""
    url = _get_cfg_value(cfg, hc.get("config_key", ""))
    if not url:
        return _result(False, backend, result_type, "Ollama 地址未配置")
    ok = _url_ok(url, "/api/tags")
    reason = "" if ok else f"Ollama 不可达 ({url})"
    return _result(ok, backend, result_type, reason)


def _hc_openai(name: str, hc: dict, cfg: dict, backend: str, result_type: str = "cloud") -> dict:
    """openai_models 类型检查"""
    url = _get_cfg_value(cfg, hc.get("config_key", ""))
    if not url:
        return _result(False, backend, "cloud", "LLM 地址未配置")
    llm_enabled = cfg.get("llm", {}).get("enabled")
    if llm_enabled is None or str(llm_enabled).lower() in ("false", "0", ""):
        if _url_ok(url.rstrip("/") + "/v1/models", headers=_resolve_auth(cfg, hc.get("api_key_from", ""))):
            return _result(False, backend, result_type, "服务已就绪，但未启用（请在设置中开启）")
        return _result(False, backend, result_type, "LLM 未启用")
    check_url = url.rstrip("/")
    if not check_url.endswith("/v1"):
        check_url += "/v1"
    headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
    ok = _url_ok(check_url, "/models", headers=headers)
    reason = "" if ok else f"LLM 服务不可达 ({url})"
    return _result(ok, backend, result_type, reason)


def _hc_command(name: str, hc: dict, backend: str) -> dict:
    """command 类型检查"""
    cmd = hc.get("command", "")
    ok = bool(shutil.which(cmd))
    reason = "" if ok else f"{cmd} 未安装"
    return _result(ok, backend, "local", reason)


def _hc_port(name: str, hc: dict, backend: str) -> dict:
    """port 类型检查"""
    port = hc.get("port", 0)
    ok = _port_ok(port)
    reason = "" if ok else f"端口 {port} 未监听"
    return _result(ok, backend, "infra", reason)


def _hc_celery(name: str, backend: str) -> dict:
    """celery_active 类型检查"""
    if not _port_ok(_redis_port()):
        return _result(False, backend, "infra", "Redis 未运行（Celery 依赖 Redis）")
    try:
        from pipeline.celery_app import app
        insp = app.control.inspect(timeout=2)
        ok = bool(insp.active())
        reason = "" if ok else "Celery Worker 未启动"
        return _result(ok, backend, "infra", reason)
    except Exception:
        return _result(False, backend, "infra", "Celery 连接失败")


def _execute_health_check(name: str, hc: dict, cfg: dict,
                          backend: str = "", type: str = "") -> dict:
    """通用健康检查执行器 — 根据 hc.type 分发到对应检测逻辑"""
    check_type = hc.get("type", "")
    b = backend or name
    t = type or "unknown"

    if check_type == "api_key_env":
        return _hc_api_key(name, hc, cfg, b)
    if check_type == "http":
        return _hc_http(name, hc, cfg, b, t)
    if check_type == "ollama_tags":
        return _hc_ollama(name, hc, cfg, b, t)
    if check_type == "openai_models":
        return _hc_openai(name, hc, cfg, b, t)
    if check_type == "command":
        return _hc_command(name, hc, b)
    if check_type == "port":
        return _hc_port(name, hc, b)
    if check_type == "celery_active":
        return _hc_celery(name, b)
    return _result(False, b, "unknown", f"未知检查类型: {check_type}")


def _check_consistency(name: str, cfg: dict, registry, method: dict) -> dict:
    """检测一致性方案的可用性（从注册表读取配置，不硬编码）"""
    config_key = method.get("config_key", "")
    if config_key:
        # 检查配置中是否显式禁用
        method_cfg = cfg.get(config_key, {})
        if isinstance(method_cfg, dict) and method_cfg.get("enabled") is False:
            return _result(False, name, "gpu", f"{name} 已禁用")

    # 检查 ComfyUI 是否可达（从注册表读取 URL，不硬编码）
    comfyui_meta = registry.get_service_meta("comfyui") or {}
    comfyui_hc = comfyui_meta.get("health_check", {})
    comfyui_url = _get_cfg_value(cfg, comfyui_hc.get("config_key", "comfyui.url"))
    comfyui_key_from = comfyui_hc.get("api_key_from", "comfyui.api_key")
    headers = _resolve_auth(cfg, comfyui_key_from)
    comfyui_ok = _url_ok(comfyui_url, "/system_stats", headers=headers)
    if not comfyui_ok:
        return _result(False, name, "gpu", "ComfyUI 不可达")

    # 获取模型名
    model_name = ""
    if config_key:
        model_cfg = cfg.get(config_key, {})
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("model", "")
    return _result(True, name, "gpu",
                   f"{name} ({model_name})" if model_name else f"{name}")


def _check_service_type_backend(service_type: str, cfg: dict, registry) -> dict:
    """检测指定服务类型的当前后端

    Args:
        service_type: tts / lipsync / llm / music / image / video
        cfg: 项目配置
        registry: ModelRegistry 实例
    """
    cfg_key = registry.get_service_cfg_key(service_type)
    default_backend = registry.get_defaults().get(cfg_key, "")

    # 统一从注册表 config_paths 读取后端名
    config_path = registry.get_config_path(service_type)
    backend_name = _get_cfg_value(cfg, config_path) or default_backend

    if not backend_name:
        return _result(False, service_type, "unknown",
                       f"未配置 {cfg_key}")

    hc = registry.get_health_check(service_type, backend_name)
    if not hc:
        return _result(False, backend_name, "unknown",
                       f"后端 '{backend_name}' 未声明 health_check")

    return _execute_health_check(
        service_type, hc, cfg,
        backend=backend_name)


def _result(available: bool, backend: str, type: str, reason: str) -> dict:
    return {"available": available, "backend": backend, "type": type, "reason": reason}


def reset_registry():
    """重置 ModelRegistry 单例（用于测试）"""
    from flow.model_registry import ModelRegistry
    ModelRegistry._instance = None
    ModelRegistry._instance_mtime = 0.0
