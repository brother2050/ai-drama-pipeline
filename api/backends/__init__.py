"""后端实现包 — 共享工具"""


def http_health_check(url: str, fast_client, service_name: str) -> tuple[bool, str]:
    """HTTP 服务可达性检查（消除 TTS/LipSync 后端 health_check 重复逻辑）

    Args:
        url: 服务地址
        fast_client: httpx.Client 实例（5s 超时）
        service_name: 服务名（用于日志，如 "CosyVoice"）

    Returns:
        (available, reason) 元组
    """
    try:
        r = fast_client.get(f"{url}/docs")
        return True, f"{service_name} reachable (HTTP {r.status_code})"
    except Exception as e:
        return False, f"{service_name} unreachable: {e}"
