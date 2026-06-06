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

from engines.shot_utils import parse_char_ids
from engines.workflow import (
    find_first_node, find_load_image_nodes,
    resolve_node_aliases, set_clip_text_prompts,
)
from engines.workflow_inject import (
    inject_character_refs as _inject_character_refs,
    inject_pulid_flux as _inject_pulid_flux,
    find_character_lora as _find_character_lora,
    find_style_lora as _find_style_lora,
    inject_lora as _inject_lora,
)
from infra.gpu import get_generation_config as get_gpu_config
from infra.config import ProjectPaths

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
        self._refs_cache: dict[str, list[str]] = {}  # 角色参考图缓存（防并发重复查找）

    def _get_container(self) -> object:
        """获取容器：优先完整 DI 容器，回退到简单 dict"""
        if self._container:
            return self._container
        if self.comfyui:
            return {"image": self.comfyui}
        return None

    # ── 加载工作流 ──────────────────────────────────────────

    def load_workflows(self) -> None:
        """根据 image_backend / video_backend 加载对应工作流 JSON"""
        available_nodes: set[str] = set()
        if self.comfyui and hasattr(self.comfyui, 'get_available_node_types'):
            try:
                available_nodes = self.comfyui.get_available_node_types()
            except Exception as e:
                logger.debug(f"获取 ComfyUI 节点类型失败: {e}")
        self.available_nodes = available_nodes

        # 确保 registry 可用
        if not self.registry:
            from flow.model_registry import ModelRegistry
            self.registry = ModelRegistry()

        # 从注册表读取默认后端名（注册表是唯一真相来源）
        defaults = self.registry.get_defaults()
        default_img = defaults.get("image_backend")
        default_video = defaults.get("video_backend")

        # 首帧工作流
        img_backend = self.models.get("image_backend", default_img)
        wf_name = self.registry.get_image_workflow(img_backend)
        if not wf_name:
            logger.warning(f"未知 image_backend '{img_backend}'，回退到 {default_img}")
            wf_name = self.registry.get_image_workflow(default_img)
        if not wf_name:
            raise ValueError(f"首帧工作流未找到: image_backend='{img_backend}'，请检查 models_registry.yaml")
        self.first_frame_wf = self._load_wf(wf_name)
        if not self.first_frame_wf:
            raise ValueError(f"首帧工作流文件为空或不存在: {wf_name}")
        self.first_frame_wf = resolve_node_aliases(self.first_frame_wf, available_nodes)

        # 视频工作流
        video_backend = self.models.get("video_backend", default_video)
        video_wf_name = self.registry.get_video_workflow(video_backend)
        if not video_wf_name:
            logger.warning(f"未知 video_backend '{video_backend}'，回退到 {default_video}")
            video_wf_name = self.registry.get_video_workflow(default_video)
        if not video_wf_name:
            raise ValueError(f"视频工作流未找到: video_backend='{video_backend}'，请检查 models_registry.yaml")
        self.video_wf = self._load_wf(video_wf_name)
        if not self.video_wf:
            raise ValueError(f"视频工作流文件为空或不存在: {video_wf_name}")
        self.video_wf = resolve_node_aliases(self.video_wf, available_nodes)

        # 应用 GPU 适配
        gpu_cfg = get_gpu_config(config=self.config)
        # 预构建采样器节点集合（一次构建，两次复用）
        sampler_types = {"KSampler", "KSamplerAdvanced", "BasicScheduler"}
        for svc in ("image", "video"):
            for bname in self.registry.list_backend_names(svc):
                sn = self.registry.get_sampler_node(bname) if svc == "image" else self.registry.get_video_sampler_node(bname)
                if sn:
                    sampler_types.add(sn)
        if self.first_frame_wf:
            self._apply_gpu(self.first_frame_wf, "first_frame", gpu_cfg, sampler_types)
        if self.video_wf:
            self._apply_gpu(self.video_wf, "video", gpu_cfg, sampler_types)

    def _load_wf(self, name: str) -> dict:
        path = os.path.join(self.wf_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        # 回退到仓库根目录 workflows/
        root_wf = os.path.join(os.path.dirname(__file__), "..", "workflows", name)
        root_wf = os.path.normpath(root_wf)
        if os.path.exists(root_wf):
            with open(root_wf, encoding="utf-8") as f:
                return json.load(f)
        logger.debug(f"工作流不存在: {path} (也检查了 {root_wf})")
        return {}

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

        for nid, node in wf.items():
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
        for nid, node in WorkflowBuilder._iter_seed_nodes(wf):
            node["inputs"]["seed"] = random.randint(0, 2**63 - 1)

    @staticmethod
    def _set_seed(wf: dict, seed: int) -> None:
        """设置指定 seed（用于定妆照五视图/服装图保持一致性）"""
        for nid, node in WorkflowBuilder._iter_seed_nodes(wf):
            node["inputs"]["seed"] = seed

    def _lora_file_exists(self, lora_name: str) -> bool:
        """检查 LoRA 文件是否存在于 ComfyUI models 目录

        搜索顺序：项目 loras/ → ComfyUI models/loras/
        注意：远程 ComfyUI 实例时，本地检查可能误判（文件在远程服务器上），
        此时跳过检查让 ComfyUI 自行报错。
        """
        # 项目内 loras 目录
        project_lora = self._paths.loras_dir / lora_name
        if project_lora.exists():
            return True
        # ComfyUI models 目录（从 comfyui 配置读取）
        comfyui_dir = self.config.get("comfyui", {}).get("models_dir", "")
        if comfyui_dir:
            return (Path(comfyui_dir) / "loras" / lora_name).exists()
        # 远程 ComfyUI 时 models_dir 为空，无法本地校验，放行让 ComfyUI 报错
        default_path = Path.home() / "ComfyUI" / "models" / "loras" / lora_name
        if not default_path.parent.exists():
            return True  # 本地无 ComfyUI 目录，视为远程实例，放行
        return default_path.exists()

    @staticmethod
    def _find_downstream_consumer(wf: dict, source_node: str) -> tuple[str | None, str | None]:
        """查找 source_node 的下游消费者（接收其输出的节点+输入名）

        优先找非 LoadImage 节点中引用 source_node 的输入，
        回退到 KSampler.model。

        Returns:
            (node_id, input_name) 或 (None, None)
        """
        for nid, node in wf.items():
            if nid == source_node or node.get("class_type") == "LoadImage":
                continue
            for inp_name, inp_val in node.get("inputs", {}).items():
                if isinstance(inp_val, list) and len(inp_val) == 2 and inp_val[0] == source_node:
                    return nid, inp_name
        # 回退到 KSampler
        ksampler = find_first_node(wf, "KSampler")
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
            char_ids = parse_char_ids(shot)
            if char_ids:
                logger.warning("img2img 后端无参考图（角色缺定妆照），将按 denoise=1 纯文本生成")
            else:
                logger.info("img2img 后端无角色参考图，将按 denoise=1 纯文本生成")
            return

        # 上传到 ComfyUI
        if self.comfyui:
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
                      and not nid.startswith("pulid_ref")]
        if plain_load:
            target_node = plain_load[0]
        elif all_load:
            # 所有 LoadImage 都是一致性节点，创建新的场景参考图节点
            logger.warning("img2img: 无普通 LoadImage 节点，创建新节点用于场景参考图")
            target_node = f"img2img_ref_{len(all_load)}"
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
        char_ids = parse_char_ids(shot)
        if not char_ids:
            return None
        cid = char_ids[0]
        outfit = shot.get("outfit", "default")
        paths = self._paths

        # 优先 outfit 参考图
        outfit_dir = paths.character_outfit_dir(cid, outfit)
        if outfit_dir.exists():
            for f in outfit_dir.iterdir():
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
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
        from engines.prompt import build_prompt, PromptBuildParams

        style = self.config.get("project", {}).get("style", "cinematic")
        genre = self.config.get("project", {}).get("genre", "urban")
        defaults = self.registry.get_defaults()
        img_backend = self.models.get("image_backend", defaults.get("image_backend"))

        # 获取角色圣经上下文
        character_bible = ""
        char_ids = parse_char_ids(shot)
        if char_ids:
            try:
                from engines.character_bible import CharacterBible
                bible = CharacterBible(self.project_dir)
                prompt_style = self.registry.get_prompt_style(img_backend) if img_backend else "tag"
                character_bible = bible.get_tags(char_ids[0]) if prompt_style == "tag" else bible.get_context(char_ids[0])
            except Exception:
                logger.debug("角色圣经加载跳过")

        positive = build_prompt(PromptBuildParams(
            shot=shot, character_desc=character_desc,
            scene_desc=scene_desc, style=style, genre=genre,
            image_backend=img_backend, registry=self.registry,
            character_bible=character_bible))
        if multi_char_prompt:
            positive = f"{positive}, {multi_char_prompt}"

        negative = ("bad quality, worst quality, ugly, deformed, blurry, "
                    "watermark, text, subtitle, caption, text overlay, "
                    "burned-in text, word, letter, logo, signature, username, timestamp, "
                    "bottom text, top text, screen text, embedded text, "
                    "movie subtitle, film caption, hardcoded subtitle, "
                    "speech bubble, thought bubble, comic text, "
                    "garbled text, corrupted text, misspelled text")

        return {"positive": positive, "negative": negative}, img_backend

    def _inject_character_consistency(self, wf: dict, char_ids: list[str],
                                       outfit: str, img_backend: str) -> dict:
        """注入角色 LoRA 和一致性方案（IP-Adapter / PuLID）"""
        # 一致性方案选择
        consistency = self.models.get("consistency_method",
                                      self.config.get("consistency_method", "auto"))
        if consistency == "auto":
            consistency = self.registry.get_consistency_default(img_backend) or "none"

        # 分 LoRA 角色 vs 无 LoRA 角色（统一用 dict 避免混合类型）
        chars_with_lora: list[dict] = []  # {"cid": str, "lora_path": str}
        chars_without_lora: list[str] = []
        for cid in char_ids:
            lora_path = _find_character_lora(self, cid)
            if lora_path:
                chars_with_lora.append({"cid": cid, "lora_path": lora_path})
            else:
                chars_without_lora.append(cid)

        # 注入 LoRA
        from infra.asset_tracker import comfyui_asset_name
        for item in chars_with_lora:
            cid, lora_path = item["cid"], item["lora_path"]
            strength = self.models.get("character_lora_strength", 0.7)
            name = comfyui_asset_name(self.project_dir, Path(lora_path).stem, Path(lora_path).name)
            wf = _inject_lora(wf, lora_path, strength=strength, lora_name=name)
            logger.info(f"使用角色 LoRA: {cid} → {lora_path}")

        # 无 LoRA 角色 → 一致性方案
        if chars_without_lora:
            chars_with_refs = [cid for cid in chars_without_lora
                               if self._get_character_refs(cid, outfit=outfit, _no_auto_gen=self.no_auto_gen)]
            missing = set(chars_without_lora) - set(chars_with_refs)
            for cid in missing:
                # 定妆照生成阶段（no_auto_gen=True）无参考图是预期行为，降级为 debug
                if self.no_auto_gen:
                    logger.debug(f"角色 '{cid}' 定妆照生成中，暂无参考图（一致性将在首帧生产时注入）")
                else:
                    logger.warning(f"角色 '{cid}' 无定妆照，跳过一致性注入")

            if chars_with_refs:
                wf = self._inject_consistency_method(wf, consistency, chars_with_refs, outfit)

        return wf

    def _inject_consistency_method(self, wf: dict, consistency: str,
                                    chars: list[str], outfit: str) -> dict:
        """根据一致性方案元数据注入对应节点"""
        method_meta = self.registry.get_consistency_method(consistency)
        if not method_meta or not method_meta.get("inject_method"):
            if consistency == "none":
                logger.info("一致性方案: none，跳过面部一致性注入")
            else:
                logger.warning(f"未注册的一致性方案: {consistency}")
            return wf

        config_key = method_meta.get("config_key", "")
        method_config = self.config.get(config_key, {}) if config_key else {}
        if method_config.get("enabled") is False:
            logger.info(f"{consistency} 已禁用，跳过一致性注入")
            return wf

        # 注入方法映射：注册表中的 inject_method → 实际函数
        _INJECT_DISPATCH = {
            "_inject_character_refs": _inject_character_refs,
            "_inject_pulid_flux": _inject_pulid_flux,
        }
        inject_fn = _INJECT_DISPATCH.get(method_meta["inject_method"])
        if not inject_fn:
            logger.warning(f"一致性方案 '{consistency}' 的注入方法不存在")
            return wf

        # 检查 ComfyUI 插件
        required_node = method_meta.get("required_comfyui_node")
        if required_node and hasattr(self, 'available_nodes') and self.available_nodes:
            if required_node not in self.available_nodes:
                logger.warning(f"ComfyUI 未安装 {consistency} 插件（{required_node} 节点不存在），跳过")
                return wf

        return inject_fn(self, wf, chars, method_config, outfit=outfit)

    def build_first_frame(self, shot: dict, character_desc: str = "",
                          scene_desc: str = "", multi_char_prompt: str = "",
                          seed: int | None = None) -> tuple[dict, dict]:
        """构建首帧工作流

        Args:
            shot: 镜头配置
            character_desc: 角色英文描述
            scene_desc: 场景英文描述
            multi_char_prompt: 多角色合并 prompt
            seed: 指定 seed（None 则随机，用于定妆照一致性控制）

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

        # 4. 注入角色一致性（LoRA + IP-Adapter/PuLID）
        char_ids = parse_char_ids(shot)
        outfit = shot.get("outfit", "")
        if char_ids:
            wf = self._inject_character_consistency(wf, char_ids, outfit, img_backend)

        # 5. 注入风格 LoRA
        genre = self.config.get("project", {}).get("genre", "")
        if genre:
            style_lora = _find_style_lora(self, genre)
            if style_lora:
                strength = self.models.get("style_lora_strength", 0.6)
                wf = _inject_lora(wf, style_lora, strength=strength,
                                       lora_name=os.path.basename(style_lora))
                logger.info(f"使用风格 LoRA: {genre} → {style_lora}")

        # 5b. 注入全局 LoRA（用户手动放入 ComfyUI/models/loras/ 的通用 LoRA）
        # 仅在有角色时注入 — 全局 LoRA 通常是人物肖像类（如 ACE++ Portrait），
        # 注入到纯场景图会导致场景被人像特征污染。
        if char_ids:
            for gl in self.models.get("global_loras", []):
                name = gl.get("name", "")
                if not name:
                    continue
                # 检查 LoRA 文件是否存在于 ComfyUI models 目录
                if not self._lora_file_exists(name):
                    logger.warning(f"全局 LoRA 文件不存在，跳过: {name}（请放入 ComfyUI/models/loras/）")
                    continue
                strength = gl.get("strength", 0.7)
                wf = _inject_lora(wf, name, strength=strength, lora_name=name)
                logger.info(f"使用全局 LoRA: {name} (strength={strength})")
        elif self.models.get("global_loras"):
            logger.debug("无角色镜头，跳过全局 LoRA 注入")

        # 6. Seed 控制
        if seed is not None:
            self._set_seed(wf, seed)
        else:
            self._randomize_seed(wf)

        return prompt, wf

    def build_video(self, frame_path: str, shot: dict | None = None) -> dict:
        """构建视频生成工作流

        Args:
            frame_path: 首帧图片路径
            shot: 镜头数据（含 duration），用于计算 video_frames
        """
        wf = copy.deepcopy(self.video_wf)
        if not wf:
            logger.warning("build_video: video_wf 为空，无法构建视频工作流")
            return {}

        # 设置首帧图
        load_nodes = find_load_image_nodes(wf)
        if load_nodes:
            wf[load_nodes[0]]["inputs"]["image"] = os.path.basename(frame_path)

        # 根据 duration 动态计算 video_frames（修复 video_frames 与 duration 脱节的问题）
        if shot:
            self._apply_duration(wf, shot)

        # 注入风格 LoRA（视频生成也受益于风格一致性）
        genre = self.config.get("project", {}).get("genre", "")
        if genre:
            style_lora = _find_style_lora(self, genre)
            if style_lora:
                style_strength = self.models.get("style_lora_strength", 0.6)
                # 风格 LoRA 用原文件名（用户手动放置，不加 project hash）
                wf = _inject_lora(wf, style_lora, strength=style_strength,
                                       lora_name=os.path.basename(style_lora))

        # 随机化 seed
        self._randomize_seed(wf)

        return wf

    def _apply_duration(self, wf: dict, shot: dict) -> None:
        """根据镜头 duration 动态调整视频帧数，使生成视频时长匹配分镜预期。

        计算公式: video_frames = max(min_frames, ceil(duration × model_fps))
        不同后端的帧数参数位置不同，按后端类型设置到正确的节点。
        """
        import math

        # 读取 duration（秒），默认 4 秒
        from infra.constants import clip_duration
        duration = clip_duration(shot.get("duration"))

        # 获取当前视频后端的 fps
        reg_defaults = self.registry.get_defaults()
        video_backend = self.models.get("video_backend", reg_defaults.get("video_backend"))
        model_fps = 8  # 默认
        if self.registry:
            defaults = self.registry.get_video_defaults(video_backend)
            if defaults.get("fps"):
                model_fps = defaults["fps"]

        # 计算所需帧数（最少 8 帧，避免过短导致质量问题）
        min_frames = 8
        video_frames = max(min_frames, math.ceil(duration * model_fps))

        logger.info(
            f"视频帧数计算: duration={duration}s × fps={model_fps} → "
            f"video_frames={video_frames} (backend={video_backend})"
        )

        # 按后端类型设置到正确的节点参数
        self._set_video_frames(wf, video_frames, video_backend)

    def _set_video_frames(self, wf: dict, frames: int, backend: str) -> None:
        """将帧数设置到工作流的正确节点（注册表驱动）

        从 models_registry.yaml 读取视频后端的 frame_params 配置，
        根据 node_class 和 input_name 注入帧数，不再硬编码后端名。
        """
        frame_cfg = self.registry.get_frame_params(backend)
        if not frame_cfg:
            logger.warning(f"视频后端 '{backend}' 未声明 frame_params，跳过帧数注入")
            return

        target_class = frame_cfg["node_class"]
        target_input = frame_cfg["input_name"]

        for nid, node in wf.items():
            if node.get("class_type") == target_class:
                node["inputs"][target_input] = frames
                logger.debug(f"  {backend}: {nid}.{target_input} = {frames}")

    # ── 参考图上传映射 ──────────────────────────────────────

    def build_upload_map(self, shot: dict, wf: dict) -> dict[str, str]:
        """构建参考图上传映射 {node_id: file_path}"""
        uploads: dict[str, str] = {}
        char_ids = parse_char_ids(shot)
        outfit = shot.get("outfit", "")

        all_load_nodes = find_load_image_nodes(wf)

        # 区分一致性参考图节点和场景图节点
        # IP-Adapter 节点命名规则: ipadapter_ref_* (主角色), ipadapter_ref2_* (次要角色)
        ipa_primary_nodes = [n for n in all_load_nodes if n.startswith("ipadapter_ref_") and not n.startswith("ipadapter_ref2_")]
        ipa_secondary_nodes = [n for n in all_load_nodes if n.startswith("ipadapter_ref2_")]
        # PuLID-Flux 节点命名规则: pulid_ref_* (主角色), pulid_ref2_* (次要角色)
        pulid_primary_nodes = [n for n in all_load_nodes if n.startswith("pulid_ref_") and not n.startswith("pulid_ref2_")]
        pulid_secondary_nodes = [n for n in all_load_nodes if n.startswith("pulid_ref2_")]
        # 剩余的是场景图节点
        ipa_node_set = (set(ipa_primary_nodes) | set(ipa_secondary_nodes)
                        | set(pulid_primary_nodes) | set(pulid_secondary_nodes))
        scene_nodes = [n for n in all_load_nodes if n not in ipa_node_set
                       and not n.startswith("ipadapter_")
                       and not n.startswith("pulid_")]

        # 主角色
        if char_ids:
            refs = self._get_character_refs(char_ids[0], outfit=outfit, _no_auto_gen=self.no_auto_gen)
            # 优先用 PuLID 节点，再用 IP-Adapter 节点，最后回退到第一个 LoadImage
            target_node = (pulid_primary_nodes[0] if pulid_primary_nodes
                          else ipa_primary_nodes[0] if ipa_primary_nodes
                          else all_load_nodes[0] if all_load_nodes else None)
            if refs and target_node:
                uploads[target_node] = refs[0]

        # 第二角色
        for i, cid in enumerate(char_ids[1:]):
            refs = self._get_character_refs(cid, outfit=outfit, _no_auto_gen=self.no_auto_gen)
            # 优先用 pulid_ref2 节点，回退到 ipadapter_ref2
            secondary_pool = pulid_secondary_nodes + ipa_secondary_nodes
            if refs and i < len(secondary_pool):
                uploads[secondary_pool[i]] = refs[0]

        # 场景图
        depth_map = shot.get("depth_map", "")
        scene_ref = shot.get("scene_ref", "")
        if depth_map and scene_nodes:
            uploads[scene_nodes[0]] = depth_map
        elif scene_ref and scene_nodes:
            uploads[scene_nodes[0]] = scene_ref

        return uploads

    # ── 内部方法 ──────────────────────────────────────────

    def _get_character_refs(self, char_id: str, outfit: str = "", *, _no_auto_gen: bool = False) -> list[str]:
        """获取角色面部一致性参考图（IP-Adapter/PuLID 注入用）

        返回单元素列表 [最佳正面照路径]，而非角色目录下的全部图片。
        五视图（left_side/back 等）不是面部一致性参考图，不应混入。

        优先级：outfit cover.png → 角色 cover.png → 自动定妆照 → 全局共享库

        Args:
            _no_auto_gen: 内部标志，禁止自动触发 ensure_portrait（防止递归）
        """
        cache_key = f"{char_id}:{outfit}"
        if cache_key in self._refs_cache:
            return self._refs_cache[cache_key]

        from engines.portrait import ensure_portrait
        char_dir = self._paths.character_asset_dir(char_id)

        # 1. 优先查找 outfit 专属参考图（outfit/<key>/cover.png）
        if outfit:
            outfit_cover = self._paths.character_outfit_dir(char_id, outfit) / "cover.png"
            if outfit_cover.exists():
                result = [str(outfit_cover)]
                self._refs_cache[cache_key] = result
                return result

        # 2. 角色正面定妆照（cover.png）
        cover = char_dir / "cover.png"
        if cover.exists():
            result = [str(cover)]
            self._refs_cache[cache_key] = result
            return result

        # 3. 尝试自动定妆照
        if _no_auto_gen:
            self._refs_cache[cache_key] = []
            return []
        portrait = ensure_portrait(char_id, self.config,
                                   self._get_container(),
                                   force=self.force)
        if portrait:
            self._refs_cache[cache_key] = [portrait]
            return [portrait]

        # 4. 全局共享库
        shared_cover = self._paths.shared_assets_dir / "characters" / char_id / "cover.png"
        if shared_cover.exists():
            result = [str(shared_cover)]
            self._refs_cache[cache_key] = result
            return result

        self._refs_cache[cache_key] = []
        return []
