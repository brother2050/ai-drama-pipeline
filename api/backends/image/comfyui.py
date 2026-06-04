"""ComfyUI 图片/视频生成 — HTTP API"""
from __future__ import annotations
import logging, random, time, uuid, urllib.parse
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry
from infra.http_pool import get_client, auth_headers

logger = logging.getLogger(__name__)

class ComfyUI:
    """ComfyUI 图像/视频生成后端"""
    def __init__(self, config: dict):
        self._url = (config.get("url") or "").rstrip("/")
        if not self._url:
            raise ValueError("ComfyUI url 未配置，请在 system.yaml 的 comfyui.url 中设置")
        self._timeout = config.get("timeouts", {}).get("comfyui", 900)
        self._api_key = config.get("api_key", "")
        self._client = get_client(timeout=self._timeout)

    @property
    def name(self): return "comfyui"

    @property
    def url(self) -> str:
        """暴露服务器 URL，供 AssetTracker 等使用"""
        return self._url

    def _headers(self) -> dict:
        return auth_headers(self._api_key)

    def check_image_exists(self, filename: str, subfolder: str = "", asset_type: str = "output") -> bool:
        """检查图片是否已存在于 ComfyUI 服务器

        通过 HEAD 请求 /view 端点验证，HTTP 200 表示文件存在。
        Args:
            asset_type: "output"（生成结果）或 "input"（上传的图片），默认 "output"
        """
        try:
            params = {"filename": filename, "type": asset_type}
            if subfolder:
                params["subfolder"] = subfolder
            r = self._client.head(f"{self._url}/view", params=params,
                                  headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    def upload_image(self, filepath: str, overwrite: bool = True, filename: str | None = None) -> dict:
        """上传图片到 ComfyUI 服务器（用于 IP-Adapter 等需要参考图的节点）

        Args:
            filepath: 本地文件路径
            overwrite: 是否覆盖同名文件
            filename: 自定义服务端文件名（None 则使用本地文件名）
        """
        upload_name = filename or Path(filepath).name
        headers = auth_headers(self._api_key, content_type="")
        with open(filepath, "rb") as f:
            r = self._client.post(f"{self._url}/upload/image",
                           files={"image": (upload_name, f)},
                           data={"overwrite": str(overwrite).lower()},
                           headers=headers)
        r.raise_for_status()
        return r.json()

    def generate(self, workflow: dict, output_dir: str) -> list[str]:
        """提交工作流并等待结果，返回生成的文件路径列表"""
        client_id = uuid.uuid4().hex
        r = self._client.post(f"{self._url}/prompt", json={"prompt": workflow, "client_id": client_id},
                      headers=self._headers())
        if r.status_code != 200:
            try:
                detail = _extract_error(r)
            except Exception:
                detail = r.text[:500]
            raise RuntimeError(f"ComfyUI /prompt 提交失败 (HTTP {r.status_code}): {detail}")
        try:
            resp = r.json()
        except Exception:
            raise RuntimeError(f"ComfyUI /prompt 返回非 JSON 响应 (HTTP {r.status_code}): {r.text[:200]}")
        if "error" in resp:
            raise RuntimeError(f"ComfyUI 工作流提交失败: {resp['error']}")
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id: {resp}")

        return self._poll_until_done(prompt_id, output_dir)

    def _poll_until_done(self, prompt_id: str, output_dir: str) -> list[str]:
        """轮询 ComfyUI /history 直到任务完成（指数退避 + jitter）"""
        deadline = time.time() + self._timeout
        poll_interval = 2
        while time.time() < deadline:
            try:
                r = self._client.get(f"{self._url}/history/{prompt_id}", headers=self._headers())
                if r.status_code == 200:
                    result = self._check_history(r, prompt_id, output_dir)
                    if result is not None:
                        return result
            except httpx.HTTPError as e:
                logger.debug(f"ComfyUI 轮询网络抖动: {e}")
            time.sleep(poll_interval * (0.5 + random.random()))
            poll_interval = min(poll_interval * 2, 16)
        raise TimeoutError(f"ComfyUI workflow timeout ({self._timeout}s)")

    def _check_history(self, r, prompt_id: str, output_dir: str) -> list[str] | None:
        """检查 /history 响应，完成时返回文件列表，未完成返回 None"""
        try:
            history = r.json()
        except Exception:
            logger.warning(f"GET /history/{prompt_id} 返回非 JSON (len={len(r.text)}): {r.text[:200]}")
            return None
        if prompt_id not in history:
            return None
        entry = history[prompt_id]
        status_info = entry.get("status", {})
        if status_info.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI 任务执行失败: {status_info.get('messages', [])}")
        outputs = entry.get("outputs", {})
        if outputs:
            files = self._download_outputs(outputs, output_dir)
            if not files:
                raise RuntimeError("ComfyUI 任务完成但未返回任何文件")
            return files
        return None

    def _download_outputs(self, outputs: dict, output_dir: str) -> list[str]:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        files = []
        headers = self._headers()
        for node_out in outputs.values():
            # 兼容图片(images)和视频(gifs/videos)输出
            media_items = (
                node_out.get("images", [])
                + node_out.get("gifs", [])
                + node_out.get("videos", [])
            )
            for img in media_items:
                fname = img.get("filename")
                if not fname:
                    continue
                fname = Path(fname).name
                subfolder = Path(img.get("subfolder", "")).name if img.get("subfolder") else ""
                url = f"{self._url}/view?filename={urllib.parse.quote(fname)}&subfolder={urllib.parse.quote(subfolder)}&type=output"
                r = self._client.get(url, headers=headers)
                r.raise_for_status()
                out_path = Path(output_dir) / fname
                out_path.write_bytes(r.content)
                files.append(str(out_path))
        return files

    def health_check(self) -> tuple[bool, str]:
        try:
            r = self._client.get(f"{self._url}/system_stats", headers=self._headers())
            return True, f"ComfyUI reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"ComfyUI unreachable: {e}"

def _extract_error(r) -> str:
    """从 ComfyUI 错误响应中提取详细信息"""
    try:
        err_body = r.json()
        detail = err_body.get("error", {}).get("message", "") if isinstance(err_body.get("error"), dict) else str(err_body.get("error", ""))
        node_errors = err_body.get("node_errors", {})
        if node_errors:
            detail += f" | node_errors: {node_errors}"
        return detail or r.text[:500]
    except Exception:
        return r.text[:500]


def _f(config): return ComfyUI(config)
registry.register(BackendMeta(name="comfyui", service_type="image", factory=_f,
    description="ComfyUI 图片/视频生成", priority=10, tags=["api"]))
