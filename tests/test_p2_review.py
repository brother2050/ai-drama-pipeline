"""P2 修改审查测试 — 验证 context marker 剥离 / UID 对齐 / 翻译回写 逻辑正确性"""
import re
import pytest

# 从生产代码导入被测函数，避免测试重实现导致逻辑漂移
from pipeline.tasks.prepare import _strip_context_markers, _extract_field_marker
from engines.prompt.translate import _parse_tagged_lines


# ══════════════════════════════════════════════════════════
# 1. _strip_context_markers 单次正则测试
# ══════════════════════════════════════════════════════════

def test_strip_single_marker():
    assert _strip_context_markers("[CHAR:钢铁侠|FIELD:voice_description]\nLow magnetic voice") == "Low magnetic voice"
    assert _strip_context_markers("[SCENE:实验室|FIELD:description] A modern lab") == "A modern lab"
    assert _strip_context_markers("[SHOT:001|FIELD:action] Walking") == "Walking"
    assert _strip_context_markers("[OUTFIT:default] Red armor") == "Red armor"


def test_strip_no_marker():
    assert _strip_context_markers("Plain English text") == "Plain English text"
    assert _strip_context_markers("") == ""


def test_strip_marker_only():
    """空内容的 marker 行（LLM 可能出现）"""
    result = _strip_context_markers("[CHAR:钢铁侠|FIELD:relationships]")
    assert result == ""


# ══════════════════════════════════════════════════════════
# 2. _extract_field_marker 测试（先剥离 context marker 再找 FIELD）
# ══════════════════════════════════════════════════════════

def test_extract_field_with_context_prefix():
    """带 context marker 前缀的 FIELD 标记"""
    field, text = _extract_field_marker(
        "[CHAR:钢铁侠|FIELD:core_traits]\n[FIELD: core_traits]\nArrogant tech magnate"
    )
    assert field == "core_traits"
    assert "Arrogant tech magnate" in text


def test_extract_field_no_context():
    """纯 FIELD 标记无 context 前缀"""
    field, text = _extract_field_marker("[FIELD: voice_description]\nLow voice")
    assert field == "voice_description"
    assert "Low voice" in text


def test_extract_no_field_marker():
    """无 FIELD 标记，返回剥离后的纯文本"""
    field, text = _extract_field_marker("[CHAR:钢铁侠|FIELD:core_traits]\n傲慢的科技巨头")
    assert field is None
    assert "core_traits" not in text  # context marker 已剥离
    assert "傲慢的科技巨头" in text


def test_extract_empty():
    assert _extract_field_marker("") == (None, "")
    assert _extract_field_marker("  ") == (None, "  ".strip())


# ══════════════════════════════════════════════════════════
# 3. _parse_tagged_lines UID 格式测试（t{6位hex}）
# ══════════════════════════════════════════════════════════

def test_parse_tagged_lines_basic():
    raw = "[t000000] Walking down the street\n[t000001] The lab hums\n[t000002] Third line"
    parsed = _parse_tagged_lines(raw)
    assert len(parsed) == 3
    assert parsed["t000000"] == "Walking down the street"
    assert parsed["t000001"] == "The lab hums"
    assert parsed["t000002"] == "Third line"


def test_parse_tagged_lines_empty_translation():
    """空翻译行（.匹配0次）"""
    raw = "[t000000] translated\n[t000001] "
    parsed = _parse_tagged_lines(raw)
    assert len(parsed) == 2
    assert parsed["t000000"] == "translated"
    assert parsed["t000001"] == ""  # 空翻译


def test_parse_tagged_lines_extra_noise():
    """LLM 可能添加额外文字"""
    raw = "Here are translations:\n[t000000] Walking down the street\nDone."
    parsed = _parse_tagged_lines(raw)
    assert len(parsed) == 1
    assert parsed["t000000"] == "Walking down the street"


def test_parse_tagged_lines_uid_case():
    """UID 统一为小写"""
    raw = "[t00000a] Some text\n[t00000f] Another"
    parsed = _parse_tagged_lines(raw)
    assert parsed["t00000a"] == "Some text"
    assert parsed["t00000f"] == "Another"


def test_parse_tagged_lines_wrong_format():
    """非 t-uid 格式不应匹配"""
    raw = "[1] First\n[t000000] Real one\n[old_style] Old"
    parsed = _parse_tagged_lines(raw)
    assert len(parsed) == 1
    assert "t000000" in parsed


# ══════════════════════════════════════════════════════════
# 4. _deserialize_numbered 测试（含上下文标记混入的边界）
# 注意：_deserialize_numbered 在生产代码中无对应实现，保留为本地测试辅助函数
# ══════════════════════════════════════════════════════════

def _deserialize_numbered(raw: str, keys=None, originals=None):
    """编号列表反序列化（测试专用辅助函数，无生产代码对应）"""
    lines = []
    for line in raw.strip().splitlines():
        cleaned = re.sub(r'^\[FIELD:\s*\w+\]\s*', '', line.strip())
        m = re.match(r"^(\d+)\s*[.):：\-）]\s*(.+)", cleaned)
        if m:
            lines.append(m.group(2).strip())
    if keys is not None:
        result = {}
        for i, k in enumerate(keys):
            if i < len(lines):
                text = lines[i]
                if ": " in text:
                    _, _, parsed_val = text.partition(": ")
                    translated = parsed_val.strip()
                else:
                    translated = text
            else:
                translated = ""
            orig_val = (originals or {}).get(k, "")
            result[k] = translated or orig_val
        return result
    return [l.strip() for l in lines]


def test_deserialize_with_field_prefix():
    """首行带 [FIELD: xxx] 前缀"""
    raw = "[FIELD: relationships]\n1. 叮当猫: viewed as threat\n2. 大雄: ally"
    result = _deserialize_numbered(raw, keys=["叮当猫", "大雄"])
    assert result["叮当猫"] == "viewed as threat"
    assert result["大雄"] == "ally"


def test_deserialize_no_field_prefix():
    raw = "1. first value\n2. second value"
    result = _deserialize_numbered(raw)
    assert result == ["first value", "second value"]


def test_deserialize_with_keys_fewer_lines():
    raw = "1. only one"
    result = _deserialize_numbered(raw, keys=["k1", "k2"])
    assert result["k1"] == "only one"
    assert result["k2"] == ""


def test_deserialize_preserves_original_on_missing():
    raw = "1. only one"
    result = _deserialize_numbered(raw, keys=["k1", "k2"], originals={"k1": "原值1", "k2": "原值2"})
    assert result["k1"] == "only one"
    assert result["k2"] == "原值2"
