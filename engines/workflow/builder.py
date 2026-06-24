"""ComfyUI 工作流构建器 — 从镜头配置构建可执行工作流

职责:
- 加载 ComfyUI 工作流 JSON 模板
- 构建首帧生成工作流（含多角色一致性方案注入）
- 构建视频生成工作流
- 处理参考图上传映射

一致性方案注入逻辑已拆分到 workflow_inject.py。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from engines.utils.shot import parse_char_names
from engines.workflow.inject import (
    _next_suffix,
)
from engines.workflow.inject import (
    find_character_lora as _find_character_lora,
)
from engines.workflow.inject import (
    find_style_lora as _find_style_lora,
)
from engines.workflow.inject import (
    inject_lora as _inject_lora,
)
from engines.workflow.utils import (
    find_first_node,
    resolve_node_aliases,
    set_clip_text_prompts,
)
from infra.compute.gpu import get_generation_config as get_gpu_config
from infra.config import ProjectPaths
from infra.constants import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

__all__ = ["WorkflowBuilder", "WorkflowBuilderConfig"]


@dataclass
class WorkflowBuilderConfig:
    """工作流构建器配置 — 消除 __init__ 的 8 个参数"""
    config: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    project_dir: str = ""
    wf_dir: str = ""
    registry: object = None  # ModelRegistry 实例
    comfyui: object = None   # ComfyUI 后端实例
    container: object = None # DI 容器
    force: bool = False
    no_auto_gen: bool = False  # 禁止自动触发定妆照生成（防止递归）
    char_name_to_id: dict = field(default_factory=dict)  # 角色名→hash ID 映射


_wf_cache: dict[str, tuple[dict, float]] = {}  # 进程级缓存（按文件路径 key → (data, mtime)）


class WorkflowBuilder:
    """ComfyUI 工作流构建器"""

    def __init__(self, cfg: WorkflowBuilderConfig):
        self.config = cfg.config
        self.models = cfg.models
        self.project_dir = cfg.project_dir
        self._paths = ProjectPaths(cfg.project_dir)
        self.wf_dir = cfg.wf_dir or str(self._paths.workflows_dir)
        self.registry = cfg.registry
        self.comfyui = cfg.comfyui
        self._container = cfg.container  # 完整 DI 容器（优先使用）
        self.force = cfg.force
        self.no_auto_gen = cfg.no_auto_gen  # 禁止自动触发定妆照生成
        self._char_name_to_id = cfg.char_name_to_id  # 角色名→hash ID 映射
        self._refs_cache: dict[str, list[str]] = {}  # 角色参考图缓存（防并发重复查找）

    def _get_container(self) -> object:
        """获取容器：优先完整 DI 容器，回退到简单 dict"""
        if self._container:
            return self._container
        if self.comfyui:
            return {"image": self.comfyui}
        return None

    # ── 加载工作流 ──────────────────────────────────────────

    def _load_backend_wf(self, svc_type: str, wf_getter, default_backend: str, available_nodes: set[str]) -> dict:
        """加载指定服务类型的工作流（图像/视频统一入口）"""
        backend = self.models.get(f"{svc_type}_backend", default_backend)
        wf_name = wf_getter(backend)
        if not wf_name:
            logger.warning(f"未知 {svc_type}_backend '{backend}'，回退到 {default_backend}")
            wf_name = wf_getter(default_backend)
        if not wf_name:
            raise ValueError(f"{svc_type} 工作流未找到: backend='{backend}'，请检查 models_registry.yaml")
        wf = self._load_wf(wf_name)
        if not wf:
            raise ValueError(f"{svc_type} 工作流文件为空或不存在: {wf_name}")
        return resolve_node_aliases(wf, available_nodes)

    def load_workflows(self) -> None:
        """根据 image_backend / video_backend 加载对应工作流 JSON"""
        available_nodes: set[str] = set()
        if self.comfyui and hasattr(self.comfyui, 'get_available_node_types'):
            try:
                available_nodes = self.comfyui.get_available_node_types()
            except Exception as e:
                logger.debug(f"获取 ComfyUI 节点类型失败: {e}")
        self.available_nodes = available_nodes

        if not self.registry:
            from infra.config.registry import ModelRegistry
            self.registry = ModelRegistry()

        # 首帧 + 视频工作流（后端选择由 system.yaml 的 models 段统一定义）
        self.first_frame_wf = self._load_backend_wf(
            "image", self.registry.get_image_workflow, self.models.get("image_backend", "flux"), available_nodes)
        self.video_wf = self._load_backend_wf(
            "video", self.registry.get_video_workflow, self.models.get("video_backend", "cosmos-video"), available_nodes)

        # GPU 适配
        gpu_cfg = get_gpu_config(config=self.config)
        sampler_types = {"KSampler", "KSamplerAdvanced", "BasicScheduler"}
        for svc in ("image", "video"):
            for bname in self.registry.list_backend_names(svc):
                sn = (self.registry.get_sampler_node(bname) if svc == "image"
                      else self.registry.get_video_sampler_node(bname))
                if sn:
                    sampler_types.add(sn)
        if self.first_frame_wf:
            self._apply_gpu(self.first_frame_wf, "first_frame", gpu_cfg, sampler_types)
        if self.video_wf:
            self._apply_gpu(self.video_wf, "video", gpu_cfg, sampler_types)

    def _load_wf(self, name: str) -> dict:
        # 进程级缓存：mtime 变化时自动重载
        path = os.path.join(self.wf_dir, name)
        if os.path.exists(path):
            cache_key = os.path.normpath(path)
        else:
            from infra.config.core import REPO_WORKFLOWS_DIR
            root_wf = str(REPO_WORKFLOWS_DIR / name)
            root_wf = os.path.normpath(root_wf)
            if os.path.exists(root_wf):
                cache_key = root_wf
                path = root_wf
            else:
                logger.debug(f"工作流不存在: {path} (也检查了 {root_wf})")
                return {}
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        if cache_key in _wf_cache:
            data, cached_mtime = _wf_cache[cache_key]
            if cached_mtime == mtime:
                return data
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _wf_cache[cache_key] = (data, mtime)
        return data

    def _apply_gpu(self, wf: dict, stage: str, gpu_cfg: dict, sampler_types: set[str]) -> None:
        """应用生成参数到工作流（比例自动计算分辨率 + 步数可选覆盖）

        用户配置 generation.aspect_ratio（如 "16:9", "9:16", "1:1"），
        代码读取 JSON 模板的原生分辨率，保持长边不变，按比例计算新分辨率。

        优先级:
          generation.resolution（精确值）> generation.aspect_ratio（比例计算）> JSON 原生值
        """
        resolution = gpu_cfg.get("resolution")
        aspect_ratio = gpu_cfg.get("aspect_ratio")
        image_steps = gpu_cfg.get("image_steps")

        _RESIZE_NODES = {
            "EmptyLatentImage": (1024, 576),
            "EmptySD3LatentImage": (1024, 576),
            "ImageScale": (768, 768),
        }

        for _, node in wf.items():
            ct = node.get("class_type", "")
            inp = node.get("inputs", {})

            # 分辨率 → EmptyLatentImage / ImageScale
            defaults = _RESIZE_NODES.get(ct)
            if defaults:
                native_w = inp.get("width", defaults[0])
                native_h = inp.get("height", defaults[1])
                if resolution and len(resolution) == 2:
                    inp["width"] = resolution[0]
                    inp["height"] = resolution[1]
                elif aspect_ratio:
                    target_w, target_h = self._calc_resolution(native_w, native_h, aspect_ratio)
                    inp["width"] = target_w
                    inp["height"] = target_h

            # 步数 → 所有采样器节点（仅首帧）
            if ct in sampler_types and stage == "first_frame":
                if image_steps:
                    inp["steps"] = image_steps

        # 视频帧数由 build_video() → _apply_duration() 根据镜头 duration 动态计算，
        # 不再从 generation.video_frames 硬编码读取。

        # 检测未覆盖的 latent 节点
        latent_classes = {"EmptyLatentImage", "EmptySD3LatentImage", "ImageScale",
                          "EmptyImage", "LatentUpscale", "LatentBatch"}
        uncovered = [f"{nid}({node.get('class_type', '?')})" for nid, node in wf.items()
                     if node.get("class_type", "") in latent_classes and node.get("class_type", "") not in _RESIZE_NODES]
        if uncovered:
            logger.warning(f"  ⚠ {stage}: 未覆盖的 latent 节点（分辨率未调整）: {uncovered}")

    # ── Seed 随机化 ────────────────────────────────────────

    @staticmethod
    def _calc_resolution(native_w: int, native_h: int, aspect_ratio: str) -> tuple[int, int]:
        """根据目标比例计算分辨率，保持长边不变

        Args:
            native_w: 模板原生宽度
            native_h: 模板原生高度
            aspect_ratio: 目标比例，如 "16:9", "9:16", "1:1", "4:3"

        Returns:
            (width, height) 元组，8 的倍数（模型要求）

        示例（Cosmos 原生 1024×576）：
            "16:9" → 1024×576（不变）
            "9:16" → 576×1024
            "1:1"  → 728×728
        """
        try:
            parts = aspect_ratio.split(":")
            rw, rh = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            logger.warning(f"无效比例格式: {aspect_ratio}，使用原生分辨率")
            return native_w, native_h

        if rw <= 0 or rh <= 0:
            logger.warning(f"比例值必须为正数: {aspect_ratio}")
            return native_w, native_h

        long_side = max(native_w, native_h)

        if rw >= rh:
            # 横屏或正方形：长边为宽
            w = long_side
            h = int(long_side * rh / rw)
        else:
            # 竖屏：长边为高
            h = long_side
            w = int(long_side * rw / rh)

        # 对齐到 8 的倍数（扩散模型 latent 空间要求）
        w = max(64, (w // 8) * 8)
        h = max(64, (h // 8) * 8)

        logger.info(f"分辨率计算: 原生 {native_w}×{native_h}, 比例 {aspect_ratio} → {w}×{h}")
        return w, h

    @staticmethod
    def _iter_seed_nodes(wf: dict):
        """遍历所有含 seed 输入的采样器节点（不硬编码 class_type）"""
        for nid, node in wf.items():
            if "seed" in node.get("inputs", {}):
                yield nid, node

    @staticmethod
    def _randomize_seed(wf: dict) -> None:
        """随机化工作流中所有采样器的 seed，避免重复生成相同图片"""
        for _, node in WorkflowBuilder._iter_seed_nodes(wf):
            node["inputs"]["seed"] = random.randint(0, 2**63 - 1)

    @staticmethod
    def _set_seed(wf: dict, seed: int) -> None:
        """设置指定 seed（用于定妆照五视图/服装图保持一致性）"""
        for _, node in WorkflowBuilder._iter_seed_nodes(wf):
            node["inputs"]["seed"] = seed

    def _lora_file_exists(self, lora_name: str) -> bool:
        """检查 LoRA 文件是否存在

        搜索顺序：项目 loras/ → ComfyUI models/loras/
        远程 ComfyUI 实例时 models_dir 为空，跳过本地检查让 ComfyUI 自行报错。
        """
        # 项目内 loras 目录
        if (self._paths.loras_dir / lora_name).exists():
            return True
        # ComfyUI models 目录（从 comfyui 配置读取）
        comfyui_dir = self.config.get("comfyui", {}).get("models_dir", "")
        if comfyui_dir:
            return (Path(comfyui_dir) / "loras" / lora_name).exists()
        # 远程 ComfyUI 时 models_dir 为空，无法本地校验，放行
        return True

    @staticmethod
    def _find_downstream_consumer(wf: dict, source_node: str) -> tuple[str | None, str | None]:
        """查找 source_node 的下游消费者（接收其输出的节点+输入名）

        优先找非 LoadImage 节点中引用 source_node 的输入，
        回退到 sampler.model。

        Returns:
            (node_id, input_name) 或 (None, None)
        """
        for nid, node in wf.items():
            if nid == source_node or node.get("class_type") == "LoadImage":
                continue
            for inp_name, inp_val in node.get("inputs", {}).items():
                if isinstance(inp_val, list) and len(inp_val) == 2 and inp_val[0] == source_node:
                    return nid, inp_name
        # 回退到 sampler（所有类型）
        ksampler = (find_first_node(wf, "KSampler")
                    or find_first_node(wf, "KSamplerAdvanced")
                    or find_first_node(wf, "XlabsSampler"))
        return (ksampler, "model") if ksampler else (None, None)

    # ── img2img 处理 ────────────────────────────────────────

    def _setup_img2img(self, wf: dict, shot: dict, backend_meta: dict) -> None:
        """img2img 后端：上传参考图到 ComfyUI 并注入 LoadImage 节点

        参考图来源优先级：
        1. shot 的 outfit 对应的服装参考图
        2. 角色定妆照（cover.png）
        3. 无参考图时跳过（纯文本生成）
        """
        ref_image = self._find_ref_image(shot)
        if not ref_image:
            char_names = parse_char_names(shot)
            if char_names:
                logger.warning("img2img 后端无参考图（角色缺定妆照），将按 denoise=1 纯文本生成")
            else:
                logger.info("img2img 后端无角色参考图，将按 denoise=1 纯文本生成")
            return

        # 上传到 ComfyUI
        if self.comfyui and hasattr(self.comfyui, 'upload_image'):
            try:
                upload_name = f"img2img_ref_{Path(ref_image).name}"
                self.comfyui.upload_image(ref_image, filename=upload_name)
                ref_image = upload_name
            except Exception as e:
                raise RuntimeError(f"参考图上传到 ComfyUI 失败: {e}")

        # 设置 LoadImage 节点的输入图片（排除 IP-Adapter/PuLID 一致性节点）
        all_load = [nid for nid, n in wf.items() if n.get("class_type") == "LoadImage"]
        plain_load = [nid for nid in all_load
                      if not nid.startswith("ipadapter_ref")
                      and not nid.startswith("pulid_ref")
                      and not nid.startswith("controlnet_ref")]
        if plain_load:
            target_node = plain_load[0]
        elif all_load:
            # 所有 LoadImage 都是一致性节点，创建新的场景参考图节点
            logger.warning("img2img: 无普通 LoadImage 节点，创建新节点用于场景参考图")
            target_node = f"img2img_ref_{_next_suffix()}"
            wf[target_node] = {
                "class_type": "LoadImage",
                "inputs": {"image": Path(ref_image).name},
            }
        else:
            target_node = None
        if target_node:
            wf[target_node]["inputs"]["image"] = Path(ref_image).name

    def _find_ref_image(self, shot: dict) -> str | None:
        """查找镜头的参考图（定妆照或 outfit 参考图）"""
        char_names = parse_char_names(shot)
        if not char_names:
            return None
        cid = self._char_name_to_id.get(char_names[0], char_names[0])
        outfit = shot.get("outfit", "") or "default"
        paths = self._paths

        # 优先 outfit 参考图
        outfit_dir = paths.character_outfit_dir(cid, outfit)
        if outfit_dir.exists():
            for f in outfit_dir.iterdir():
                if f.suffix.lower() in IMAGE_EXTENSIONS:
                    return str(f)

        # 回退到定妆照 cover.png
        cover = paths.character_asset_dir(cid) / "cover.png"
        if cover.exists():
            return str(cover)

        return None

    # ── 构建首帧工作流 ──────────────────────────────────────

    def _build_first_frame_prompt(self, shot: dict, character_desc: str,
                                   scene_desc: str, multi_char_prompt: str) -> tuple[dict, str]:
        """构建首帧 prompt + 返回图像后端名"""
        from engines.prompt.builder import PromptBuildParams, build_prompt

        style = self.config.get("project", {}).get("style", "cinematic")
        genre = self.config.get("project", {}).get("genre", "urban")
        img_backend = self.models.get("image_backend", "flux")

        # 获取角色圣经上下文 + 注入角色专属情绪/肢体语言到 shot
        character_bible = ""
        char_names = parse_char_names(shot)
        enriched_shot = dict(shot)  # 不修改原 shot，用副本注入临时字段
        if char_names:
            try:
                from engines.consistency.bible import CharacterBible
                bible = CharacterBible(self.project_dir)
                prompt_style = self.registry.get_prompt_style(img_backend) if img_backend else "tag"
                # name → hash ID（bible 用 hash ID 查文件）
                resolved_cid = self._char_name_to_id.get(char_names[0], char_names[0])
                character_bible = bible.get_tags(resolved_cid) if prompt_style == "tag" else bible.get_context(resolved_cid)
                char_bible_data = bible.load(resolved_cid)
                if char_bible_data:
                    enriched_shot["_char_emotional_range"] = char_bible_data.get("emotional_range", {})
                    enriched_shot["_char_body_language"] = char_bible_data.get("body_language", {})
            except Exception as e:
                logger.warning(f"角色圣经加载跳过（配置可能有误）: {e}")

        # 加载场景数据（含 lighting）
        scene_data = {}
        scene_name = shot.get("scene_name", "")
        if scene_name:
            try:
                from infra.config import load_scene
                scene_data = load_scene(self._paths, scene_name)
            except Exception as e:
                logger.debug(f"场景数据加载跳过: {e}")

        positive = build_prompt(PromptBuildParams(
            shot=enriched_shot, character_desc=character_desc,
            scene_desc=scene_desc, style=style, genre=genre,
            image_backend=img_backend, registry=self.registry,
            character_bible=character_bible, scene_data=scene_data))
        if multi_char_prompt:
            positive = f"{positive}, {multi_char_prompt}"

        # 从注册表读取后端专属 negative prompt（注册表是唯一真相来源）
        backend_meta = self.registry.get_backend("image", img_backend) if img_backend else {}
        negative = (backend_meta or {}).get("negative_prompt",
            "bad quality, worst quality, ugly, deformed, blurry, "
            "text, watermark, logo, signature, subtitle, caption, text overlay")

        return {"positive": positive, "negative": negative}, img_backend

    def _apply_view_overrides(self, view_key: str) -> tuple[dict, dict | None]:
        """返回 (lora_dict, overridden_config_or_None) — 不修改 self.config。

        self.config 保持不可变；视图级覆盖通过 deepcopy + merge 产生局部 config，
        由调用方按需传递给下游方法。下游 inject_from_registry() 原生检查
        config.enabled 控制启用/禁用，无需额外分支。

        Returns:
            (lora_dict, overridden_config_or_None):
            - lora_dict: LoRA 参数覆盖（global_lora_strength, character_lora_strength）
            - overridden_config: 带视图覆盖的局部 config；无覆盖时为 None（用 self.config）
        """
        overrides = self.models.get("view_overrides", {}).get(view_key, {})
        if not overrides:
            return {}, None

        import copy
        cfg = copy.deepcopy(self.config)
        for cfg_key, cfg_val in overrides.get("config", {}).items():
            cfg.setdefault(cfg_key, {}).update(cfg_val)

        return overrides.get("lora", {}), cfg

    def _inject_character_consistency(self, wf: dict, char_names: list[str],
                                       img_backend: str,
                                       skip_consistency: bool = False,
                                       lora_overrides: dict | None = None,
                                       config: dict | None = None) -> dict:
        """注入角色 LoRA 和一致性方案（IP-Adapter / PuLID）

        注意: 就地修改 wf，由 build_first_frame 负责初始 deepcopy。
        面部一致性始终使用主 cover.png（不使用 outfit 图 — 那是服装参考，不是面部参考）。

        Args:
            skip_consistency: True 时只注入 LoRA，跳过 PuLID/IP-Adapter。
                正面定妆照无参考图时使用。
            lora_overrides: 视图级 LoRA 覆盖（来自 _apply_view_overrides 返回）。
                支持的 key: character_lora_strength
            config: 视图级配置覆盖（来自 _apply_view_overrides 返回）。
                None 时使用 self.config（无覆盖/全局默认配置）。
        """
        if config is None:
            config = self.config
        # 分 LoRA 角色 vs 无 LoRA 角色
        chars_with_lora: list[dict] = []
        chars_without_lora: list[str] = []
        for cid in char_names:
            lora_path = _find_character_lora(self, cid)
            if lora_path:
                chars_with_lora.append({"cid": cid, "lora_path": lora_path})
            else:
                chars_without_lora.append(cid)

        # 注入 LoRA
        from infra.storage.asset_tracker import comfyui_asset_name
        for item in chars_with_lora:
            cid, lora_path = item["cid"], item["lora_path"]
            strength = (lora_overrides or {}).get("character_lora_strength")
            if strength is None:
                strength = self.models.get("character_lora_strength", 0.7)
            name = comfyui_asset_name(self.project_dir, Path(lora_path).stem, Path(lora_path).name)
            wf = _inject_lora(wf, lora_path, strength=strength, lora_name=name)
            logger.info(f"使用角色 LoRA: {cid} → {lora_path} (strength={strength})")

        # skip_consistency: 只注入 LoRA，不注入 PuLID/IP-Adapter
        if skip_consistency:
            for cid in chars_without_lora:
                logger.debug(f"角色 '{cid}' 无 LoRA（skip_consistency，跳过一致性注入）")
            return wf

        # 一致性方案选择 — 管道优先（命名管道 → 单方法 → auto → consistency_default）
        consistency = self.models.get("consistency_method",
                                      config.get("consistency_method", "auto"))
        if consistency == "auto":
            pipeline = self.registry.get_consistency_pipeline(
                img_backend, available_nodes=getattr(self, "available_nodes", None))
        else:
            pipeline = [] if consistency == "none" else [consistency]

        # 身份层面注入：PuLID-Flux → Flux IP-Adapter（按管道逐层注入）
        # 方法级启用/禁用由 inject_from_registry() 原生检查 config.enabled 处理，
        # 无需在 builder 中额外分支过滤。
        if chars_without_lora and pipeline:
            ip_config = config.get("ip_adapter", {})
            chars_with_refs = self._filter_chars_with_refs(chars_without_lora, ip_config=ip_config)
            if chars_with_refs:
                for method in pipeline:
                    wf = self._inject_consistency_method(wf, method, chars_with_refs, config=config)

        # ControlNet Depth：全身结构一致性（位于身份注入之后，即管道最外层；
        # ApplyFluxControlNet 接收已 patch 的 MODEL，输出 baked-in MODEL →
        # 对 XlabsSampler 仅设 model，不设 controlnet_condition）
        # 视图级禁用通过 config.controlnet_depth.enabled=false 实现，无需额外检查。
        if (config.get("controlnet_depth", {}).get("enabled")
                and chars_without_lora):
            cn_chars = self._filter_chars_with_refs(chars_without_lora)
            if cn_chars:
                wf = self._inject_consistency_method(wf, "controlnet_depth", cn_chars, config=config)

        return wf

    def _filter_chars_with_refs(self, char_ids: list[str], *, ip_config: dict | None = None) -> list[str]:
        """过滤出有参考图的角色，并记录缺失者日志"""
        refs = [cid for cid in char_ids
                if self._get_character_refs(cid, _no_auto_gen=self.no_auto_gen, ip_config=ip_config)]
        for cid in set(char_ids) - set(refs):
            if self.no_auto_gen:
                logger.debug(f"角色 '{cid}' 定妆照生成中，暂无参考图")
            else:
                logger.warning(f"角色 '{cid}' 无定妆照，跳过一致性注入")
        return refs

    def _inject_consistency_method(self, wf: dict, consistency: str,
                                    chars: list[str], *,
                                    config: dict | None = None) -> dict:
        """根据一致性方案元数据注入对应节点（配置驱动：优先使用 node_graphs YAML）"""
        from engines.workflow.node_graph import inject_from_registry
        return inject_from_registry(self, wf, chars, consistency,
                                     config if config is not None else self.config)

    def build_first_frame(self, shot: dict, character_desc: str = "",
                          scene_desc: str = "", multi_char_prompt: str = "",
                          seed: int | None = None,
                          skip_consistency: bool = False) -> tuple[dict, dict]:
        """构建首帧工作流

        Args:
            shot: 镜头配置
            character_desc: 角色英文描述
            scene_desc: 场景英文描述
            multi_char_prompt: 多角色合并 prompt
            seed: 指定 seed（None 则随机，用于定妆照一致性控制）
            skip_consistency: 跳过角色一致性注入（正面定妆照无参考图时使用）

        Returns:
            (prompt_dict, workflow_dict) 元组
        """
        # 1. 构建 prompt
        prompt, img_backend = self._build_first_frame_prompt(
            shot, character_desc, scene_desc, multi_char_prompt)

        # 2. 复制模板 + 设置 prompt
        wf = copy.deepcopy(self.first_frame_wf)
        if not wf:
            return prompt, {}
        set_clip_text_prompts(wf, prompt["positive"], prompt["negative"])

        # 3. img2img 后端：注入参考图
        backend_meta = self.registry.get_backend("image", img_backend) or {}
        if backend_meta.get("img2img"):
            self._setup_img2img(wf, shot, backend_meta)

        char_names = parse_char_names(shot)

        # 3b. 注入风格 LoRA（必须在一致性管道之前；LoRA 在 ControlNet/PuLID 之后
        #     会因 ApplyFluxControlNet 输出 ControlNetCondition 导致 type mismatch）
        genre = self.config.get("project", {}).get("genre", "")
        if genre:
            style_lora = _find_style_lora(self, genre)
            if style_lora:
                strength = self.models.get("style_lora_strength", 0.6)
                wf = _inject_lora(wf, style_lora, strength=strength,
                                       lora_name=os.path.basename(style_lora))
                logger.info(f"使用风格 LoRA: {genre} → {style_lora}")

        # 3c. 注入全局 LoRA（必须在一致性管道之前；同上）
        # 仅在有角色时注入 — 全局 LoRA 通常是人物肖像类（如 ACE++ Portrait）
        #
        # 视图级覆盖通过 _apply_view_overrides() 统一修改 config + 返回 lora 字典，
        # 无需在 builder 中为每个 override key 写专用分支。
        view_key = shot.get("view_key") or shot.get("shot_type", "")
        lora, local_config = self._apply_view_overrides(view_key)

        if char_names:
            for gl in self.models.get("global_loras", []):
                name = gl.get("name", "")
                if not name:
                    continue
                if not self._lora_file_exists(name):
                    logger.warning(f"全局 LoRA 文件不存在，跳过: {name}（请放入 ComfyUI/models/loras/）")
                    continue
                strength = lora.get("global_lora_strength")
                if strength is None:
                    strength = gl.get("strength", 0.7)
                wf = _inject_lora(wf, name, strength=strength, lora_name=name)
                logger.info(f"使用全局 LoRA: {name} (strength={strength})")
        elif self.models.get("global_loras"):
            logger.debug("无角色镜头，跳过全局 LoRA 注入")

        # 4. 注入角色一致性（LoRA + IP-Adapter/PuLID + ControlNet）
        #    local_config 为视图级配置覆盖（有覆盖时为 deepcopy，无覆盖时为 None=默认）
        #    self.config 始终保持不变，无状态泄漏风险。
        if char_names:
            wf = self._inject_character_consistency(wf, char_names, img_backend,
                                                     skip_consistency=skip_consistency,
                                                     lora_overrides=lora,
                                                     config=local_config)

        # 6. Seed 控制
        if seed is not None:
            self._set_seed(wf, seed)
        else:
            self._randomize_seed(wf)

        # 7. 工作流预检（组装后全面校验，不连接 ComfyUI）
        from engines.workflow.preflight import WorkflowPreflightChecker
        preflight = WorkflowPreflightChecker(
            schema_cache=getattr(self, "_schema_cache", None),
        )
        result = preflight.check(wf)
        if not result.passed:
            for e in result.errors:
                logger.error(f"工作流预检失败: {e}")
            # 不阻断执行，仅记录错误（渐进式启用）
        for w in result.warnings:
            logger.warning(f"工作流预检警告: {w}")
        logger.info(
            f"工作流预检: {result.checks_passed}/{result.checks_run} 项通过, "
            f"{len(result.errors)} error, {len(result.warnings)} warning"
        )

        return prompt, wf

    def build_video(self, frame_path: str, shot: dict | None = None,
                    characters: dict | None = None,
                    scenes: dict | None = None) -> dict:
        """构建视频生成工作流（委托给 video.py）"""
        from engines.workflow.video import build_video
        return build_video(self, frame_path, shot, characters, scenes)

    def build_upload_map(self, shot: dict, wf: dict) -> dict[str, str]:
        """构建参考图上传映射（委托给 upload.py）"""
        from engines.workflow.upload import build_upload_map
        return build_upload_map(self, shot, wf)

    # ── 内部方法 ──────────────────────────────────────────

    def _get_character_refs(self, char_id: str, *, _no_auto_gen: bool = False,
                            ip_config: dict | None = None) -> list[str]:
        """获取角色一致性参考图（IP-Adapter/PuLID 注入用）

        多图参考模式（ip_config.multi_ref.enabled=true）：
        返回 [cover.png, full_body.png/three_quarter.png] — 面部 + 全身/半身参考

        单图模式（multi_ref.enabled=false 或 PuLID）：
        返回 [cover.png] — 仅面部参考

        char_id: 角色名（从分镜解析）或 hash ID。
        ip_config: IP-Adapter 配置（含 multi_ref 子配置）。
        """
        # name → hash ID（分镜存 name，文件路径用 hash ID）
        resolved_id = self._char_name_to_id.get(char_id, char_id)

        if resolved_id in self._refs_cache:
            return self._refs_cache[resolved_id]

        from engines.content.portrait import ensure_portrait
        char_dir = self._paths.character_asset_dir(resolved_id)

        # 1. 角色正面定妆照（cover.png）— 始终作为主参考
        cover = char_dir / "cover.png"
        if not cover.exists():
            # 尝试自动定妆照
            if _no_auto_gen:
                self._refs_cache[resolved_id] = []
                return []
            portrait = ensure_portrait(resolved_id, self.config,
                                       self._get_container(),
                                       force=self.force)
            if portrait:
                cover = char_dir / "cover.png"
            else:
                # 全局共享库
                shared_cover = self._paths.shared_assets_dir / "characters" / resolved_id / "cover.png"
                if shared_cover.exists():
                    cover = shared_cover
                else:
                    self._refs_cache[resolved_id] = []
                    return []

        refs = [str(cover)]

        # 2. 多图参考：全身/半身视图（用于 IP-Adapter 身体一致性）
        multi_ref_cfg = (ip_config or {}).get("multi_ref", {})
        if not multi_ref_cfg:
            multi_ref_cfg = self.models.get("multi_ref", {})
        if multi_ref_cfg.get("enabled", False):
            max_refs = multi_ref_cfg.get("max_refs", 3)
            if len(refs) < max_refs:
                # 全身视图（捕捉体型、发型、服装轮廓）
                full_body = self._paths.full_body_ref(resolved_id)
                if full_body and str(full_body) not in refs:
                    refs.append(str(full_body))

        self._refs_cache[resolved_id] = refs
        return refs
