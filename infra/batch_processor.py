"""自适应批处理器 — 双重约束分批 + 容错隔离 + 错误驱动学习

- 双重约束分批（input token + output token）
- 60K token 硬上限防 Lost-in-the-Middle
- 单批次失败不影响其他批次（容错隔离）
- 单批次重试（指数退避）
- 从 API 错误中自动学习模型真实限制
"""
from __future__ import annotations

import logging

import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["AdaptiveBatchProcessor", "estimate_tokens"]

# ── 常量 ──

HARD_CAP_TOKENS = 60000  # 无论模型支持多大上下文，每批 input 最多 60K
MAX_BATCH_RETRIES = 2    # 单批次最大重试次数
RETRY_BASE_DELAY = 3     # 重试基础延迟（秒），指数退避


def estimate_tokens(text: str) -> int:
    """保守估算 token 数（宁可高估多分批，也不低估撞限制）

    中文约 1 token/汉字，英文约 1 token/4 字符。
    """
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cjk
    return max(1, int(cjk + other / 4))


def _execute_batches(processor, batches, build_prompts, parse_result, on_progress) -> dict:
    """逐批执行（带重试 + 容错隔离）"""
    all_results = []
    batch_sizes = []
    failed = 0
    for i, batch in enumerate(batches):
        batch_sizes.append(len(batch))
        if on_progress:
            on_progress(i, len(batches), f"批次 {i+1}/{len(batches)}...")
        try:
            result = processor._execute_with_retry(batch, build_prompts, parse_result)
            all_results.append(result)
        except Exception as e:
            failed += 1
            logger.error(f"批次 {i+1} 最终失败: {e}")
            all_results.append(None)
        processor._learn_from_last_error()

    if on_progress:
        on_progress(len(batches), len(batches),
                    f"完成 ({failed} 批失败)" if failed else "全部成功")
    return {"results": all_results, "batch_sizes": batch_sizes,
            "failed_batches": failed, "total_batches": len(batches)}


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

    def __init__(self, llm, *, model_name: str = "",
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
        self._input_budget = min(int(limits["context_window"] * 0.6), hard_cap_tokens)
        self._output_budget = int(limits["max_output"] * 0.8)  # 留 20% 给格式开销
        self._last_error: Exception | None = None

    def _get_limits(self, llm) -> dict:
        """从 ModelRegistry 查询模型限制，带 fallback"""
        try:
            from flow.model_registry import ModelRegistry
            reg = ModelRegistry()
            model = self._model_name or getattr(llm, "_model", "")
            if model:
                return reg.get_model_limits(model)
        except Exception as e:
            logger.debug(f"模型限制查询失败，使用默认值: {e}")
        return {"context_window": 8192, "max_output": 4096}

    def process(
        self,
        items: list[Any],
        build_prompts: Callable[[list[Any]], dict],
        parse_result: Callable[[str, list[Any]], Any],
        *,
        estimate_item_tokens: Callable[[Any], int] | None = None,
        estimate_item_output_tokens: Callable[[Any], int] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """自适应批处理"""
        if not items:
            return {"results": [], "failed_batches": 0, "total_batches": 0}

        get_input = estimate_item_tokens or (lambda item: estimate_tokens(str(item)))
        get_output = estimate_item_output_tokens or (lambda _: 300)
        sample = build_prompts([items[0]])
        system_tokens = estimate_tokens(sample.get("system", ""))
        batches = self._create_batches(items, get_input, get_output, system_tokens)

        logger.info(f"自适应分批: {len(items)} 项 → {len(batches)} 批 ({[len(b) for b in batches]})")
        if on_progress:
            on_progress(0, len(batches), f"开始处理 {len(batches)} 批...")

        return _execute_batches(self, batches, build_prompts, parse_result, on_progress)

    def _create_batches(
        self,
        items: list[Any],
        get_input: Callable, get_output: Callable,
        system_tokens: int,
    ) -> list[list[Any]]:
        """双重约束贪心分组

        约束 1: system_tokens + sum(item_input) ≤ input_budget
        约束 2: sum(item_output) ≤ output_budget
        """
        batches: list[list[Any]] = []
        current: list[Any] = []
        cur_input = system_tokens
        cur_output = 0

        for item in items:
            item_in = get_input(item)
            item_out = get_output(item)

            exceed_input = cur_input + item_in > self._input_budget
            exceed_output = cur_output + item_out > self._output_budget

            if current and (exceed_input or exceed_output):
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
        build_prompts: Callable, parse_result: Callable,
    ) -> Any:
        """执行单个批次，带指数退避重试"""
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                prompts = build_prompts(batch)
                raw = self._llm.chat(
                    prompts["user"],
                    system=prompts.get("system", ""),
                    max_tokens=self._output_budget,
                )
                return parse_result(raw, batch)
            except Exception as e:
                last_error = e
                # 记录错误用于学习
                self._last_error = e
                if attempt < self._max_retries:
                    wait = self._retry_base_delay * (2 ** attempt)
                    logger.warning(f"批次失败 (尝试 {attempt+1}), {wait}s 后重试: {e}")
                    time.sleep(wait)
        raise last_error

    def _learn_from_last_error(self) -> None:
        """从 API 错误中学习模型限制"""
        if not self._last_error:
            return
        error_text = str(self._last_error)
        try:
            from flow.model_registry import ModelRegistry
            limits = ModelRegistry.parse_limits_from_error(error_text)
            if limits and self._model_name:
                ModelRegistry.cache_discovered_limits(self._model_name, limits)
                logger.info(f"从错误中学习到 {self._model_name} 限制: {limits}")
        except Exception as e:
            logger.debug(f"错误学习失败: {e}")
        finally:
            self._last_error = None
