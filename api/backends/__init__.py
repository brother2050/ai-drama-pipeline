"""后端实现包 — 共享工具"""


def http_health_check(url: str, fast_client, service_name: str, path: str = "/") -> tuple[bool, str]:
    """HTTP/HTTPS 服务可达性检查（消除 TTS/LipSync 后端 health_check 重复逻辑）

    根据 url 的 scheme 自动选择 HTTP 或 HTTPS，本地和远端服务均支持。

    Args:
        url: 服务地址（如 http://127.0.0.1:9880 或 https://remote-server:9880）
        fast_client: httpx.Client 实例（5s 超时）
        service_name: 服务名（用于日志，如 "CosyVoice"）
        path: 探测路径（默认 "/"，可从 YAML 注册表的 health_check.path 读取）

    Returns:
        (available, reason) 元组
    """
    try:
        r = fast_client.get(f"{url}{path}")
        return True, f"{service_name} reachable (HTTP {r.status_code})"
    except Exception as e:
        return False, f"{service_name} unreachable: {e}"
