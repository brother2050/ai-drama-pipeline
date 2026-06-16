"""Seko 后端注册 — 影视策划案功能"""
from __future__ import annotations

import logging
import os

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)


def _seko_test_handler(name: str, result: dict, cfg: dict) -> dict:
    """Seko 连接测试 — 实际调用 API 验证 Key 有效性"""
    seko_cfg = cfg.get("seko", {})
    api_key = seko_cfg.get("api_key") or os.environ.get("SEKO_API_KEY", "")
    if not api_key:
        return {"ok": False, "name": name, "message": "SEKO_API_KEY 未配置", **result}
    from api.backends.seko.proposal import check_proposal_status
    test_result = check_proposal_status("__health_check__", api_key=api_key, config=seko_cfg)
    code = test_result.get("code", 0)
    if code in (401, 403):
        return {"ok": False, "name": name, "message": f"API Key 无效 (HTTP {code})", **result}
    if isinstance(test_result.get("msg"), str) and "auth" in test_result["msg"].lower():
        return {"ok": False, "name": name, "message": f"API Key 认证失败: {test_result['msg']}", **result}
    return {"ok": True, "name": name, "message": f"Seko API 连接正常 (code={code})", **result}


class SekoProposal:
    """Seko 影视策划案后端"""

    def __init__(self, config: dict):
        self._config = config

    @property
    def name(self) -> str:
        return "seko"

    def is_available(self) -> bool:
        """检查 Seko API Key 是否已配置"""
        key = self._config.get("api_key") or os.environ.get("SEKO_API_KEY", "")
        return bool(key)


# 注册到服务注册表
try:
    registry.register(BackendMeta(
        name="seko",
        service_type="seko",
        factory=lambda cfg: SekoProposal(cfg),
        requires_api_key=True,
        api_key_env="SEKO_API_KEY",
        description="Seko 影视策划案（seko.sensetime.com）",
        priority=10,
        test_handler=_seko_test_handler,
    ))
except Exception as e:
    logger.debug(f"Seko 后端注册跳过: {e}")
