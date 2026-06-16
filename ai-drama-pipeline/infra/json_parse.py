"""JSON 解析工具 — 统一的 LLM 输出解析器

提供容错的 JSON 解析能力，支持：
- markdown 代码块提取
- 前后多余文字过滤
- 截断 JSON 自动修复（LLM 输出因 token 限制被截断）
- 单引号 / Python dict 风格兼容
"""
from __future__ import annotations

import json
import logging
import re
import time as _time

logger = logging.getLogger(__name__)

__all__ = ["parse_llm_json", "llm_call_with_retry", "get_max_output_tokens"]


def get_max_output_tokens(llm: object, default: int = 4096) -> int:
    """从 models_registry.yaml 查询 LLM 模型的 max_output，受实际 context_length 约束

    注册表的 max_output 是理论值（如 8192），但本地模型（llama.cpp/GGUF）的
    实际上下文窗口可能更小（如 4096）。此函数取两者较小值，避免请求超出
    模型能力的 token 数导致输出截断。
    """
    model = getattr(llm, "_model", None)
    if not model:
        return default
    try:
        from infra.config.registry import ModelRegistry
        limits = ModelRegistry().get_model_limits(model)
        max_output = limits.get("max_output", default)
        # 检查模型实际 context_length（通过 property 触发 API 查询）
        try:
            actual_ctx = llm.context_length if hasattr(llm, "context_length") else 0
        except Exception:
            actual_ctx = 0
        if actual_ctx > 0:
            # max_output 不能超过 context 的 60%（留给输入 prompt 足够空间）
            cap = int(actual_ctx * 0.6)
            if max_output > cap:
                logger.info(f"max_output 从 {max_output} 降到 {cap}（模型 context={actual_ctx}）")
                max_output = cap
        return max_output
    except Exception:
        return default


def llm_call_with_retry(llm: object, prompt: str, system: str, label: str,
                        max_tokens: int = 4096, retries: int = 3) -> list | dict | None:
    """LLM 调用 + 重试 + JSON 解析（共享工具，消除 llm_generator 重复）

    Args:
        llm: LLM 后端实例（需有 .chat() 方法）
        prompt: 用户提示
        system: 系统提示
        label: 日志标签
        max_tokens: 最大 token 数
        retries: 重试次数

    Returns:
        解析后的 JSON 对象（list 或 dict），失败返回 None
        失败详情可通过 llm_call_with_retry.last_error 获取
    """
    llm_call_with_retry.last_error = ""
    llm_call_with_retry.last_raw = ""
    for attempt in range(retries):
        try:
            raw = llm.chat(prompt, system=system, max_tokens=max_tokens)
            if not raw:
                llm_call_with_retry.last_error = "LLM 返回空内容"
                logger.warning(f"  ⚠ {label} 生成失败（{attempt+1}/{retries}）: LLM 返回空内容")
                continue
            llm_call_with_retry.last_raw = raw[:2000]
            result = parse_llm_json(raw)
            if result:
                return result
            # 解析失败 — 记录足够诊断的原始输出
            llm_call_with_retry.last_error = f"JSON 解析失败（输出前 200 字: {raw[:200]}）"
            logger.warning(
                f"  ⚠ {label} 解析失败（{attempt+1}/{retries}）: 无法解析为 JSON\n"
                f"    原始输出 len={len(raw)}, 前 500 字: {raw[:500]!r}\n"
                f"    原始输出末 200 字: {raw[-200:]!r}")
        except Exception as e:
            logger.warning(f"  ⚠ {label} 生成失败（{attempt+1}/{retries}）: {e}")
        if attempt < retries - 1:
            _time.sleep(2 ** attempt)
    logger.error(f"  ✗ {label} 生成完全失败（已重试 {retries} 次）")
    return None


def _scan_json_structure(text: str) -> tuple[list[str], int, bool]:
    """扫描 JSON 结构 → (未闭合括号栈, 最后安全位置, 是否在字符串中)"""
    stack: list[str] = []
    in_string = False
    escape = False
    last_safe = -1
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '[':
            stack.append(']')
        elif ch == '{':
            stack.append('}')
        elif ch in (']', '}'):
            if stack and stack[-1] == ch:
                stack.pop()
                last_safe = i
        elif ch == ',':
            if not stack:
                last_safe = i
    return stack, last_safe, in_string


def _try_close_brackets(text: str, stack: list[str], in_string: bool) -> str | None:
    """尝试补全未闭合括号，返回修复后的字符串或 None"""
    candidate = text
    if in_string:
        for j in range(len(candidate) - 1, -1, -1):
            if candidate[j] in (',', '[', '{'):
                candidate = candidate[:j + 1]
                break
        else:
            candidate = ""

    candidate = candidate.rstrip(", \t\n\r")
    if candidate.endswith(':'):
        candidate = candidate[:-1].rstrip(", \t\n\r")

    closing = ''.join(reversed(stack))
    repaired = candidate + closing
    try:
        json.loads(repaired)
        return repaired
    except json.JSONDecodeError:
        for j in range(len(candidate) - 1, max(0, len(candidate) - 200), -1):
            if candidate[j] == ',':
                attempt = candidate[:j] + closing
                try:
                    json.loads(attempt)
                    return attempt
                except json.JSONDecodeError:
                    continue
    return None


def _repair_truncated_json(text: str) -> str | None:
    """尝试修复被截断的 JSON（LLM 输出常因 token 限制被截断）"""
    if not text:
        return None
    cleaned = text.rstrip().rstrip(", \t\n\r")
    if not cleaned:
        return None

    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    stack, last_safe, in_string = _scan_json_structure(cleaned)

    # 情况1：完整 JSON，只是末尾有垃圾
    if not stack and last_safe >= 0:
        candidate = cleaned[:last_safe + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 情况2：JSON 被截断，补全闭合括号
    if stack:
        return _try_close_brackets(cleaned, stack, in_string)
    return None


def _extract_json_block(text: str) -> object | None:
    """从文本中提取第一个完整 JSON 数组/对象（深度匹配）"""
    for start_ch, end_ch in [('[', ']'), ('{', '}')]:
        idx = text.find(start_ch)
        if idx < 0:
            continue
        depth, in_str, escape = 0, False, False
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == start_ch:
                depth += 1
            elif c == end_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        fixed = re.sub(r',\s*([\]}])', r'\1', candidate)
                        try:
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            break
    return None


def _strip_thinking_blocks(text: str) -> str:
    """移除 LLM 思考/推理内容（<think>...</think> 和 reasoning_content 前缀）

    现代推理模型（DeepSeek-R1、Qwen3 等）可能在 JSON 输出前插入思考过程，
    或在 content 中直接包含 <think> 标签。此函数统一清理。
    """
    # 移除 <think>...</think> 块（含变体 <|thinking|>...</think>）
    text = re.sub(r'<(?:think|thinking|thought)\b[^>]*>.*?</(?:think|thinking|thought)\s*>',
                  '', text, flags=re.DOTALL | re.IGNORECASE)
    # 移除未闭合的 <think> 前缀（模型截断时可能只有开头没有结尾）
    text = re.sub(r'<(?:think|thinking|thought)\b[^>]*>.*$', '', text,
                  flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def parse_llm_json(text: str) -> object | None:
    """从 LLM 响应中提取 JSON（容错：markdown 代码块、前后多余文字、思考块、截断修复）"""
    if not text:
        return None
    text = text.strip()

    # 0. 清理思考/推理块（DeepSeek-R1、Qwen3 等模型）
    cleaned = _strip_thinking_blocks(text)
    if cleaned != text:
        text = cleaned
        logger.debug("已移除 LLM 思考块")

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. markdown 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 深度匹配提取
    result = _extract_json_block(text)
    if result is not None:
        return result

    # 4. 单引号 → Python dict（限制长度防止 ast.literal_eval DoS）
    if "'" in text and '"' not in text and len(text) < 50000:
        try:
            import ast
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            pass

    # 5. 截断修复（先从第一个括号开始）
    first_bracket = -1
    for ch in ('{', '['):
        idx = text.find(ch)
        if idx != -1 and (first_bracket == -1 or idx < first_bracket):
            first_bracket = idx
    if first_bracket != -1:
        repaired = _repair_truncated_json(text[first_bracket:])
        if repaired is not None:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                logger.debug(f"JSON 解析跳过: {text[:50]}...")
                pass

    # 6. 全文修复（兜底）
    repaired = _repair_truncated_json(text)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # 7. 最后尝试：剥离所有非 JSON 前缀文本（某些模型在 JSON 前加说明文字）
    for ch, end_ch in [('[', ']'), ('{', '}')]:
        idx = text.find(ch)
        if idx > 0:
            candidate = text[idx:]
            # 先试直接解析
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
            # 再试截断修复
            repaired = _repair_truncated_json(candidate)
            if repaired is not None:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    logger.warning(f"无法从 LLM 回复中提取 JSON（len={len(text)}, 前 200 字）: {text[:200]}")
    return None
