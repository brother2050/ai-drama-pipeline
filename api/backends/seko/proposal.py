"""Seko API 后端 — 影视策划案生成/查询/修改 + 图片下载

集成 seko.sensetime.com 的策划案相关功能，不含视频生产接口。
统一使用 httpx 作为 HTTP 客户端（与项目其他模块一致）。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://seko.sensetime.com"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _get_api_key(config: dict | None = None) -> str:
    """获取 Seko API Key（参数 > 环境变量）"""
    if config and config.get("api_key"):
        return config["api_key"]
    return os.environ.get("SEKO_API_KEY", "")


def _headers(api_key: str) -> dict:
    return {
        "Seko-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


# ══════════════════════════════════════════════════════════
# 策划案生成
# ══════════════════════════════════════════════════════════

def generate_proposal(prompt: str, *, api_key: str = "", config: dict | None = None) -> dict:
    """生成影视策划案

    Args:
        prompt: 策划案描述/故事梗概
        api_key: Seko API Key（可选，默认从环境变量读取）
        config: 后端配置字典

    Returns:
        API 响应字典，包含 taskId 等信息
    """
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.post(f"{_API_BASE}/seko-api/openapi/v1/plan-tasks",
                            json={"input": prompt}, headers=_headers(key))
            return r.json()
    except Exception as e:
        logger.error(f"生成策划案失败: {e}", exc_info=True)
        return {"code": 500, "msg": str(e)}


# ══════════════════════════════════════════════════════════
# 策划案状态查询
# ══════════════════════════════════════════════════════════

def check_proposal_status(task_id: str, *, api_key: str = "", config: dict | None = None) -> dict:
    """查询策划案任务状态（单次查询，不轮询）"""
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(f"{_API_BASE}/seko-api/openapi/v1/plan-tasks/{task_id}/status",
                           headers=_headers(key))
            return r.json()
    except Exception as e:
        return {"code": 500, "msg": str(e)}


def wait_for_proposal(
    task_id: str,
    *,
    api_key: str = "",
    config: dict | None = None,
    interval: int = 10,
    max_retries: int = 180,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """轮询等待策划案任务完成

    Args:
        task_id: 任务 ID
        interval: 轮询间隔（秒）
        max_retries: 最大轮询次数（默认 180 次 × 10 秒 = 30 分钟）
        on_status: 状态回调 fn(status: str)

    Returns:
        最终 API 响应字典
    """
    import time

    logger.info(f"等待策划案完成，taskId: {task_id}，每 {interval} 秒轮询一次（最多 {max_retries} 次）...")
    consecutive_errors = 0
    for attempt in range(1, max_retries + 1):
        result = check_proposal_status(task_id, api_key=api_key, config=config)
        if result.get("code") != 200:
            # 服务器错误（5xx）可重试，客户端错误（4xx）直接返回
            code = result.get("code", 0)
            consecutive_errors += 1
            if code >= 500 and consecutive_errors < 5:
                logger.warning(f"API 服务器错误 (code={code})，重试 {consecutive_errors}/5")
                time.sleep(interval)
                continue
            return result
        consecutive_errors = 0

        data = result.get("data", {})
        status = data.get("taskStatus", "RUNNING")
        if on_status:
            on_status(status)

        if status == "RUNNING":
            time.sleep(interval)
        else:
            if status == "OK":
                logger.info("策划案任务成功完成！")
            elif status == "FAIL":
                logger.warning(f"策划案任务失败: {data.get('taskStatusMsg', '未知原因')}")
            return result

    logger.warning(f"策划案轮询超时（{max_retries} 次），taskId: {task_id}")
    return {"code": 408, "msg": f"轮询超时（{max_retries} 次）", "data": {"taskStatus": "TIMEOUT"}}


# ══════════════════════════════════════════════════════════
# 策划案修改
# ══════════════════════════════════════════════════════════

def modify_proposal(
    task_id: str,
    prompt: str,
    *,
    api_key: str = "",
    config: dict | None = None,
) -> dict:
    """修改已有策划案"""
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.post(f"{_API_BASE}/seko-api/openapi/v1/plan-tasks",
                            json={"input": prompt, "updateCtx": {"taskId": task_id}},
                            headers=_headers(key))
            return r.json()
    except Exception as e:
        logger.error(f"修改策划案失败: {e}", exc_info=True)
        return {"code": 500, "msg": str(e)}


# ══════════════════════════════════════════════════════════
# 图片下载
# ══════════════════════════════════════════════════════════

def download_image(url: str, output_path: str) -> str:
    """下载图片到指定路径

    Returns:
        实际保存的文件路径
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "downloaded_image.png"

    out = Path(output_path)
    if out.is_dir() or not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
        out = out / filename
    else:
        out.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        with client.stream("GET", url, headers={"User-Agent": "ai-drama-pipeline/2.0"}) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    f.write(chunk)

    logger.info(f"图片下载成功: {out}")
    return str(out)


def download_elements_images(data: dict, download_dir: str) -> list[str]:
    """下载策划案返回 JSON 中的所有 elements 图片"""
    elements = data.get("result", {}).get("elements", [])
    if not elements:
        logger.info("未发现可下载的 elements 图片。")
        return []

    Path(download_dir).mkdir(parents=True, exist_ok=True)
    downloaded = []

    for element in elements:
        url = element.get("elementUrl")
        name = element.get("elementName")
        if not url or not name:
            continue

        from urllib.parse import urlparse
        ext = Path(urlparse(url).path).suffix or ".jpeg"
        safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
        filepath = str(Path(download_dir) / f"{safe_name}{ext}")

        try:
            download_image(url, filepath)
            downloaded.append(filepath)
        except Exception as e:
            logger.warning(f"下载失败 {name}: {e}")

    return downloaded
