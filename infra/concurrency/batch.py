"""自适应批处理器 — 三重约束分批 + 容错隔离 + 错误驱动学习

- 三重约束分批（input token + output token + 最大项数防超时）
- 60K token 硬上限防 Lost-in-the-Middle
- 单批次失败不影响其他批次（容错隔离）
- 单批次重试（指数退避）
- 从 API 错误中自动学习模型真实限制
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["AdaptiveBatchProcessor", "estimate_tokens"]


def estimate_tokens(text: str) -> int:
    """保守估算 token 数（宁可高估多分批，也不低估撞限制）

    估算策略：
    - CJK 汉字/标点：约 1 token/字
    - 英文单词：约 1 token/word（平均 4-5 chars/word）
    - 数字/标点/空格等：约 1 token/字符
    - 字符级下界：len(text) // 3（防止长连续字符被低估为 1 token）
    """
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'  # CJK 统一汉字
              or '\u3000' <= c <= '\u303f'  # CJK 标点符号
              or '\uff00' <= c <= '\uffef')  # 全角标点
    # 英文单词（每个单词约 1 token）
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其他字符（数字、标点、空格等）：约 1 token/字符
    english_chars = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    other = len(text) - cjk - english_chars
    word_based = cjk + english_words + other
    # 字符级下界：防止 "XXXXX..." 类长连续字符被低估为 1 token
    char_floor = len(text) // 3
    return max(1, word_based, char_floor)


def _execute_batches(
    processor: AdaptiveBatchProcessor,
    batches: list[list[Any]],
    build_prompts: Callable[[list[Any]], dict],
    parse_result: Callable[[str, list[Any]], Any],
    on_progress: Callable[[int, int, str], None] | None,
    on_batch_complete: Callable[[int, Any, list[Any]], None] | None = None,
) -> dict[str, Any]:
    """逐批执行（带重试 + 容错隔离 + 统计 + 增量持久化回调）

    on_batch_complete(batch_index, batch_result, batch_items):
        每批次成功后立即调用，用于增量保存（防止中途崩溃丢失已生成内容）。
    """
    all_results = []
    batch_sizes = []
    failed = 0
    total_attempts = 0
    t0 = time.monotonic()
    for i, batch in enumerate(batches):
        batch_sizes.append(len(batch))
        if on_progress:
            on_progress(i, len(batches), f"批次 {i+1}/{len(batches)}...")
        try:
            result, attempts = processor._execute_with_retry(batch, build_prompts, parse_result)
            all_results.append(result)
            total_attempts += attempts
            if result is None:
                failed += 1
            # 增量持久化：批次成功后立即回调（防止中途崩溃）
            elif on_batch_complete:
                try:
                    on_batch_complete(i, result, batch)
                except Exception as cb_err:
                    logger.warning(f"批次完成回调异常（不影响主流程）: {cb_err}")
        except Exception as e:
            failed += 1
            total_attempts += processor._max_retries + 1
            logger.error(f"批次 {i+1} 最终失败: {e}")
            all_results.append(None)
            processor._learn_from_last_error()

    elapsed = round(time.monotonic() - t0, 2)
    if on_progress:
        on_progress(len(batches), len(batches),
                    f"完成 ({failed} 批失败)" if failed else "全部成功")
    return {"results": all_results, "batch_sizes": batch_sizes,
            "failed_batches": failed, "total_batches": len(batches),
            "total_items": sum(batch_sizes), "retries": total_attempts,
            "elapsed": elapsed}


class AdaptiveBatchProcessor:
    """自适应批处理器

    用法:
        processor = AdaptiveBatchProcessor(llm)
        results = processor.process(
            items=texts,
            build_prompts=lambda batch: {"system": "...", "user": "\\n".join(batch)},
            parse_result=lambda raw, batch: raw.strip().splitlines(),
        )
    """

    def __init__(self, llm: Any, *, model_name: str = "",
                 hard_cap_tokens: int = 60000,
                 max_retries: int = 2,
                 retry_base_delay: float = 3.0):
        """
        Args:
            llm: LLM 后端实例（需有 chat 方法和 context_length 属性）
            model_name: 模型名（为空时从 llm 推断）
        """
        self._llm = llm
        self._model_name = model_name or getattr(llm, "_model", "") or ""
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

        # 从注册表查询模型限制
        limits = self._get_limits(llm)
        self._max_output = int(limits["max_output"])           # API 真实上限（不打折）
        self._input_budget = min(int(limits["context_window"] * 0.6), hard_cap_tokens)
        self._output_budget = int(limits["max_output"] * 0.8)  # 分批决策用（留 20% 给格式开销）
        # 最大批内项数：防止 LLM 生成太慢导致 HTTP 超时
        # 默认 15 项/批（翻译任务约 80 output tokens/项，15 项 ≈ 1200 tokens，约 30-60s）
        self._max_items_per_batch = limits.get("max_items_per_batch", 15)
        self._last_error: Exception | None = None

    def _get_limits(self, llm: Any) -> dict[str, int]:
        """从 ModelRegistry 查询模型限制，带 fallback"""
        try:
            from infra.config.registry import ModelRegistry
            reg = ModelRegistry()
            model = self._model_name or getattr(llm, "_model", "")
            if model:
                return reg.get_model_limits(model)
        except Exception as e:
            logger.debug(f"模型限制查询失败，使用默认值: {e}")
        return {"context_window": 32768, "max_output": 8192}

    def process(
        self,
        items: list[Any],
        build_prompts: Callable[[list[Any]], dict],
        parse_result: Callable[[str, list[Any]], Any],
        *,
        estimate_item_tokens: Callable[[Any], int] | None = None,
        estimate_item_output_tokens: Callable[[Any], int] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_batch_complete: Callable[[int, Any, list[Any]], None] | None = None,
    ) -> dict:
        """自适应批处理

        on_batch_complete(batch_index, batch_result, batch_items):
            每批次成功后立即回调，用于增量持久化。
        """
        if not items:
            return {"results": [], "failed_batches": 0, "total_batches": 0,
                    "total_items": 0, "retries": 0, "elapsed": 0}

        get_input = estimate_item_tokens or (lambda item: estimate_tokens(str(item)))
        # output 默认值：取 300 和 input 估算的较大者，避免低估
        if estimate_item_output_tokens:
            get_output = estimate_item_output_tokens
        else:
            def get_output(item): return max(300, get_input(item))
        sample = build_prompts([items[0]])
        system_tokens = estimate_tokens(sample.get("system", ""))
        batches = self._create_batches(items, get_input, get_output, system_tokens)

        total_input = sum(get_input(it) for it in items)
        total_output = sum(get_output(it) for it in items)
        logger.info(
            f"自适应分批: {len(items)} 项 → {len(batches)} 批 ({[len(b) for b in batches]}), "
            f"估算 input≈{total_input} output≈{total_output}, "
            f"预算 input={self._input_budget} output={self._output_budget} "
            f"max_items={self._max_items_per_batch}")
        if on_progress:
            on_progress(0, len(batches), f"开始处理 {len(batches)} 批...")

        result = _execute_batches(self, batches, build_prompts, parse_result, on_progress,
                                  on_batch_complete=on_batch_complete)
        logger.info(
            f"自适应批处理完成: {result['total_items']} 项, {result['total_batches']} 批, "
            f"{result['failed_batches']} 批失败, {result['retries']} 次重试, "
            f"耗时 {result['elapsed']}s")
        return result

    def _create_batches(
        self,
        items: list[Any],
        get_input: Callable[[Any], int],
        get_output: Callable[[Any], int],
        system_tokens: int,
    ) -> list[list[Any]]:
        """三重约束贪心分组

        约束 1: system_tokens + sum(item_input) ≤ input_budget
        约束 2: sum(item_output) ≤ output_budget
        约束 3: len(batch) ≤ max_items_per_batch（防 HTTP 超时）

        单个超预算项独立成批（宁可超限也不丢弃，由重试机制兜底）。
        """
        batches: list[list[Any]] = []
        current: list[Any] = []
        cur_input = system_tokens
        cur_output = 0

        for item in items:
            item_in = get_input(item)
            item_out = get_output(item)

            # 单个超预算项：独立成批，不和别人混
            if item_in > self._input_budget or item_out > self._output_budget:
                if current:
                    batches.append(current)
                    current = []
                    cur_input = system_tokens
                    cur_output = 0
                batches.append([item])
                logger.warning(f"单个超预算项独立成批: input≈{item_in} output≈{item_out}")
                continue

            exceed_input = cur_input + item_in > self._input_budget
            exceed_output = cur_output + item_out > self._output_budget
            exceed_count = len(current) >= self._max_items_per_batch

            if current and (exceed_input or exceed_output or exceed_count):
                batches.append(current)
                current = []
                cur_input = system_tokens
                cur_output = 0

            current.append(item)
            cur_input += item_in
            cur_output += item_out

        if current:
            batches.append(current)

        return batches

    def _execute_with_retry(
        self, batch: list[Any],
        build_prompts: Callable[[list[Any]], dict],
        parse_result: Callable[[str, list[Any]], Any],
    ) -> tuple[Any, int]:
        """执行单个批次，带指数退避重试（含 JSON 解析失败重试）。返回 (result, total_attempts)。

        LLM 每次调用是非确定性的，JSON 解析失败后重新调用 LLM 可能得到合法输出。
        """
        for attempt in range(self._max_retries + 1):
            try:
                prompts = build_prompts(batch)
                raw = self._llm.chat(
                    prompts["user"],
                    system=prompts.get("system", ""),
                    max_tokens=self._max_output,
                )
                result = parse_result(raw, batch)
                if result is not None:
                    return result, attempt + 1
                # JSON 解析失败 → 重试 LLM 调用（非确定性，下次可能输出合法 JSON）
                if attempt < self._max_retries:
                    wait = self._retry_base_delay * (2 ** attempt)
                    logger.warning(f"JSON 解析失败, {wait}s 后重试 LLM (尝试 {attempt+1}/{self._max_retries + 1}): {raw[:120]!r}")
                    time.sleep(wait)
                else:
                    return None, attempt + 1
            except Exception as e:
                self._last_error = e
                if attempt < self._max_retries:
                    wait = self._retry_base_delay * (2 ** attempt)
                    logger.warning(f"批次失败 (尝试 {attempt+1}/{self._max_retries + 1}), {wait}s 后重试: {e}")
                    time.sleep(wait)
        return None, self._max_retries + 1

    def _learn_from_last_error(self) -> None:
        """从 API 错误中学习模型限制"""
        if not self._last_error:
            return
        error_text = str(self._last_error)
        try:
            from infra.config.registry import ModelRegistry
            limits = ModelRegistry.parse_limits_from_error(error_text)
            if limits and self._model_name:
                ModelRegistry.cache_discovered_limits(self._model_name, limits)
                logger.info(f"从错误中学习到 {self._model_name} 限制: {limits}")
        except Exception as e:
            logger.debug(f"错误学习失败: {e}")
        finally:
            self._last_error = None
