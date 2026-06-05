"""Prompt 工程引擎 — LLM 批量生成模型友好 prompt + ComfyUI Prompt 构建"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field

from engines.shot_utils import strip_dialogue
from infra.constants import is_ascii_only

logger = logging.getLogger(__name__)

__all__ = [
    "PromptBuildParams", "batch_generate_appearance_prompts", "get_view_appearance",
    "build_prompt", "translate_to_english", "batch_translate_to_english",
]


@dataclass
class PromptBuildParams:
    """Prompt 构建参数 — 统一参数对象"""
    shot: dict = field(default_factory=dict)
    character_desc: str = ""
    scene_desc: str = ""
    style: str = "cinematic"
    genre: str = "urban"
    image_backend: str = ""
    registry: object = None  # ModelRegistry 实例
    character_bible: str = ""


def _get_compiler():
    """获取 PromptCompiler 单例"""
    from engines.prompt_compiler import get_compiler
    return get_compiler()


def _get_template(key: str) -> str:
    """从 PromptCompiler 获取模板文本"""
    return _get_compiler().get(key)


# ══════════════════════════════════════════════════════════
#  LLM 批量生成模型友好 prompt（prepare 阶段调用）
# ══════════════════════════════════════════════════════════

def _get_appearance_system() -> str:
    """加载角色外貌 prompt 系统提示（从配置文件）"""
    return _get_template("appearance_prompt_system")


def batch_generate_appearance_prompts(characters: list[dict], llm: object) -> dict[str, dict]:
    """批量生成角色模型友好 prompt — AdaptiveBatchProcessor 自适应分批

    为每个角色生成：
    - appearance_prompt_en: 英文外貌 prompt（用于 AI 绘图）
    - body_features: 身体特征（伤疤/纹身/胎记等）

    Args:
        characters: 角色数据列表（需含 id + appearance 字段）
        llm: LLM 后端实例

    Returns:
        {char_id: {"prompt_en": str, "body_features": str}} 映射
    """
    if not characters or not llm:
        return {}

    from infra.batch_processor import AdaptiveBatchProcessor, estimate_tokens
    from infra.json_parse import parse_llm_json

    processor = AdaptiveBatchProcessor(llm)
    system = _get_appearance_system()

    def build_prompts(batch):
        parts = []
        for i, char in enumerate(batch):
            cid = char.get("id", f"char_{i}")
            appearance = char.get("appearance", "")
            parts.append(f"[角色 {i+1}] id={cid}\n外貌描述：{appearance}")
        return {"system": system, "user": "请为以下每个角色生成 AI 绘图 prompt，按角色编号输出 JSON 数组。\n\n" + "\n\n".join(parts)}

    def parse_result(raw, batch):
        result = parse_llm_json(raw)
        if not result:
            return None
        if isinstance(result, dict):
            result = [result]
        return result if isinstance(result, list) else None

    batch_result = processor.process(
        items=characters,
        build_prompts=build_prompts,
        parse_result=parse_result,
        estimate_item_tokens=lambda c: estimate_tokens(c.get("appearance", "")) + 200,
        estimate_item_output_tokens=lambda _: 800,
    )

    # 用 batch_sizes 精确计算每个 batch 对应的 characters 切片（修复 offset 对齐 bug）
    all_mapping: dict[str, dict] = {}
    offset = 0
    for batch_idx, (batch_data, batch_size) in enumerate(
            zip(batch_result["results"], batch_result["batch_sizes"])):
        if not batch_data:
            offset += batch_size
            continue
        batch_chars = characters[offset:offset + batch_size]
        for i, item in enumerate(batch_data):
            if not isinstance(item, dict):
                continue
            cid = item.get("id", "")
            if not cid and i < len(batch_chars):
                cid = batch_chars[i].get("id", f"char_{i}")
            if cid:
                all_mapping[cid] = {
                    "prompt_en": item.get("prompt_en", ""),
                    "body_features": item.get("body_features", ""),
                }
        offset += batch_size

    failed = batch_result.get("failed_batches", 0)
    if failed:
        raise RuntimeError(
            f"角色 prompt 生成失败（{failed} 批）。请检查 LLM 服务后重试。")

    logger.info(f"  ✅ 批量 prompt 生成完成: {len(all_mapping)}/{len(characters)} 个角色")
    return all_mapping


def get_view_appearance(char: dict, shot_type: str) -> str:
    """获取角色在指定视角的模型友好英文 prompt

    视角映射（5视图）：
    - 特写/近景/中景/全身/过肩 → front
    - 侧面特写 → left_side（默认左侧，无则 right_side，再无则 front）
    - 背面特写 → back
    - 3/4侧/三人全景 → three_quarter

    Args:
        char: 角色数据 dict
        shot_type: 景别（特写/侧面特写/背面特写/全身 等）

    Returns:
        英文 prompt 字符串
    """
    if "背面" in shot_type:
        view_key = "back"
    elif "侧面" in shot_type:
        view_key = "left_side"
    elif "3/4" in shot_type or "三人" in shot_type:
        view_key = "three_quarter"
    else:
        view_key = "front"

    base_en = char.get("appearance_prompt_en", "")
    if not base_en:
        return ""

    body_features = char.get("body_features", "")
    return build_view_prompt(base_en, body_features, view_key)


# ── 视角 prompt 运行时构建 ──────────────────────────────

# 视角前缀（引导 AI 绘图模型理解视角方向）
_VIEW_PREFIX = {
    "front": "front view, facing camera",
    "left_side": "left side view, profile angle",
    "right_side": "right side view, profile angle",
    "back": "back view, from behind",
    "three_quarter": "three-quarter view, angled pose",
}


def build_view_prompt(base_en: str, body_features: str, view: str) -> str:
    """从通用 prompt + 身体特征构建视角专属 prompt

    Args:
        base_en: 通用英文外貌 prompt
        body_features: 逗号分隔的身体特征（伤疤/纹身/胎记等），可为空
        view: 视角 key（front/left_side/right_side/back/three_quarter）

    Returns:
        视角专属英文 prompt
    """
    prefix = _VIEW_PREFIX.get(view, _VIEW_PREFIX["front"])
    parts = [prefix, base_en]

    if body_features and body_features.strip():
        features = body_features.strip()
        # back 视角排除面部特征（眼睛/鼻子/嘴巴/眉毛）
        if view == "back":
            features = _filter_back_features(features)
        parts.append(features)

    return ", ".join(parts)


def _filter_back_features(features: str) -> str:
    """从身体特征中移除面部特征（背面不可见）"""
    face_keywords = {"eye", "nose", "mouth", "lip", "brow", "eyebrow", "eyelash", "forehead", "cheek", "chin"}
    parts = [p.strip() for p in features.split(",") if p.strip()]
    filtered = [p for p in parts if not any(kw in p.lower() for kw in face_keywords)]
    return ", ".join(filtered)


def build_prompt(params: PromptBuildParams) -> str:
    """从镜头数据构建 ComfyUI Prompt"""
    shot = params.shot
    registry = params.registry

    # ── 判断后端 prompt 风格（从注册表查询，不硬编码后端名） ──
    if registry is None:
        from flow.model_registry import ModelRegistry
        registry = ModelRegistry()

    prompt_style = registry.get_prompt_style(params.image_backend) if params.image_backend else "tag"

    # ── 使用 PromptCompiler 编译 ──
    from engines.prompt_compiler import get_compiler
    compiler = get_compiler()

    # 清理输入
    scene_clean = ""
    if params.scene_desc:
        if not is_ascii_only(params.scene_desc):
            from infra.constants import ERR_NOT_PREPARED
            logger.warning(f"场景描述仍为中文，{ERR_NOT_PREPARED}")
        scene_clean = params.scene_desc

    char_clean = params.character_desc.strip() if params.character_desc else ""

    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            action = strip_dialogue(action)
            if not is_ascii_only(action):
                from infra.constants import ERR_NOT_PREPARED
                logger.warning(f"动作描述仍为中文（action_en 缺失），{ERR_NOT_PREPARED}")
    else:
        action = strip_dialogue(action)

    result = compiler.compile_first_frame(
        shot=shot,
        character_desc=char_clean,
        scene_desc=scene_clean,
        style=params.style,
        genre=params.genre,
        prompt_style=prompt_style,
        character_bible=params.character_bible,
    )

    # SD1.5 CLIP 最大 75 tokens，超长时截断
    if prompt_style == "tag":
        result = _truncate_tag_prompt(result, max_tokens=75)

    return result


def _truncate_tag_prompt(prompt: str, max_tokens: int = 75) -> str:
    """将逗号分隔的 tag prompt 截断到指定 token 数以内。

    SD1.5 CLIP tokenizer 限制 75 tokens（不含 start/end token）。
    粗略估算：1 token ≈ 4 字符（英文），按逗号分隔的 tag 边界截断，
    保留前面的 tag（style/genre/scene/character 优先），丢弃末尾溢出部分。
    """
    est_tokens = len(prompt) / 4
    if est_tokens <= max_tokens:
        return prompt

    # 按逗号拆分，逐个 tag 累加，超出限制时截断
    char_limit = max_tokens * 4
    tags = [t.strip() for t in prompt.split(",") if t.strip()]
    result = []
    char_count = 0
    for tag in tags:
        tag_cost = len(tag) / 4 + 1
        if char_count + tag_cost > char_limit:
            break
        result.append(tag)
        char_count += len(tag) + 2  # ", " = 2 chars

    truncated = ", ".join(result)
    if len(truncated) < len(prompt):
        logger.info(f"SD1.5 prompt 截断: {len(prompt)} → {len(truncated)} 字符 "
                    f"(保留 {len(result)}/{len(tags)} 个 tag)")
    return truncated


# ══════════════════════════════════════════════════════════
#  LLM 翻译（场景、动作、台词等非外貌文本）
# ══════════════════════════════════════════════════════════

def _get_translate_system() -> str:
    """加载翻译系统提示（从配置文件）"""
    return _get_template("translate_system") or "You are a professional translator. Output only the translation, no explanations."


def translate_to_english(text: str, llm: object = None) -> str:
    """中文→英文翻译（LLM）"""
    if not text:
        return ""
    if is_ascii_only(text):
        return text
    if not llm:
        logger.warning(f"LLM 不可用，中文描述将原样传入（可能无效）: {text[:50]}...")
        return text
    try:
        result = llm.chat(f"Translate to English: {text}", system=_get_translate_system())
        return result.strip() if result and result.strip() else text
    except Exception as e:
        logger.warning(f"翻译失败: {e}")
        return text


def _get_batch_translate_system() -> str:
    """加载批量翻译系统提示（从配置文件）"""
    return _get_template("batch_translate_system") or "You are a professional translator. The user will send numbered Chinese texts.\nTranslate each to English. Output ONLY the translations, one per line, keeping the same numbering.\nDo not add explanations. If a line is already English, output it unchanged."


def batch_translate_to_english(texts: list[str], llm: object = None) -> list[str]:
    """批量中→英翻译（自适应分批，token 感知）"""
    if not llm:
        return [translate_to_english(t, llm=None) for t in texts]

    need_idx, need_text, results = _split_translate_texts(texts)
    if not need_text:
        return results

    from infra.batch_processor import AdaptiveBatchProcessor, estimate_tokens
    processor = AdaptiveBatchProcessor(llm)
    system_prompt = _get_batch_translate_system()
    batch_items = list(zip(need_idx, need_text))

    batch_result = processor.process(
        items=batch_items,
        build_prompts=lambda batch: {"system": system_prompt, "user": "\n".join(f"{i+1}. {t}" for i, (_, t) in enumerate(batch))},
        parse_result=lambda raw, batch: _parse_numbered_lines(raw),
        estimate_item_tokens=lambda item: estimate_tokens(item[1]),
    )

    _merge_translate_results(results, batch_items, batch_result, llm)
    return results


def _split_translate_texts(texts: list[str]) -> tuple[list[int], list[str], list[str]]:
    """分离需要翻译的文本 → (indices, texts_to_translate, results_array)"""
    need_idx, need_text = [], []
    results = [""] * len(texts)
    for i, t in enumerate(texts):
        if not t:
            results[i] = ""
        elif is_ascii_only(t):
            results[i] = t
        else:
            need_idx.append(i)
            need_text.append(t)
    return need_idx, need_text, results


def _parse_numbered_lines(raw: str) -> dict:
    """解析编号行（1. text → {1: text}）"""
    parsed = {}
    for line in raw.strip().splitlines():
        m = re.match(r"^(\d+)\s*[.)]\s*(.+)", line.strip())
        if m:
            parsed[int(m.group(1))] = m.group(2).strip()
    return parsed


def _merge_translate_results(results: list[str], batch_items: list[tuple[int, str]], batch_result: dict, llm: object = None) -> None:
    """合并批次翻译结果，未翻译的回退单条翻译

    batch_result 结构: {"results": [...], "batch_sizes": [...], "total_batches": N}
    每个 parsed_dict 是 {line_num: translated_text}，None 表示批次失败。
    """
    total_items = len(batch_items)
    batch_sizes = batch_result.get("batch_sizes", [])
    offset = 0

    for batch_idx, batch_data in enumerate(batch_result["results"]):
        # 使用精确 batch_size（来自 AdaptiveBatchProcessor），回退到均匀分配
        if batch_idx < len(batch_sizes):
            batch_len = batch_sizes[batch_idx]
        else:
            remaining = total_items - offset
            batches_left = len(batch_result["results"]) - batch_idx
            batch_len = max(remaining // max(batches_left, 1), 1) if remaining > 0 else 0

        if batch_data is None:
            offset += batch_len
            continue
        for local_idx in range(batch_len):
            if offset + local_idx >= total_items:
                break
            orig_idx, orig_text = batch_items[offset + local_idx]
            translated = batch_data.get(local_idx + 1, "")
            if translated:
                results[orig_idx] = translated
        offset += batch_len

    for orig_idx, orig_text in batch_items:
        if not results[orig_idx]:
            results[orig_idx] = translate_to_english(orig_text, llm=llm)
