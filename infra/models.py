"""共享数据模型 — Web 和 Pipeline 共用的 Pydantic 模型

将导入相关的纯数据模型从 web/schemas 中提取，
消除 pipeline → web 的跨层依赖。

拆分后：
- 模型定义保留在此文件
- 校验逻辑 → infra/validation.py
- 规范化逻辑 → infra/normalize.py

向后兼容：此文件重新导出所有公共 API。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from infra.constants import MIN_DURATION, MAX_DURATION
from infra.config.loader import CHARACTER_NAME_PATTERN

__all__ = [
    "ImportOutfit", "ImportCharacter", "ImportScene",
    "ImportShot", "ImportPlan", "ImportValidator", "get_translation_status",
    "normalize_character", "validate_id",
]

# ── 向后兼容：从拆分后的模块重新导出 ─────────────────────
# 所有原有 import 路径保持不变。
from infra.validation import ImportValidator, get_translation_status, validate_id  # noqa: E402, F401
from infra.normalize import normalize_character, normalize_scene, name_to_id  # noqa: E402, F401

__all__ += ["normalize_scene", "name_to_id"]


# ── 导入子模型 ──────────────────────────────────────────

class ImportOutfit(BaseModel):
    """导入服装数据"""
    description: str = Field(..., min_length=1, max_length=500)
    description_en: str = Field("", max_length=1000, description="英文服装描述（可选，跳过 prepare 翻译）")


class ImportCharacter(BaseModel):
    """导入角色数据"""
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100, pattern=CHARACTER_NAME_PATTERN,
                      description="角色名，括号外不允许含逗号（括号内逗号不受限）")
    gender: str = Field("", max_length=10)
    age: str = Field("", max_length=10)
    appearance: str = Field(..., min_length=10, max_length=2000)
    outfits: dict[str, ImportOutfit] | None = None
    bible: dict | None = None
    # ── 可选：预翻译（提供则跳过 prepare） ──
    appearance_prompt_en: str = Field("", max_length=4000, description="英文外貌 prompt（可选）")
    body_features: str = Field("", max_length=2000, description="身体特征（伤疤/纹身等，可选）")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_id(v, allow_chinese=True)


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
        return validate_id(v, allow_chinese=True)


class ImportShot(BaseModel):
    """导入镜头数据"""
    episode: int = Field(1, ge=1)
    shot_id: str = Field(..., min_length=1, max_length=20)
    scene_name: str = Field(..., min_length=1, max_length=50, description="场景名称（与场景 YAML 的 name 一致）")
    characters: str = Field("", max_length=100)
    action: str = Field(..., min_length=5, max_length=500)
    dialogue: str = Field("......", max_length=500)
    camera: str = Field("", max_length=50)
    shot_type: str = Field("", max_length=50)
    duration: float = Field(4.0, ge=float(MIN_DURATION), le=float(MAX_DURATION))
    emotion: str = Field("neutral", max_length=30)
    outfit: str = Field("default", max_length=50)
    # ── 可选：预翻译（提供则跳过 prepare） ──
    action_en: str = Field("", max_length=2000, description="英文画面描述（可选，用于 AI 绘图 prompt）")
    dialogue_en: str = Field("", max_length=1000, description="英文台词（可选）")

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("shot_id 只允许字母、数字、下划线、连字符")
        return v

    @field_validator("characters")
    @classmethod
    def validate_characters(cls, v: str) -> str:
        """规范化 characters 字段：清理多余 + 号和空白"""
        if not v:
            return v
        parts = [p.strip() for p in v.split("+") if p.strip()]
        return "+".join(parts)

    @field_validator("duration", mode="before")
    @classmethod
    def coerce_duration(cls, v):
        """兼容 LLM 返回 str/int/float，统一转为 float"""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 4.0
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
