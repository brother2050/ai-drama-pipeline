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
import re
from infra.config import ProjectPaths

logger = logging.getLogger(__name__)

__all__ = ["QualityGate", "check_quality"]

# 中文字符正则（CJK 统一汉字 + 扩展 A/B）
_CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')


def _is_mostly_chinese(text: str, threshold: float = 0.3) -> bool:
    """判断文本是否主要为中文（中文字符占比超阈值）

    替代 str.isascii() 的误判：LLM 翻译后偶尔保留"U盘"等专有名词，
    isascii() 会因单个非 ASCII 字符将整段英文判定为中文。
    """
    if not text:
        return False
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / len(text) > threshold


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

    def __init__(self):
        self._chars_cache: dict | None = None
        self._scenes_cache: dict | None = None

    @staticmethod
    def _paths(project_dir: str):
        return ProjectPaths(project_dir)

    def _load_chars_scenes(self, project_dir: str):
        """加载角色/场景数据（带实例级缓存，同一次 check() 调用内复用）"""
        if self._chars_cache is not None and self._scenes_cache is not None:
            return self._chars_cache, self._scenes_cache
        from infra.config import load_project_entities
        chars, scenes = load_project_entities(project_dir)
        self._chars_cache = chars
        self._scenes_cache = scenes
        return chars, scenes

    def check(self, stage: str, project_dir: str, *, episode: int | None = None) -> list[dict]:
        """执行质量检查

        Args:
            stage: 阶段名
            project_dir: 项目目录
            episode: 集数

        Returns:
            问题列表（空列表 = 全部通过）
        """
        self._chars_cache = None
        self._scenes_cache = None
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
                ("lipsync_complete", "口型同步完整", "warning", self._check_all_lipsync),
                ("final_video", "最终成片", "error", self._check_final_video),
            ],
        }
        return checks_map.get(stage, [])

    # ══════════════════════════════════════════════════════════
    #  after_prepare 检查
    # ══════════════════════════════════════════════════════════

    def _check_translation_complete(self, project_dir: str, episode: int | None) -> dict:
        """检查翻译完整性：所有角色/场景/分镜都有英文版"""
        chars, scenes = self._load_chars_scenes(project_dir)
        missing = []

        for char in chars.values():
            prompt_en = char.get("appearance_prompt_en", "")
            if not prompt_en:
                missing.append(f"角色 {char.get('name', char.get('id', '?'))} 缺英文外貌 prompt")
            elif _is_mostly_chinese(prompt_en):
                missing.append(f"角色 {char.get('name', char.get('id', '?'))} 的 appearance_prompt_en 仍为中文")
            # 检查服装描述翻译
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict):
                for okey, odata in outfits.items():
                    if isinstance(odata, dict) and odata.get("description") and not odata.get("description_en"):
                        missing.append(f"角色 {char.get('name', char.get('id', '?'))} 的服装 '{okey}' 缺英文描述")

        for scene in scenes.values():
            desc_en = scene.get("description_en", "")
            if not desc_en:
                missing.append(f"场景 {scene.get('name', scene.get('id', '?'))} 缺英文描述")
            elif _is_mostly_chinese(desc_en):
                missing.append(f"场景 {scene.get('name', scene.get('id', '?'))} 的 description_en 仍为中文")
            lighting = scene.get("lighting", "")
            lighting_en = scene.get("lighting_en", "")
            if lighting and not lighting_en:
                missing.append(f"场景 {scene.get('name', scene.get('id', '?'))} 缺英文光照描述")

        if missing:
            return {"ok": False, "message": f"{len(missing)} 项未翻译", "details": missing}
        return {"ok": True}

    def _check_prompt_valid(self, project_dir: str, episode: int | None) -> dict:
        """检查 Prompt 有效性：角色 prompt tag 数 ≥ 3（逗号分隔的短语）"""
        chars, _ = self._load_chars_scenes(project_dir)
        issues = []

        for char in chars.values():
            prompt_en = char.get("appearance_prompt_en", "")
            name = char.get("name", char.get("id", "?"))
            if not prompt_en:
                issues.append(f"角色 {name} 无英文 prompt")
            else:
                tags = [t.strip() for t in prompt_en.split(",") if t.strip()]
                if len(tags) < 3:
                    issues.append(f"角色 {name} prompt 过短 ({len(tags)} 个 tag, {len(prompt_en)} 字符)")

        if issues:
            return {"ok": False, "message": f"{len(issues)} 个 prompt 质量不足", "details": issues}
        return {"ok": True}

    # ══════════════════════════════════════════════════════════
    #  after_portrait 检查
    # ══════════════════════════════════════════════════════════

    def _check_portrait_exists(self, project_dir: str, episode: int | None) -> dict:
        """检查定妆照存在：所有角色都有 cover.png"""
        paths = self._paths(project_dir)
        chars, _ = self._load_chars_scenes(project_dir)
        missing = []

        for char in chars.values():
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
        """检查定妆照质量：文件大小 > 50KB + PNG 完整性"""
        paths = self._paths(project_dir)
        chars, _ = self._load_chars_scenes(project_dir)
        issues = []

        for char in chars.values():
            cid = char.get("id", "")
            if not cid:
                continue
            cover = paths.character_asset_dir(cid) / "cover.png"
            if cover.exists():
                size_kb = cover.stat().st_size / 1024
                if size_kb < 50:
                    issues.append(f"角色 {char.get('name', cid)} 定妆照过小 ({size_kb:.0f}KB)")
                else:
                    # 校验 PNG 文件头（magic bytes）
                    try:
                        with open(cover, "rb") as f:
                            magic = f.read(8)
                        if magic != b'\x89PNG\r\n\x1a\n':
                            issues.append(f"角色 {char.get('name', cid)} 定妆照文件损坏（非有效 PNG）")
                    except OSError:
                        issues.append(f"角色 {char.get('name', cid)} 定妆照读取失败")

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
        paths = self._paths(project_dir)
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
        paths = self._paths(project_dir)
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
        from engines.content.storyboard import load_storyboard
        import string
        paths = self._paths(project_dir)
        out_dir = paths.episode_dir(episode)
        if not out_dir.exists():
            return {"ok": True}  # 目录不存在时跳过（produce 未开始）

        shots = load_storyboard(episode=episode)
        missing = []
        for shot in shots:
            sid = shot.get("shot_id", "")
            dialogue = shot.get("dialogue", "").strip()
            if not sid or not dialogue:
                continue
            # 剥离标点/空白/省略号后检查是否有实质内容
            strip_chars = string.whitespace + string.punctuation + '…—。，、！？：；""''「」'
            meaningful = dialogue.strip(strip_chars)
            if not meaningful:
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

    def _check_all_lipsync(self, project_dir: str, episode: int | None) -> dict:
        """检查口型同步完整：有音频的镜头都有 synced.mp4"""
        if episode is None:
            return {"ok": True}
        from engines.content.storyboard import load_storyboard
        paths = self._paths(project_dir)
        shots = load_storyboard(episode)
        out_dir = paths.episode_dir(episode)
        missing = []
        for shot in shots:
            sid = shot.get("shot_id", "")
            dialogue = shot.get("dialogue", "").strip()
            if not sid or not dialogue or set(dialogue) <= {".", "…", " ", "-", "—", "~"}:
                continue
            synced = out_dir / f"s{sid}" / "synced.mp4"
            if not synced.exists():
                missing.append(sid)
        if missing:
            return {"ok": False, "message": f"{len(missing)} 个有台词镜头缺口型同步视频", "details": missing}
        return {"ok": True}

    def _check_final_video(self, project_dir: str, episode: int | None) -> dict:
        """检查最终成片"""
        if episode is None:
            return {"ok": True}
        paths = self._paths(project_dir)
        final = paths.episode_final(episode)
        if not final.exists():
            return {"ok": False, "message": f"第{episode}集成片不存在"}
        size_mb = final.stat().st_size / 1024 / 1024
        if size_mb < 0.1:
            return {"ok": False, "message": f"成片文件过小 ({size_mb:.1f}MB)"}
        return {"ok": True}
