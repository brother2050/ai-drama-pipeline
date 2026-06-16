"""ComfyUI 服务器资源跟踪 — 基于 PostgreSQL 持久化

通过 comfyui_assets 表记录哪些图片/LoRA 文件已上传到哪些服务器。
项目删除重建时，数据库中 project_dir 对应的记录为空，自动触发重新上传。
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

__all__ = ["comfyui_asset_name", "AssetTracker"]


def comfyui_asset_name(project_dir: str, char_id: str, filename: str) -> str:
    """生成 ComfyUI 服务器端唯一文件名

    格式: proj_{hash8}_{char_id}_{filename}
    - project_dir 的 MD5 前 8 位：不同项目即使同名也不碰撞
    - char_id：不同角色隔离
    - filename：原始文件名

    与视频帧的 ASCII 化逻辑保持一致风格。
    """
    dir_hash = hashlib.md5(project_dir.encode("utf-8")).hexdigest()[:8]
    return f"proj_{dir_hash}_{char_id}_{filename}"


class AssetTracker:
    """跟踪项目资源在各 ComfyUI 服务器上的存在状态

    数据存储在 PostgreSQL 表 comfyui_assets 中，以 project 名称隔离。
    """

    def __init__(self, project_dir: str):
        from pathlib import Path
        self._project_dir = project_dir
        # 从路径推导项目名（projects/<name>/ → <name>）
        self._project = Path(project_dir).resolve().name

    # ── 公开接口 ────────────────────────────────────────

    def is_image_tracked(self, server_url: str, filename: str) -> bool:
        """检查图片是否已记录存在于此服务器"""
        return self._check(server_url, "image", filename)

    def mark_image_tracked(self, server_url: str, filename: str) -> None:
        """记录图片已上传到此服务器"""
        self._mark(server_url, "image", filename)

    def is_lora_tracked(self, server_url: str, lora_name: str) -> bool:
        """检查 LoRA 是否已记录存在于此服务器"""
        return self._check(server_url, "lora", lora_name)

    def mark_lora_tracked(self, server_url: str, lora_name: str) -> None:
        """记录 LoRA 已存在于（或已上传到）此服务器"""
        self._mark(server_url, "lora", lora_name)

    def untrack_image(self, server_url: str, filename: str) -> None:
        """移除图片记录（文件被删除时使用）"""
        self._unmark(server_url, "image", filename)

    def untrack_lora(self, server_url: str, lora_name: str) -> None:
        """移除 LoRA 记录（文件被删除时使用）"""
        self._unmark(server_url, "lora", lora_name)

    def upload_if_needed(self, comfyui, local_path: str, remote_name: str,
                         server_url: str) -> bool:
        """带跟踪的上传：已存在则跳过，不存在则上传并记录

        Args:
            comfyui: ComfyUI 后端实例
            local_path: 本地文件路径
            remote_name: ComfyUI 服务端文件名
            server_url: ComfyUI 服务器 URL

        Returns:
            True=上传了，False=跳过了
        """
        # 1) tracker 记录了 + 服务端确实存在 → 跳过
        if self.is_image_tracked(server_url, remote_name):
            try:
                if comfyui.check_image_exists(remote_name, asset_type="input"):
                    logger.debug(f"参考图 {remote_name} 已在服务器，跳过上传")
                    return False
                else:
                    self.untrack_image(server_url, remote_name)
            except Exception as e:
                # 异常时清除 tracker 记录，宁可重复上传也不永久跳过
                logger.warning(f"检查资产存在性失败，清除 tracker 并重新上传: {e}")
                self.untrack_image(server_url, remote_name)

        # 2) 上传 + 记录（上传失败不清除 tracker，下次重试时会重新检查）
        comfyui.upload_image(local_path, filename=remote_name)
        self.mark_image_tracked(server_url, remote_name)
        return True

    # ── 内部实现 ────────────────────────────────────────

    def _check(self, server_url: str, asset_type: str, filename: str) -> bool:
        try:
            from infra.database.comfyui_assets import check
            from infra.database.pool import get_pool
            return check(get_pool(), server_url.rstrip("/"), asset_type, filename,
                         project=self._project)
        except Exception:
            return False

    def _mark(self, server_url: str, asset_type: str, filename: str) -> None:
        try:
            from infra.database.comfyui_assets import mark
            from infra.database.pool import get_pool
            mark(get_pool(), server_url.rstrip("/"), asset_type, filename,
                 project=self._project)
        except Exception as e:
            logger.warning(f"AssetTracker mark 失败（下次会重新上传）: {e}")

    def _unmark(self, server_url: str, asset_type: str, filename: str) -> None:
        try:
            from infra.database.comfyui_assets import unmark
            from infra.database.pool import get_pool
            unmark(get_pool(), server_url.rstrip("/"), asset_type, filename,
                   project=self._project)
        except Exception as e:
            logger.debug(f"AssetTracker unmark 失败: {e}")
