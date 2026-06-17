"""Pydantic 数据模型 — API 请求/响应校验"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
import re

from infra.models import validate_id
from infra.constants import MIN_DURATION, MAX_DURATION
from infra.config.loader import CHARACTER_NAME_PATTERN

__all__ = [
    "StepRequest", "TTSRequest", "PostRequest", "MusicRequest",
    "SubtitleRequest", "PipelineRequest", "CharacterData", "SceneData",
    "ProjectCreate", "ProjectSwitch", "ConfigUpdate",
    "StoryboardGenRequest", "EntityGenRequest", "CharacterGenRequest", "SceneGenRequest", "ChatEditRequest",
    "SekoProposalRequest", "SekoProposalStatusRequest", "SekoProposalModifyRequest",
    "SekoImportRequest",
    "TrainingRequest",
    "PrepareRequest", "ImportPromptParams",
    "BatchDeleteRequest",
    "StoryboardBatchDeleteRequest",
    "StoryboardSaveRequest",
]


# ── 批量删除 ──

class BatchDeleteRequest(BaseModel):
    """通用批量删除请求（角色/场景）"""
    ids: list[str] = Field(..., min_length=1, max_length=200, description="要删除的 ID 列表")

    @field_validator("ids")
    @classmethod
    def validate_ids(cls, v: list[str]) -> list[str]:
        cleaned = [x.strip() for x in v if x.strip()]
        if not cleaned:
            raise ValueError("至少需要一个 ID")
        for x in cleaned:
            validate_id(x, allow_chinese=True)
        return cleaned


class StoryboardBatchDeleteRequest(BaseModel):
    """分镜表批量删除请求"""
    shot_ids: list[str] = Field(..., min_length=1, max_length=500, description="要删除的镜头 ID 列表")

    @field_validator("shot_ids")
    @classmethod
    def validate_shot_ids(cls, v: list[str]) -> list[str]:
        cleaned = [x.strip() for x in v if x.strip()]
        if not cleaned:
            raise ValueError("至少需要一个镜头 ID")
        for x in cleaned:
            validate_id(x)
        return cleaned


# ── 镜头步骤 ──

class StepRequest(BaseModel):
    """单镜头步骤执行请求"""
    episode: int = Field(..., ge=1, description="集数")
    shot_id: str = Field(..., min_length=1, max_length=20, description="镜头 ID")
    force: bool = Field(False, description="强制覆盖已有文件")

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("镜头 ID 只允许字母、数字、下划线、连字符")
        return v


# ── TTS ──

class TTSRequest(BaseModel):
    """语音合成请求"""
    text: str = Field(..., min_length=1, max_length=5000, description="合成文本")
    voice_config: dict | None = None
    emotion: str = Field("neutral", pattern=r"^[a-z_]+$")
    language: str = Field("zh", pattern=r"^[a-z]{2}$")


# ── 后期 ──

class PostRequest(BaseModel):
    """后期合成请求"""
    episode: int = Field(..., ge=1)
    vertical: bool = False


# ── 配乐 ──

class MusicRequest(BaseModel):
    """配乐生成请求"""
    duration: float = Field(..., gt=0, le=600, description="时长（秒）")
    mood: str = Field("neutral", max_length=50)


# ── 字幕 ──

class SubtitleRequest(BaseModel):
    """字幕生成请求"""
    episode: int = Field(..., ge=1)


# ── 管线 ──

class PipelineRequest(BaseModel):
    """管线执行请求"""
    episode: int = Field(..., ge=1)
    command: str = Field("produce", pattern=r"^(preview|prepare|entities|produce|post|run_all)$")
    level: str = Field("draft", pattern=r"^(draft|standard|high)$")
    vertical: bool = False
    force: bool = Field(False, description="强制覆盖已有文件")


# ── 角色 ──

class CharacterData(BaseModel):
    """角色数据（创建/更新）"""
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field("", max_length=100, pattern=CHARACTER_NAME_PATTERN,
                      description="角色名，括号外不允许含逗号（括号内逗号不受限）")
    gender: str = Field("", max_length=10)
    appearance: str = Field("", max_length=2000)
    voice: dict | None = None
    outfits: dict | None = None
    reference_images: list[str] | None = None
    appearance_prompt_en: str = Field("", max_length=4000, description="英文外貌 prompt（LLM 生成或翻译）")
    body_features: str = Field("", max_length=2000, description="身体特征（纹身/伤疤等）")
    bible: dict | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_id(v, allow_chinese=True)


# ── 场景 ──

class SceneData(BaseModel):
    """场景数据（创建/更新）"""
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field("", max_length=100)
    description: str = Field("", max_length=2000)
    lighting: str = Field("", max_length=200)
    reference_images: list[str] | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_id(v, allow_chinese=True)


# ── 项目 ──

class ProjectCreate(BaseModel):
    """项目创建请求"""
    name: str = Field(..., min_length=1, max_length=100)
    style: str = Field("cinematic", max_length=50, description="视觉风格")
    genre: str = Field("urban", max_length=50, description="题材类型")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff]+$", v):
            raise ValueError("项目名只允许字母、数字、中文、下划线、连字符")
        return v


class ProjectSwitch(BaseModel):
    """项目切换请求"""
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("项目名包含非法字符")
        return v


# ── 配置 ──

class ConfigUpdate(BaseModel):
    """配置更新 — 统一格式: {"data": {...}}"""
    data: dict = Field(..., description="配置数据")

    def get_config_data(self) -> dict:
        return self.data


class SystemConfigUpdate(BaseModel):
    """系统全局配置更新 — 白名单字段 + 类型校验"""
    models: dict | None = None
    comfyui: dict | None = None
    llm: dict | None = None
    seko: dict | None = None
    training: dict | None = None
    server: dict | None = None
    post_production: dict | None = None
    timeouts: dict | None = None
    generation: dict | None = None

    def to_filtered_dict(self) -> dict:
        """返回非空字段的 dict"""
        return self.model_dump(exclude_none=True)


# ── LLM 生成 ──

class StoryboardGenRequest(BaseModel):
    """分镜 AI 生成请求"""
    episode: int = Field(1, ge=1, description="集数")
    outline: str = Field(..., min_length=10, max_length=10000, description="剧情大纲")
    duration: int = Field(90, ge=10, le=3600, description="目标时长（秒）")
    append: bool = Field(False, description="追加到现有分镜表")


class EntityGenRequest(BaseModel):
    """AI 实体生成请求 — 从分镜提取引用，批量生成缺失的角色/场景"""
    episode: int = Field(1, ge=1, description="集数")


class CharacterGenRequest(BaseModel):
    """角色 AI 生成请求"""
    descriptions: list[str] = Field(..., min_length=1, max_length=10, description="角色描述列表")

    @field_validator("descriptions")
    @classmethod
    def validate_descs(cls, v: list[str]) -> list[str]:
        result = [d.strip() for d in v if d.strip()]
        if not result:
            raise ValueError("描述不能为空")
        return result


class SceneGenRequest(BaseModel):
    """场景 AI 生成请求"""
    descriptions: list[str] = Field(..., min_length=1, max_length=10, description="场景描述列表")

    @field_validator("descriptions")
    @classmethod
    def validate_descs(cls, v: list[str]) -> list[str]:
        result = [d.strip() for d in v if d.strip()]
        if not result:
            raise ValueError("描述不能为空")
        return result


class ChatEditRequest(BaseModel):
    """AI 对话编辑请求"""
    episode: int = Field(1, ge=1, description="集数")
    message: str = Field(..., min_length=1, max_length=10000, description="编辑指令")
    shots: list[dict] = Field(default_factory=list, max_length=500, description="当前分镜表")


# ── Seko 影视策划案 ──

class SekoProposalRequest(BaseModel):
    """Seko 策划案生成请求"""
    prompt: str = Field(..., min_length=1, max_length=10000, description="策划案描述/故事梗概")
    api_key: str = Field("", description="Seko API Key（可选，默认从环境变量读取）")


class SekoProposalStatusRequest(BaseModel):
    """Seko 策划案状态查询"""
    task_id: str = Field(..., min_length=1, description="策划案任务 ID")
    api_key: str = Field("", description="Seko API Key（可选）")
    wait: bool = Field(False, description="是否轮询等待完成")
    interval: int = Field(10, ge=5, le=120, description="轮询间隔（秒）")
    download_dir: str = Field("", description="图片下载目录（留空则不下载）")


class SekoProposalModifyRequest(BaseModel):
    """Seko 策划案修改请求"""
    task_id: str = Field(..., min_length=1, description="原策划案任务 ID")
    prompt: str = Field(..., min_length=1, max_length=10000, description="修改指令")
    api_key: str = Field("", description="Seko API Key（可选）")


class SekoImportRequest(BaseModel):
    """Seko 策划案导入请求"""
    proposal_data: dict = Field(..., description="Seko 策划案完整 JSON（含 steps + elements）")
    episode: int = Field(1, ge=1, description="导入到第几集")
    import_characters: bool = Field(True, description="是否导入角色")
    import_scenes: bool = Field(True, description="是否导入场景")
    import_storyboard: bool = Field(True, description="是否导入分镜")
    download_images: bool = Field(True, description="是否下载角色/场景图片")
    project_name: str = Field("", max_length=100, description="创建新项目并导入（留空则导入当前项目）")


# ── LoRA 训练 ──

class TrainingRequest(BaseModel):
    """LoRA 训练请求"""
    char_id: str = Field(..., min_length=1, max_length=50, description="角色 ID")
    steps: int = Field(600, ge=100, le=10000, description="训练步数")
    learning_rate: float = Field(1e-4, gt=0, le=1, description="学习率")
    rank: int = Field(16, ge=4, le=128, description="LoRA rank")
    resolution: str = Field("512x768", description="训练分辨率")
    force: bool = Field(False, description="强制覆盖已有 LoRA")

    @field_validator("char_id")
    @classmethod
    def validate_char_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$", v):
            raise ValueError("角色 ID 只允许字母、数字、中文、下划线、连字符")
        return v


# ── 准备阶段 ──

class PrepareRequest(BaseModel):
    """准备阶段请求 — 批量预翻译"""
    episode: int = Field(1, ge=1, description="集数")
    force: bool = Field(False, description="强制覆盖已有翻译")
    translate: bool = Field(True, description="是否批量翻译")


class ImportPromptParams(BaseModel):
    """导入提示词模板参数 — 消除 get_import_prompt_template 的 10 个参数"""
    project_name: str = Field("我的短剧", max_length=100)
    style: str = Field("cinematic", max_length=50)
    genre: str = Field("urban", max_length=50)
    duration: int = Field(90, ge=10, le=600)
    episode: int = Field(1, ge=1)
    shot_start: int = Field(1, ge=1)
    shot_end: int = Field(50, ge=1)
    last_shot_info: str = Field("", max_length=2000)
    template_id: str = Field("", max_length=100)
    mode: str = Field("", max_length=20)


# ── 分镜保存 ──

class StoryboardShotData(BaseModel):
    """单个镜头数据（保存用）"""
    shot_id: str = Field("", max_length=20)
    scene_name: str = Field("", max_length=50)
    characters: str = Field("", max_length=100)
    action: str = Field("", max_length=500)
    dialogue: str = Field("", max_length=500)
    action_en: str = Field("", max_length=2000)
    dialogue_en: str = Field("", max_length=1000)
    camera: str = Field("", max_length=50)
    shot_type: str = Field("", max_length=50)
    duration: float = Field(4.0, ge=float(MIN_DURATION), le=float(MAX_DURATION))
    emotion: str = Field("neutral", max_length=30)
    outfit: str = Field("default", max_length=50)

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, v: str) -> str:
        if v and not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("shot_id 只允许字母、数字、下划线、连字符")
        return v


class StoryboardSaveRequest(BaseModel):
    """分镜表保存请求"""
    shots: list[StoryboardShotData] = Field(default_factory=list, max_length=500, description="镜头列表")


# ══════════════════════════════════════════════════════════
#  剧本导入 — 统一翻译字段定义 + 校验 + 翻译状态检测
# ══════════════════════════════════════════════════════════

# 翻译字段映射 — 唯一真相源

