"""质量门禁系统 — 管线各阶段结束后自动检查

参考 Toonflow-app 的 3 层 Agent 协作（监督层）设计：
每个阶段结束后自动检查产出质量，问题早发现早解决。

用法:
    gate = QualityGate()
    issues = gate.check("after_prepare", project_dir)
    if issues:
        for issue in issues:
            print(f"{'❌' if issue['severity'] == 'error' else '⚠'} {issue['name']}: {issue['message']}")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["QualityGate", "check_quality"]


def check_quality(stage: str, project_dir: str, *, episode: int | None = None) -> list[dict]:
    """快捷入口：执行质量检查，返回问题列表

    Args:
        stage: 阶段名（after_prepare / after_portrait / after_produce / after_post）
        project_dir: 项目目录
        episode: 集数（after_produce/after_post 需要）

    Returns:
        [{"id": str, "name": str, "severity": "error"|"warning", "message": str}, ...]
    """
    gate = QualityGate()
    return gate.check(stage, project_dir, episode=episode)


class QualityGate:
    """管线质量门禁

    检查阶段：
    - after_prepare: 翻译完整性、Prompt 有效性
    - after_portrait: 定妆照存在性、文件质量
    - after_produce: 首帧/视频/音频完整性
    - after_post: 最终成片
    """

    def check(self, stage: str, project_dir: str, *, episode: int | None = None) -> list[dict]:
        """执行质量检查

        Args:
            stage: 阶段名
            project_dir: 项目目录
            episode: 集数

        Returns:
            问题列表（空列表 = 全部通过）
        """
        checks = self._get_checks(stage)
        if not checks:
            return []

        issues = []
        for check_id, name, severity, checker in checks:
            try:
                result = checker(project_dir, episode)
                if not result.get("ok", True):
                    issues.append({
                        "id": check_id,
                        "name": name,
                        "severity": severity,
                        "message": result.get("message", "检查失败"),
                        "details": result.get("details", []),
                    })
            except Exception as e:
                logger.warning(f"质量检查 {check_id} 异常: {e}")
                issues.append({"id": check_id, "name": name, "severity": "warning",
                               "message": f"检查异常: {e}"})

        return issues

    def _get_checks(self, stage: str) -> list[tuple]:
        """获取指定阶段的检查项列表"""
        checks_map = {
            "after_prepare": [
                ("translation_complete", "翻译完整性", "warning", self._check_translation_complete),
                ("prompt_valid", "Prompt 有效性", "warning", self._check_prompt_valid),
            ],
            "after_portrait": [
                ("portrait_exists", "定妆照存在", "error", self._check_portrait_exists),
                ("portrait_quality", "定妆照质量", "warning", self._check_portrait_quality),
            ],
            "after_produce": [
                ("all_frames", "首帧完整", "error", self._check_all_frames),
                ("all_videos", "视频完整", "error", self._check_all_videos),
                ("all_audio", "音频完整", "warning", self._check_all_audio),
            ],
            "after_post": [
                ("final_video", "最终成片", "error", self._check_final_video),
            ],
        }
        return checks_map.get(stage, [])

    # ══════════════════════════════════════════════════════════
    #  after_prepare 检查
    # ══════════════════════════════════════════════════════════

    def _check_translation_complete(self, project_dir: str, episode: int | None) -> dict:
        """检查翻译完整性：所有角色/场景/分镜都有英文版"""
        from infra.config import ProjectPaths, load_yaml_entities
        from infra.constants import is_ascii_only
        paths = ProjectPaths(project_dir)
        missing = []

        # 角色
        chars = load_yaml_entities(paths.characters_dir, "character")
        for char in chars:
            prompt_en = char.get("appearance_prompt_en", "")
            if not prompt_en:
                missing.append(f"角色 {char.get('name', char.get('id', '?'))} 缺英文外貌 prompt")
            elif not is_ascii_only(prompt_en):
                missing.append(f"角色 {char.get('name', char.get('id', '?'))} 的 appearance_prompt_en 仍为中文")

        # 场景
        scenes = load_yaml_entities(paths.scenes_dir, "scene")
        for scene in scenes:
            desc_en = scene.get("description_en", "")
            if not desc_en:
                missing.append(f"场景 {scene.get('name', scene.get('id', '?'))} 缺英文描述")
            elif not is_ascii_only(desc_en):
                missing.append(f"场景 {scene.get('name', scene.get('id', '?'))} 的 description_en 仍为中文")

        if missing:
            return {"ok": False, "message": f"{len(missing)} 项未翻译", "details": missing}
        return {"ok": True}

    def _check_prompt_valid(self, project_dir: str, episode: int | None) -> dict:
        """检查 Prompt 有效性：角色 prompt 长度 > 50 字符"""
        from infra.config import ProjectPaths, load_yaml_entities
        paths = ProjectPaths(project_dir)
        issues = []

        chars = load_yaml_entities(paths.characters_dir, "character")
        for char in chars:
            prompt_en = char.get("appearance_prompt_en", "")
            name = char.get("name", char.get("id", "?"))
            if not prompt_en:
                issues.append(f"角色 {name} 无英文 prompt")
            elif len(prompt_en) < 50:
                issues.append(f"角色 {name} prompt 过短 ({len(prompt_en)} 字符)")

        if issues:
            return {"ok": False, "message": f"{len(issues)} 个 prompt 质量不足", "details": issues}
        return {"ok": True}

    # ══════════════════════════════════════════════════════════
    #  after_portrait 检查
    # ══════════════════════════════════════════════════════════

    def _check_portrait_exists(self, project_dir: str, episode: int | None) -> dict:
        """检查定妆照存在：所有角色都有 cover.png"""
        from infra.config import ProjectPaths, load_yaml_entities
        paths = ProjectPaths(project_dir)
        missing = []

        chars = load_yaml_entities(paths.characters_dir, "character")
        for char in chars:
            cid = char.get("id", "")
            if not cid:
                continue
            cover = paths.character_asset_dir(cid) / "cover.png"
            if not cover.exists():
                missing.append(f"角色 {char.get('name', cid)} 无定妆照")

        if missing:
            return {"ok": False, "message": f"{len(missing)} 个角色缺定妆照", "details": missing}
        return {"ok": True}

    def _check_portrait_quality(self, project_dir: str, episode: int | None) -> dict:
        """检查定妆照质量：文件大小 > 50KB"""
        from infra.config import ProjectPaths, load_yaml_entities
        paths = ProjectPaths(project_dir)
        issues = []

        chars = load_yaml_entities(paths.characters_dir, "character")
        for char in chars:
            cid = char.get("id", "")
            if not cid:
                continue
            cover = paths.character_asset_dir(cid) / "cover.png"
            if cover.exists():
                size_kb = cover.stat().st_size / 1024
                if size_kb < 50:
                    issues.append(f"角色 {char.get('name', cid)} 定妆照过小 ({size_kb:.0f}KB)")

        if issues:
            return {"ok": False, "message": f"{len(issues)} 个定妆照质量不足", "details": issues}
        return {"ok": True}

    # ══════════════════════════════════════════════════════════
    #  after_produce 检查
    # ══════════════════════════════════════════════════════════

    def _check_all_frames(self, project_dir: str, episode: int | None) -> dict:
        """检查首帧完整：所有镜头都有 frame.png"""
        if episode is None:
            return {"ok": True}
        from infra.config import ProjectPaths
        paths = ProjectPaths(project_dir)
        out_dir = paths.episode_dir(episode)
        if not out_dir.exists():
            return {"ok": False, "message": f"第{episode}集输出目录不存在"}

        missing = []
        for shot_dir in sorted(out_dir.glob("s*")):
            if not (shot_dir / "frame.png").exists():
                missing.append(shot_dir.name)

        if missing:
            return {"ok": False, "message": f"{len(missing)} 个镜头缺首帧", "details": missing}
        return {"ok": True}

    def _check_all_videos(self, project_dir: str, episode: int | None) -> dict:
        """检查视频完整：所有镜头都有 video.mp4"""
        if episode is None:
            return {"ok": True}
        from infra.config import ProjectPaths
        paths = ProjectPaths(project_dir)
        out_dir = paths.episode_dir(episode)
        if not out_dir.exists():
            return {"ok": False, "message": f"第{episode}集输出目录不存在"}

        missing = []
        for shot_dir in sorted(out_dir.glob("s*")):
            if not (shot_dir / "video.mp4").exists():
                missing.append(shot_dir.name)

        if missing:
            return {"ok": False, "message": f"{len(missing)} 个镜头缺视频", "details": missing}
        return {"ok": True}

    def _check_all_audio(self, project_dir: str, episode: int | None) -> dict:
        """检查音频完整：有台词的镜头都有 audio.wav"""
        if episode is None:
            return {"ok": True}
        from infra.config import ProjectPaths
        from engines.storyboard import load_storyboard
        paths = ProjectPaths(project_dir)
        out_dir = paths.episode_dir(episode)
        if not out_dir.exists():
            return {"ok": True}  # 目录不存在时跳过（produce 未开始）

        shots = load_storyboard(episode=episode)
        missing = []
        for shot in shots:
            sid = shot.get("shot_id", "")
            dialogue = shot.get("dialogue", "").strip()
            if not sid or not dialogue or set(dialogue) <= {".", "…"}:
                continue
            audio = out_dir / f"s{sid}" / "audio.wav"
            if not audio.exists():
                missing.append(sid)

        if missing:
            return {"ok": False, "message": f"{len(missing)} 个有台词镜头缺音频", "details": missing}
        return {"ok": True}

    # ══════════════════════════════════════════════════════════
    #  after_post 检查
    # ══════════════════════════════════════════════════════════

    def _check_final_video(self, project_dir: str, episode: int | None) -> dict:
        """检查最终成片"""
        if episode is None:
            return {"ok": True}
        from infra.config import ProjectPaths
        paths = ProjectPaths(project_dir)
        final = paths.episode_final(episode)
        if not final.exists():
            return {"ok": False, "message": f"第{episode}集成片不存在"}
        size_mb = final.stat().st_size / 1024 / 1024
        if size_mb < 0.1:
            return {"ok": False, "message": f"成片文件过小 ({size_mb:.1f}MB)"}
        return {"ok": True}
