"""AnimateDiff 视频生成 — ComfyUI API"""
from __future__ import annotations
import logging
from api.registry import BackendMeta, registry
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)


class _ComfyUIVideoBase:
    """ComfyUI 视频后端基类 — 缓存 ComfyUI 实例"""

    def __init__(self, config: dict):
        self._comfyui_url = (config.get("comfyui_url")
                             or config.get("url") or "").rstrip("/")
        if not self._comfyui_url:
            raise ValueError("ComfyUI url 未配置，请在 system.yaml 的 comfyui.url 中设置")
        self._timeout = config.get("timeouts", {}).get("comfyui", 900)
        self._api_key = config.get("api_key", "")
        self._comfyui = None

    def _get_comfyui(self):
        if self._comfyui is None:
            from api.backends.image.comfyui import ComfyUI
            self._comfyui = ComfyUI({
                "url": self._comfyui_url,
                "timeouts": {"comfyui": self._timeout},
                "api_key": self._api_key,
            })
        return self._comfyui

    def _headers(self) -> dict:
        return auth_headers(self._api_key)

    def generate(self, workflow: dict, output_dir: str) -> list[str]:
        return self._get_comfyui().generate(workflow, output_dir)

    def upload_image(self, filepath: str, overwrite: bool = True, filename: str | None = None) -> dict:
        return self._get_comfyui().upload_image(filepath, overwrite=overwrite, filename=filename)

    def check_image_exists(self, filename: str, subfolder: str = "", asset_type: str = "output") -> bool:
        return self._get_comfyui().check_image_exists(filename, subfolder=subfolder, asset_type=asset_type)

    def health_check(self) -> tuple[bool, str]:
        try:
            c = get_client(timeout=3)
            r = c.get(f"{self._comfyui_url}/system_stats", headers=self._headers())
            return True, f"{self.name} via ComfyUI (HTTP {r.status_code})"
        except Exception as e:
            return False, str(e)

    def shutdown(self):
        self._comfyui = None


class AnimateDiff(_ComfyUIVideoBase):
    """AnimateDiff 视频后端（通过 ComfyUI API 调用）"""
    @property
    def name(self) -> str: return "animatediff"


class CogVideoX(_ComfyUIVideoBase):
    """CogVideoX 视频生成 — ComfyUI API"""
    @property
    def name(self) -> str: return "cogvideox"


class CosmosVideo(_ComfyUIVideoBase):
    """Cosmos 视频生成 — ComfyUI API"""
    @property
    def name(self) -> str: return "cosmos-video"


def _f(config): return AnimateDiff(config)
registry.register(BackendMeta(name="animatediff", service_type="video", factory=_f,
    description="AnimateDiff 视频生成（via ComfyUI）", priority=10, tags=["api"]))

def _f2(config): return CogVideoX(config)
registry.register(BackendMeta(name="cogvideox", service_type="video", factory=_f2,
    description="CogVideoX 视频生成（via ComfyUI）", priority=50, tags=["api"]))

def _f3(config): return CosmosVideo(config)
registry.register(BackendMeta(name="cosmos-video", service_type="video", factory=_f3,
    description="Cosmos 视频生成（via ComfyUI）", priority=30, tags=["api"]))
