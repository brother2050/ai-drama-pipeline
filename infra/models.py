"""共享数据模型 — Web 和 Pipeline 共用的 Pydantic 模型

将导入相关的纯数据模型和校验逻辑从 web/schemas 中提取，
消除 pipeline → web 的跨层依赖。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

__all__ = [
    "ImportOutfit", "ImportCharacter", "ImportScene",
    "ImportShot", "ImportPlan", "ImportValidator", "get_translation_status",
    "normalize_character",
]


# ── 导入子模型 ──────────────────────────────────────────

class ImportOutfit(BaseModel):
    """导入服装数据"""
    description: str = Field(..., min_length=1, max_length=500)
    description_en: str = Field("", max_length=1000, description="英文服装描述（可选，跳过 prepare 翻译）")


class ImportCharacter(BaseModel):
    """导入角色数据"""
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    gender: str = Field("", max_length=10)
    age: str = Field("", max_length=10)
    appearance: str = Field(..., min_length=10, max_length=2000)
    outfits: dict[str, ImportOutfit] | None = None
    # ── 可选：预翻译（提供则跳过 prepare） ──
    appearance_prompt_en: str = Field("", max_length=4000, description="英文外貌 prompt（可选）")
    body_features: str = Field("", max_length=2000, description="身体特征（伤疤/纹身/胎记等，可选）")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("角色 ID 只允许字母、数字、下划线、连字符")
        return v


class ImportScene(BaseModel):
    """导入场景数据"""
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=10, max_length=2000)
    lighting: str = Field("", max_length=200)
    # ── 可选：预翻译（提供则跳过 prepare） ──
    description_en: str = Field("", max_length=4000, description="英文场景描述（可选）")
    lighting_en: str = Field("", max_length=400, description="英文光照描述（可选）")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("场景 ID 只允许字母、数字、下划线、连字符")
        return v


class ImportShot(BaseModel):
    """导入镜头数据"""
    episode: int = Field(1, ge=1)
    shot_id: str = Field(..., min_length=1, max_length=20)
    scene_id: str = Field(..., min_length=1, max_length=50)
    characters: str = Field("", max_length=100)
    action: str = Field(..., min_length=5, max_length=500)
    dialogue: str = Field("......", max_length=500)
    camera: str = Field("", max_length=50)
    shot_type: str = Field("", max_length=50)
    duration: int = Field(4, ge=2, le=8)
    emotion: str = Field("neutral", max_length=30)
    outfit: str = Field("default", max_length=50)
    language: str = Field("zh", max_length=5)
    # ── 可选：预翻译（提供则跳过 prepare） ──
    action_en: str = Field("", max_length=2000, description="英文画面描述（可选，用于 AI 绘图 prompt）")
    dialogue_en: str = Field("", max_length=1000, description="英文台词（可选）")

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("shot_id 只允许字母、数字、下划线、连字符")
        return v

    @field_validator("duration", mode="before")
    @classmethod
    def coerce_duration(cls, v):
        """兼容 LLM 返回 str/int/float，统一转为 int"""
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 4
        return v


# ── 导入计划 ──────────────────────────────────────────

class ImportPlan(BaseModel):
    """完整的导入计划

    支持两种模式：
    - 全量导入：首次导入，创建新项目（characters + scenes + shots）
    - 追加导入：append=True，向已有项目追加 shots（characters/scenes 可选补充）

    翻译字段（_en 后缀）均为可选。提供则跳过 prepare 阶段的 LLM 翻译。
    """
    project_name: str = Field("", max_length=100)
    style: str = Field("cinematic", max_length=50)
    genre: str = Field("urban", max_length=50)
    synopsis: str = Field("", max_length=500)
    episodes: int = Field(1, ge=1, le=100)
    episodes_summary: str = Field("", max_length=2000, description="集数概要：每集镜头数分布，如 '共3集：第1集15个镜头，第2集20个镜头，第3集10个镜头'")
    characters: list[ImportCharacter] = Field(default_factory=list)
    scenes: list[ImportScene] = Field(default_factory=list)
    shots: list[ImportShot] = Field(default_factory=list)
    append: bool = Field(False, description="追加模式：向已有项目追加 shots，不覆盖已有数据")

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, v: str) -> str:
        if v and not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff]+$", v):
            raise ValueError("项目名只允许字母、数字、中文、下划线、连字符")
        return v


# ── 翻译状态检测 ──────────────────────────────────────

def get_translation_status(plan: ImportPlan) -> dict:
    """检测导入计划的翻译完整度

    Returns:
        {
            "complete": bool,
            "missing": {"characters": [...], "scenes": [...], "shots": [...]},
            "summary": str,
        }
    """
    missing_chars = [c.id for c in plan.characters if not c.appearance_prompt_en]
    missing_scenes = [s.id for s in plan.scenes if not s.description_en]
    missing_shots = [sh.shot_id for sh in plan.shots if not sh.action_en]

    all_complete = not missing_chars and not missing_scenes and not missing_shots
    parts = []
    if missing_chars:
        parts.append(f"{len(missing_chars)} 角色缺外貌 prompt")
    if missing_scenes:
        parts.append(f"{len(missing_scenes)} 场景缺英文描述")
    if missing_shots:
        parts.append(f"{len(missing_shots)} 镜头缺英文 action")

    return {
        "complete": all_complete,
        "missing": {
            "characters": missing_chars,
            "scenes": missing_scenes,
            "shots": missing_shots,
        },
        "summary": "翻译完整" if all_complete else "缺翻译: " + "、".join(parts),
    }


# ── 引用校验 ──────────────────────────────────────────

def _resolve_existing_ids(plan: ImportPlan, project_dir: Path | None,
                          existing_char_ids: set[str] | None,
                          existing_scene_ids: set[str] | None) -> tuple[set[str], set[str], set[str]]:
    """收集所有已知的角色/场景 ID + 已有镜头 ID"""
    from infra.config import ProjectPaths, load_yaml_entities

    char_ids = {c.id for c in plan.characters}
    scene_ids = {s.id for s in plan.scenes}
    if existing_char_ids:
        char_ids |= existing_char_ids
    if existing_scene_ids:
        scene_ids |= existing_scene_ids

    existing_shots: set[str] = set()
    if project_dir and project_dir.exists():
        paths = ProjectPaths(project_dir)
        char_ids |= {e["id"] for e in load_yaml_entities(paths.characters_dir, "character")}
        scene_ids |= {e["id"] for e in load_yaml_entities(paths.scenes_dir, "scene")}
        try:
            from infra.database.pool import get_pool
            from infra.database.storyboard_db import get_all_shots
            existing_shots = {r["shot_id"] for r in get_all_shots(get_pool()) if r.get("shot_id")}
        except Exception as e:
            logger.debug(f"读取已有镜头 ID 跳过: {e}")

    return char_ids, scene_ids, existing_shots


def _check_outfit_reference(shot, i: int, plan: ImportPlan, char_ids: set[str],
                            project_dir: Path | None) -> list[str]:
    """检查镜头中 outfit 引用是否有效"""
    errors = []
    if not (shot.outfit and shot.characters):
        return errors
    primary_char = shot.characters.split("+")[0].strip()
    char = next((c for c in plan.characters if c.id == primary_char), None)
    char_outfits = char.outfits if char else None
    if not char_outfits and project_dir and project_dir.exists():
        try:
            from infra.config import ProjectPaths as _PP, load_yaml_entities as _le
            for e in _le(_PP(project_dir).characters_dir, "character"):
                if e.get("id") == primary_char:
                    char_outfits = e.get("outfits", {})
                    break
        except Exception as e:
            logger.debug(f"查找角色 outfit 跳过: {e}")
    if char_outfits and shot.outfit and shot.outfit not in char_outfits:
        errors.append(f"shots[{i}].outfit: 角色 '{primary_char}' 没有名为 '{shot.outfit}' 的服装，可用: {list(char_outfits.keys())}")
    return errors


class ImportValidator:
    """引用一致性校验 — 合并 plan 内定义 + 已有项目数据"""

    @staticmethod
    def validate_references(
        plan: ImportPlan,
        project_dir: Path | None = None,
        existing_char_ids: set[str] | None = None,
        existing_scene_ids: set[str] | None = None,
    ) -> list[str]:
        errors = []
        char_ids, scene_ids, existing_shots = _resolve_existing_ids(
            plan, project_dir, existing_char_ids, existing_scene_ids)

        # 已有镜头重复检查
        for sid in existing_shots:
            if sid in {s.shot_id for s in plan.shots}:
                errors.append(f"shots: 镜头 ID '{sid}' 与已有项目重复")

        # shot_id 唯一性
        seen_ids: dict[str, int] = {}
        for i, shot in enumerate(plan.shots):
            if shot.shot_id in seen_ids:
                errors.append(f"shots[{i}].shot_id: 镜头 ID '{shot.shot_id}' 与 shots[{seen_ids[shot.shot_id]}] 重复")
            else:
                seen_ids[shot.shot_id] = i

        # episode 范围校验
        max_episode = plan.episodes if plan.episodes > 0 else 1
        for i, shot in enumerate(plan.shots):
            try:
                ep = int(shot.episode)
                if ep < 1 or ep > max_episode:
                    errors.append(f"shots[{i}].episode: 集数 '{shot.episode}' 超出范围 [1, {max_episode}]")
            except (ValueError, TypeError):
                errors.append(f"shots[{i}].episode: 无效的集数 '{shot.episode}'")

        # 引用完整性
        for i, shot in enumerate(plan.shots):
            if shot.scene_id and shot.scene_id not in scene_ids:
                errors.append(f"shots[{i}].scene_id: 引用的场景 '{shot.scene_id}' 不存在")
            if shot.characters:
                for cid in shot.characters.split("+"):
                    cid = cid.strip()
                    if cid and cid not in char_ids:
                        errors.append(f"shots[{i}].characters: 引用的角色 '{cid}' 不存在")
            errors.extend(_check_outfit_reference(shot, i, plan, char_ids, project_dir))

        return errors


# ── 角色数据规范化 ──────────────────────────────────────

def normalize_character(char: dict) -> dict:
    """规范化角色数据 — 统一格式，补全缺失字段

    适用场景：LLM 生成、Seko 导入、Web 手动创建。
    确保无论数据来源如何，输出格式一致。
    """
    # bible: 确保存在且有 core_traits
    bible = char.get("bible")
    if not isinstance(bible, dict):
        char["bible"] = {}
    char["bible"].setdefault("core_traits", "")

    # reference_images: 清理外部 URL，保留本地路径
    refs = char.get("reference_images")
    if isinstance(refs, list):
        char["reference_images"] = [r for r in refs if not (isinstance(r, str) and r.startswith("http"))]

    # outfits: 确保 default 键 + 统一格式
    outfits = char.get("outfits")
    if isinstance(outfits, dict):
        if "default" not in outfits and outfits:
            outfits["default"] = next(iter(outfits.values()))
        for k, v in outfits.items():
            if isinstance(v, str):
                outfits[k] = {"description": v, "reference_images": []}
            elif isinstance(v, dict):
                v.setdefault("description", "")
                v.setdefault("reference_images", [])
                v["reference_images"] = [r for r in v.get("reference_images", [])
                                         if not (isinstance(r, str) and r.startswith("http"))]
    elif outfits is None:
        char["outfits"] = {"default": {"description": "", "reference_images": []}}

    return char
