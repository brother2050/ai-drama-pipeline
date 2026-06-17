"""路径管理 — 统一项目路径"""

from __future__ import annotations
from pathlib import Path


class ProjectPaths:
    """统一路径管理 — 所有项目路径的单一数据源"""

    def __init__(self, project_dir: str | Path):
        self._root = Path(project_dir).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ── 配置 ──────────────────────────────────────────

    @property
    def config_dir(self) -> Path:
        return self._root / "config"

    @property
    def project_yaml(self) -> Path:
        return self._root / "config" / "project.yaml"

    @property
    def characters_dir(self) -> Path:
        return self._root / "config" / "characters"

    @property
    def scenes_dir(self) -> Path:
        return self._root / "config" / "scenes"

    def character_yaml(self, char_id: str) -> Path:
        return self._root / "config" / "characters" / f"{char_id}.yaml"

    def scene_yaml(self, scene_id: str) -> Path:
        return self._root / "config" / "scenes" / f"{scene_id}.yaml"

    # ── 资产 ──────────────────────────────────────────

    @property
    def assets_dir(self) -> Path:
        return self._root / "assets"

    @property
    def character_assets_dir(self) -> Path:
        return self._root / "assets" / "characters"

    @property
    def scene_assets_dir(self) -> Path:
        return self._root / "assets" / "scenes"

    @property
    def loras_dir(self) -> Path:
        return self._root / "assets" / "loras"

    def character_asset_dir(self, char_id: str) -> Path:
        return self._root / "assets" / "characters" / char_id

    def character_lora_dir(self, char_id: str) -> Path:
        return self._root / "assets" / "characters" / char_id / "lora"

    def character_outfit_dir(self, char_id: str, outfit_key: str) -> Path:
        return self._root / "assets" / "characters" / char_id / outfit_key

    def full_body_ref(self, char_id: str) -> Path | None:
        """获取角色全身参考图路径（回退链：full_body → three_quarter → cover → None）

        所有需要全身参考图的地方统一调用此方法，消除 3 处重复回退逻辑。
        """
        asset_dir = self.character_asset_dir(char_id)
        for name in ("full_body.png", "three_quarter.png", "cover.png"):
            p = asset_dir / name
            if p.exists():
                return p
        return None

    def scene_asset_dir(self, scene_id: str) -> Path:
        return self._root / "assets" / "scenes" / scene_id

    # ── 输出 ──────────────────────────────────────────

    @property
    def output_dir(self) -> Path:
        return self._root / "output"

    def episode_dir(self, episode: int) -> Path:
        return self._root / "output" / f"e{episode:02d}"

    def episode_srt(self, episode: int) -> Path:
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}.srt"

    def episode_final(self, episode: int) -> Path:
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}_final.mp4"

    def shot_dir(self, episode: int, shot_id: str) -> Path:
        return self._root / "output" / f"e{episode:02d}" / f"s{shot_id}"

    def shot_frame(self, episode: int, shot_id: str) -> Path:
        return self.shot_dir(episode, shot_id) / "frame.png"

    # ── 工作流 ──────────────────────────────────────────

    @property
    def workflows_dir(self) -> Path:
        return self._root / "workflows"

    # ── 其他 ──────────────────────────────────────────

    @property
    def projects_dir(self) -> Path:
        return self._root.parent.parent / "projects"

    @property
    def shared_assets_dir(self) -> Path:
        return self._root.parent.parent / "shared_assets"

    @property
    def voices_dir(self) -> Path:
        return self.shared_assets_dir / "voices"

    @property
    def tts_preview_dir(self) -> Path:
        return self._root / "output" / "tts_preview"

    def bgm_file(self, tag: str = "") -> Path:
        name = f"bgm_{tag}.wav" if tag else "bgm.wav"
        return self._root / "output" / name

    def config_entity_dir(self, entity_type: str) -> Path:
        return self._root / "config" / entity_type

    def assets_entity_dir(self, entity_type: str) -> Path:
        return self._root / "assets" / entity_type

    def config_entity_yaml(self, entity_type: str, entity_id: str) -> Path:
        return self._root / "config" / entity_type / f"{entity_id}.yaml"

    def seko_asset_dir(self, task_id: str) -> Path:
        return self._root / "assets" / "seko" / task_id

    def ensure_dirs(self) -> None:
        for d in [
            self.config_dir, self.characters_dir, self.scenes_dir,
            self.assets_dir,
            self.character_assets_dir, self.scene_assets_dir, self.loras_dir,
            self.output_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
