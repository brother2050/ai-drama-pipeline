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

__all__ = ["parse_llm_json", "llm_call_with_retry"]


def llm_call_with_retry(llm, prompt: str, system: str, label: str,
                        max_tokens: int = 4096, retries: int = 3) -> list | dict | None:
    """LLM 调用 + 重试 + JSON 解析（共享工具，消除 llm_generator/shot_calibrator 重复）

    Args:
        llm: LLM 后端实例（需有 .chat() 方法）
        prompt: 用户提示
        system: 系统提示
        label: 日志标签
        max_tokens: 最大 token 数
        retries: 重试次数

    Returns:
        解析后的 JSON 对象（list 或 dict），失败返回 None
    """
    for attempt in range(retries):
        try:
            raw = llm.chat(prompt, system=system, max_tokens=max_tokens)
            result = parse_llm_json(raw)
            if result:
                return result
        except Exception as e:
            logger.warning(f"  ⚠ {label} 生成失败（{attempt+1}/{retries}）: {e}")
        if attempt < retries - 1:
            _time.sleep(2 ** attempt)
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


def parse_llm_json(text: str):
    """从 LLM 响应中提取 JSON（容错：markdown 代码块、前后多余文字、截断修复）"""
    if not text:
        return None
    text = text.strip()

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

    # 4. 单引号 → Python dict
    if "'" in text and '"' not in text:
        try:
            import ast
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            pass

    # 5. 截断修复
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
                pass

    # 6. 全文修复（兜底）
    repaired = _repair_truncated_json(text)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    logger.warning(f"无法从 LLM 回复中提取 JSON（前 200 字）: {text[:200]}")
    return None
