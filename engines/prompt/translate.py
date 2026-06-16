"""翻译功能 — 中→英翻译"""

from __future__ import annotations

import logging
import re

from engines.prompt.compiler import tpl

logger = logging.getLogger(__name__)


def translate_to_english(text: str, llm: object = None) -> str:
    """中文→英文翻译（LLM）。失败返回空串，不回退到原文。"""
    if not text:
        return ""
    if text.isascii():
        return text
    if not llm:
        logger.warning(f"LLM 不可用，跳过翻译: {text[:50]}...")
        return ""
    try:
        result = llm.chat(f"Translate to English: {text}",
                          system=tpl("translate_system"))
        if not result or not result.strip():
            return ""
        from infra.json_parse import _strip_thinking_blocks
        cleaned = _strip_thinking_blocks(result.strip())
        return cleaned
    except Exception as e:
        logger.warning(f"翻译失败: {e}")
        return ""


def batch_translate_to_english(texts: list[str], llm: object = None) -> list[str]:
    """批量中→英翻译（自适应分批，token 感知 + 短编码精确对齐）"""
    if not llm:
        return [translate_to_english(t, llm=None) for t in texts]

    need_idx, need_text, results = _split_translate_texts(texts)
    if not need_text:
        return results

    uid_map: dict[str, int] = {}
    batch_items: list[tuple[int, str, str]] = []
    for seq, (orig_idx, text) in enumerate(zip(need_idx, need_text)):
        uid = f"t{seq:06x}"
        uid_map[uid] = orig_idx
        batch_items.append((orig_idx, uid, text))

    from infra.concurrency.batch import AdaptiveBatchProcessor, estimate_tokens
    processor = AdaptiveBatchProcessor(llm)
    system_prompt = tpl("batch_translate_system")

    def build_prompts(batch):
        tagged = []
        for _, uid, text in batch:
            tagged.append(f"[{uid}] {text}")
        return {"system": system_prompt, "user": "\n".join(tagged)}

    batch_result = processor.process(
        items=batch_items,
        build_prompts=build_prompts,
        parse_result=lambda raw, batch: _parse_tagged_lines(raw),
        estimate_item_tokens=lambda item: estimate_tokens(item[2]),
        estimate_item_output_tokens=lambda item: int(estimate_tokens(item[2]) * 2.5),
    )

    _merge_translate_results(results, batch_items, batch_result, uid_map, llm)
    return results


def _split_translate_texts(texts: list[str]) -> tuple[list[int], list[str], list[str]]:
    """分离需要翻译的文本"""
    need_idx, need_text = [], []
    results = [""] * len(texts)
    for i, t in enumerate(texts):
        if t and not t.isascii():
            need_idx.append(i)
            need_text.append(t)
        elif t:
            results[i] = t
    return need_idx, need_text, results


def _parse_tagged_lines(raw: str) -> dict[str, str]:
    """解析短编码标记行"""
    if not isinstance(raw, str):
        return {}
    from infra.json_parse import _strip_thinking_blocks
    raw = _strip_thinking_blocks(raw)

    _RE_TAG = re.compile(r'^\[(t[a-fA-F0-9]{6})\]\s*(.*)')
    parsed: dict[str, str] = {}
    for line in raw.strip().splitlines():
        m = _RE_TAG.match(line.strip())
        if m:
            uid = m.group(1).lower()
            parsed[uid] = m.group(2).strip()
    return parsed


def _merge_translate_results(
    results: list[str],
    batch_items: list[tuple[int, str, str]],
    batch_result: dict,
    uid_map: dict[str, int],
    llm: object = None,
) -> None:
    """合并批次翻译结果"""
    total_items = len(batch_items)
    batch_sizes = batch_result["batch_sizes"]
    offset = 0
    missing: list[tuple[int, str, str]] = []

    for batch_idx, batch_data in enumerate(batch_result["results"]):
        if batch_idx < len(batch_sizes):
            batch_len = batch_sizes[batch_idx]
        else:
            batch_len = total_items - offset
            if batch_len <= 0:
                break

        if batch_data is None or not isinstance(batch_data, dict):
            for i in range(batch_len):
                if offset + i >= total_items:
                    break
                missing.append(batch_items[offset + i])
            offset += batch_len
            continue

        batch_slice = batch_items[offset:offset + batch_len]
        for orig_idx, uid, orig_text in batch_slice:
            translated = batch_data.get(uid, "")
            if translated:
                results[orig_idx] = translated
            else:
                missing.append((orig_idx, uid, orig_text))
        offset += batch_len

    if not missing:
        return

    logger.warning(f"批处理后 {len(missing)} 项未翻译，用小批次重试...")
    _retry_missing_in_small_batches(results, missing, uid_map, llm)


def _retry_missing_in_small_batches(
    results: list[str],
    missing: list[tuple[int, str, str]],
    uid_map: dict[str, int],
    llm: object,
) -> None:
    """将未翻译的项用小批次重试"""
    if not llm or not missing:
        return

    SMALL_BATCH = 10
    batches = [missing[i:i + SMALL_BATCH] for i in range(0, len(missing), SMALL_BATCH)]
    system_prompt = tpl("batch_translate_system")

    for bi, batch in enumerate(batches):
        try:
            tagged = [f"[{uid}] {text}" for _, uid, text in batch]
            user_msg = "\n".join(tagged)
            raw = llm.chat(user_msg, system=system_prompt)
            parsed = _parse_tagged_lines(raw)

            for orig_idx, uid, orig_text in batch:
                translated = parsed.get(uid, "")
                if translated:
                    results[orig_idx] = translated
        except Exception as e:
            logger.warning(f"小批次 {bi+1} 重试失败: {e}")
