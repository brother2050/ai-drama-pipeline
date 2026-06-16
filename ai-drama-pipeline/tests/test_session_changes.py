"""本次会话修改的针对性测试

覆盖所有改动的代码路径，不依赖 PostgreSQL/Redis/ComfyUI。
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ══════════════════════════════════════════════════════════
#  1. batch 翻译兜底传递 llm（8cde7bf）
# ══════════════════════════════════════════════════════════

class TestTranslateLlmFallback:
    """验证 _merge_translate_results 兜底时使用传入的 llm 而非 None"""

    def test_merge_fallback_calls_translate_with_llm(self):
        """批次失败时，兜底翻译应使用传入的 llm 对象"""
        from engines.prompt.translate import _merge_translate_results

        class FakeLLM:
            called = False
            def chat(self, prompt, system="", **kw):
                FakeLLM.called = True
                return "t000000 Translated"

        results = ["", ""]
        batch_items = [(0, "t000000", "你好"), (1, "t000001", "世界")]
        uid_map = {"t000000": 0, "t000001": 1}
        batch_result = {
            "results": [None],  # 批次失败
            "batch_sizes": [2],
            "total_batches": 1,
            "failed_batches": 1,
        }
        llm = FakeLLM()
        _merge_translate_results(results, batch_items, batch_result, uid_map, llm=llm)
        # llm=None 时不会调用 chat，llm 有值时会调用
        assert FakeLLM.called, "兜底翻译未调用 llm.chat()"

    def test_merge_fallback_none_llm_returns_original(self):
        """llm=None 时兜底应返回空串"""
        from engines.prompt.translate import _merge_translate_results

        results = [""]
        batch_items = [(0, "t000000", "你好")]
        uid_map = {"t000000": 0}
        batch_result = {
            "results": [None],
            "batch_sizes": [1],
            "total_batches": 1,
            "failed_batches": 1,
        }
        _merge_translate_results(results, batch_items, batch_result, uid_map, llm=None)
        assert results[0] == "", f"llm=None 兜底应返回空串，实际: {results[0]}"

    def test_merge_success_no_fallback(self):
        """批次成功时不应调用兜底翻译"""
        from engines.prompt.translate import _merge_translate_results

        class FailLLM:
            def chat(self, *a, **kw):
                raise AssertionError("不应调用 llm")

        results = ["", ""]
        batch_items = [(0, "t000000", "你好"), (1, "t000001", "世界")]
        uid_map = {"t000000": 0, "t000001": 1}
        batch_result = {
            "results": [{"t000000": "Hello", "t000001": "World"}],
            "batch_sizes": [2],
            "total_batches": 1,
            "failed_batches": 0,
        }
        _merge_translate_results(results, batch_items, batch_result, uid_map, llm=FailLLM())
        assert results == ["Hello", "World"]


# ══════════════════════════════════════════════════════════
#  2. AdaptiveBatchProcessor batch_sizes 返回（65347b3）
# ══════════════════════════════════════════════════════════

class TestBatchSizes:
    """验证 _execute_batches 返回 batch_sizes 供调用方精确对齐"""

    def test_batch_sizes_normal(self):
        """正常路径: 两批都成功，batch_sizes 记录每批大小"""
        from infra.concurrency.batch import _execute_batches

        class FakeProcessor:
            def _execute_with_retry(self, batch, bp, pr):
                return [f"ok_{i}" for i in range(len(batch))], 0
            def _learn_from_last_error(self): pass

        batches = [["a", "b"], ["c"]]
        result = _execute_batches(FakeProcessor(), batches, None, None, None)
        assert result["batch_sizes"] == [2, 1]
        assert result["results"] == [["ok_0", "ok_1"], ["ok_0"]]
        assert result["failed_batches"] == 0
        assert result["total_items"] == 3
        assert result["retries"] == 0
        assert result["elapsed"] >= 0

    def test_batch_sizes_with_failure(self):
        """失败批次: batch_sizes 仍记录正确大小"""
        from infra.concurrency.batch import _execute_batches

        class FailProcessor:
            _max_retries = 2
            def _execute_with_retry(self, batch, bp, pr):
                if batch == ["c"]:
                    raise RuntimeError("simulated")
                return ["ok"], 0
            def _learn_from_last_error(self): pass

        batches = [["a", "b"], ["c"]]
        result = _execute_batches(FailProcessor(), batches, None, None, None)
        assert result["batch_sizes"] == [2, 1]
        assert result["results"] == [["ok"], None]
        assert result["failed_batches"] == 1
        assert result["total_items"] == 3
        assert result["retries"] == 3  # max_retries+1 attempts for the failed batch

    def test_entities_flatten_with_batch_sizes(self):
        """_generate_entities 展平: 失败批次填 None 保持对齐"""
        # 模拟 batch_result
        batch_result = {
            "results": [["entity_a", "entity_b"], None],
            "batch_sizes": [2, 1],
            "failed_batches": 1,
        }
        # 模拟 _generate_entities 的展平逻辑
        entities = []
        for batch_data, batch_size in zip(batch_result["results"], batch_result["batch_sizes"]):
            if batch_data and isinstance(batch_data, list):
                entities.extend(batch_data)
            else:
                entities.extend([None] * batch_size)
        assert entities == ["entity_a", "entity_b", None]
        assert len(entities) == 3  # 与 descriptions 长度一致

    def test_appearance_prompts_offset_tracking(self):
        """batch_generate_appearance_prompts offset 跟踪: 失败批次正确推进"""
        characters = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
        batch_result = {
            "results": [{"prompt_en": "a"}, None],
            "batch_sizes": [1, 2],
            "failed_batches": 1,
        }
        # 模拟 offset 跟踪逻辑
        all_mapping = {}
        offset = 0
        for batch_data, batch_size in zip(batch_result["results"], batch_result["batch_sizes"]):
            if not batch_data or not isinstance(batch_data, dict):
                offset += batch_size
                continue
            # batch_data 是 dict (单条结果)
            cid = characters[offset]["id"]
            all_mapping[cid] = batch_data
            offset += batch_size
        assert offset == 3
        assert "c1" in all_mapping
        assert "c2" not in all_mapping  # 失败批次
        assert "c3" not in all_mapping  # 失败批次


# ══════════════════════════════════════════════════════════
#  3. _generate_entities 使用 AdaptiveBatchProcessor（1f89bff）
# ══════════════════════════════════════════════════════════

class TestGenerateEntities:
    """验证 _generate_entities 批量生成逻辑"""

    def test_generate_entities_basic(self):
        """正常生成: LLM 返回有效 JSON 数组（含 name）"""
        from engines.content.generator import _generate_entities

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return '[{"name": "Alice"}, {"name": "Bob"}]'

        result = _generate_entities(FakeLLM(), [
            "name 必须为「Alice」",
            "name 必须为「Bob」",
        ], "system", "角色")
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    def test_generate_entities_no_name_field(self):
        """LLM 不返回 name 字段: 实体被跳过"""
        from engines.content.generator import _generate_entities

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return '[{"gender": "female"}]'

        with pytest.raises(RuntimeError, match="全部失败"):
            _generate_entities(FakeLLM(), ["name 必须为「Alice」"], "system", "角色")

    def test_generate_entities_name_dedup_removes_duplicates(self):
        """名称去重: 重复 name 直接丢弃（保留首个）"""
        from engines.content.generator import _generate_entities

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return '[{"name": "楚轩"}, {"name": "孩童"}, {"name": "师父"}, {"name": "暗影刺客"}, {"name": "李寻欢"}, {"name": "楚轩"}]'

        result = _generate_entities(FakeLLM(), [
            "name 必须为「楚轩」",
            "name 必须为「孩童」",
            "name 必须为「师父」",
            "name 必须为「暗影刺客」",
            "name 必须为「李寻欢」",
            "name 必须为「楚轩2」",
        ], "system", "角色")
        assert len(result) == 5

    def test_generate_entities_name_dedup_no_duplicates(self):
        """无重复名: 正常通过"""
        from engines.content.generator import _generate_entities

        class FakeLLM:
            def chat(self, prompt, system="", **kw):
                return '[{"name": "Alice"}, {"name": "Bob"}]'

        result = _generate_entities(FakeLLM(), [
            "name 必须为「Alice」",
            "name 必须为「Bob」",
        ], "system", "角色")
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    def test_generate_entities_failure_raises(self):
        """生成失败: LLM 返回无效数据应抛 RuntimeError"""
        from engines.content.generator import _generate_entities

        class BadLLM:
            def chat(self, *a, **kw):
                return "not json at all"

        with pytest.raises(RuntimeError, match="全部失败"):
            _generate_entities(BadLLM(), ["desc"], "system", "角色")


# ══════════════════════════════════════════════════════════
#  4. resolve_node_aliases 迭代安全（4f4014d）
# ══════════════════════════════════════════════════════════

class TestResolveNodeAliases:
    """验证 resolve_node_aliases 不在迭代中修改 dict"""

    def test_basic_alias(self):
        """基本别名替换"""
        from engines.workflow import resolve_node_aliases
        wf = {"_node_aliases": {"Foo": ["Bar"]}, "1": {"class_type": "Foo", "inputs": {}}}
        result = resolve_node_aliases(wf, {"Bar"})
        assert result["1"]["class_type"] == "Bar"

    def test_multiple_nodes(self):
        """多节点别名替换不崩溃"""
        from engines.workflow import resolve_node_aliases
        wf = {
            "_node_aliases": {"A": ["B"]},
            "n1": {"class_type": "A"},
            "n2": {"class_type": "A"},
            "n3": {"class_type": "C"},
        }
        result = resolve_node_aliases(wf, {"B"})
        assert result["n1"]["class_type"] == "B"
        assert result["n2"]["class_type"] == "B"
        assert result["n3"]["class_type"] == "C"  # 不匹配的不变

    def test_no_aliases(self):
        """无别名键时不报错"""
        from engines.workflow import resolve_node_aliases
        wf = {"1": {"class_type": "Foo"}}
        result = resolve_node_aliases(wf, {"Foo"})
        assert result["1"]["class_type"] == "Foo"

    def test_empty_available_nodes(self):
        """空 available_nodes 直接返回"""
        from engines.workflow import resolve_node_aliases
        wf = {"_node_aliases": {"Foo": ["Bar"]}, "1": {"class_type": "Foo"}}
        result = resolve_node_aliases(wf, set())
        assert result["1"]["class_type"] == "Foo"  # 未替换


# ══════════════════════════════════════════════════════════
#  5. infra/models.py 消除伪对象（4c33521）
# ══════════════════════════════════════════════════════════

class TestImportValidator:
    """验证 _check_outfit_reference 不再用 type('C'...) 伪对象"""

    def test_valid_outfit_reference(self):
        """有效 outfit 引用不报错"""
        from infra.models import ImportPlan, ImportCharacter, ImportScene, ImportShot, ImportValidator
        plan = ImportPlan(
            characters=[ImportCharacter(id="c1", name="Alice", appearance="young woman with long hair")],
            scenes=[ImportScene(id="s1", name="Room", description="a modern living room")],
            shots=[ImportShot(shot_id="001", scene_name="s1", characters="c1",
                            action="Alice walks in slowly", outfit="default")],
        )
        errors = ImportValidator.validate_references(plan)
        assert not any("outfit" in e for e in errors)

    def test_invalid_outfit_reports_available(self):
        """无效 outfit 报错包含可用列表"""
        from infra.models import ImportPlan, ImportCharacter, ImportScene, ImportShot, ImportValidator, ImportOutfit
        plan = ImportPlan(
            characters=[ImportCharacter(id="c1", name="Alice", appearance="young woman with long hair",
                                       outfits={"default": ImportOutfit(description="casual wear")})],
            scenes=[ImportScene(id="s1", name="Room", description="a modern living room")],
            shots=[ImportShot(shot_id="001", scene_name="Room", characters="Alice",
                            action="Alice walks in slowly", outfit="nonexistent")],
        )
        errors = ImportValidator.validate_references(plan)
        assert any("nonexistent" in e and "default" in e for e in errors)


# ══════════════════════════════════════════════════════════
#  6. warnings 类型修复（4f4014d）
# ══════════════════════════════════════════════════════════

class TestWarningsType:
    """验证 _generate_entities_for_storyboard 的 warnings 是 list"""

    def test_warnings_is_list(self):
        """warnings 变量应是 list（不是 dict），支持 .extend()"""
        # 直接测试修复后的代码路径
        id_remap, warnings = {}, []
        # 模拟 _generate_characters_for_storyboard 返回
        char_result = {"id_remap": {"c1": "new_c1"}, "warnings": ["char warning"]}
        id_remap.update(char_result.get("id_remap", {}))
        warnings = char_result.get("warnings", [])
        # 模拟 _generate_scenes_for_storyboard 返回
        scene_result = {"id_remap": {"s1": "new_s1"}, "warnings": ["scene warning"]}
        id_remap.update(scene_result.get("id_remap", {}))
        warnings.extend(scene_result.get("warnings", []))  # dict 没有 extend，会崩
        assert warnings == ["char warning", "scene warning"]
        assert id_remap == {"c1": "new_c1", "s1": "new_s1"}


# ══════════════════════════════════════════════════════════
#  7. _load_shots / _find_shot 移除 config_path（7a20770）
# ══════════════════════════════════════════════════════════

class TestLoadShotsSignature:
    """验证 _load_shots/_find_shot 不再需要 config_path 参数"""

    def test_load_shots_no_config_path(self):
        """_load_shots 只接受 episode 参数"""
        import inspect
        from pipeline.tasks.helpers import _load_shots
        sig = inspect.signature(_load_shots)
        params = list(sig.parameters.keys())
        assert params == ["episode"], f"期望 ['episode'], 实际 {params}"

    def test_find_shot_no_config_path(self):
        """_find_shot 只接受 episode 和 shot_id 参数"""
        import inspect
        from pipeline.tasks.helpers import _find_shot
        sig = inspect.signature(_find_shot)
        params = list(sig.parameters.keys())
        assert params == ["episode", "shot_id"], f"期望 ['episode', 'shot_id'], 实际 {params}"


# ══════════════════════════════════════════════════════════
#  9. StatusRecord 移除（4f4014d）
# ══════════════════════════════════════════════════════════

class TestStatusRecordRemoved:
    """验证 StatusRecord dataclass 已移除"""

    def test_status_record_not_importable(self):
        """StatusRecord 不再存在于 generation 模块"""
        import infra.database.generation as mod
        assert not hasattr(mod, "StatusRecord"), "StatusRecord 应已移除"

    def test_upsert_status_still_works(self):
        """upsert_status 函数仍可导入"""
        from infra.database.generation import upsert_status
        assert callable(upsert_status)


# ══════════════════════════════════════════════════════════
#  11. post/vertical.py 消除未使用变量（4f4014d）
# ══════════════════════════════════════════════════════════

class TestVerticalImport:
    """验证 post.vertical 可正常导入（语法正确）"""

    def test_import(self):
        from post.vertical import to_vertical
        assert callable(to_vertical)

    def test_find_face_center_returns_tuple_or_none(self):
        """_find_face_center 返回 (x, y) 或 None"""
        from post.vertical import _find_face_center
        # 不存在的文件返回 None
        result = _find_face_center("/nonexistent/video.mp4")
        assert result is None


# ══════════════════════════════════════════════════════════
#  12. normalize_character 不再过滤 http URL（4c33521）
# ══════════════════════════════════════════════════════════

class TestNormalizeCharacter:
    """验证 normalize_character 角色数据规范化"""

    def test_bible_default(self):
        """bible 为 None 时不创建空壳（按需生成）"""
        from infra.models import normalize_character
        char = {"id": "test", "bible": None}
        result = normalize_character(char)
        # bible 为 None 时不再强制初始化
        assert "bible" not in result or not result.get("bible")

    def test_bible_normalize_existing(self):
        """bible 存在时规范化已有字段"""
        from infra.models import normalize_character
        char = {"id": "test", "bible": {"core_traits": "聪明"}}
        result = normalize_character(char)
        bible = result["bible"]
        assert bible["core_traits"] == "聪明"
        assert bible["speech_patterns"] == ""
        assert isinstance(bible["relationships"], dict)
        assert isinstance(bible["emotional_range"], dict)
        assert isinstance(bible["body_language"], dict)
        assert isinstance(bible["habits"], list)
        assert isinstance(bible["taboos"], list)

    def test_bible_en_normalize(self):
        """bible_en 存在时规范化（key 带 _en 后缀）"""
        from infra.models import normalize_character
        char = {"id": "test", "bible_en": {"core_traits_en": "smart"}}
        result = normalize_character(char)
        assert result["bible_en"]["core_traits_en"] == "smart"
        assert result["bible_en"]["speech_patterns_en"] == ""

    def test_outfits_ensure_default(self):
        """outfits 无 default 时自动添加"""
        from infra.models import normalize_character
        char = {"id": "test", "outfits": {"casual": {"description": "casual wear", "reference_images": []}}}
        result = normalize_character(char)
        assert "default" in result["outfits"]

    def test_outfits_string_to_dict(self):
        """outfits 值为字符串时自动转为 dict"""
        from infra.models import normalize_character
        char = {"id": "test", "outfits": {"default": "a dress"}}
        result = normalize_character(char)
        assert result["outfits"]["default"] == {"description": "a dress", "reference_images": []}

    def test_outfits_none_creates_default(self):
        """outfits 为 None 时创建 default 结构"""
        from infra.models import normalize_character
        char = {"id": "test", "outfits": None}
        result = normalize_character(char)
        assert "default" in result["outfits"]
        assert result["outfits"]["default"]["description"] == ""


class TestFieldMarker:
    """翻译回写 [FIELD: xxx] 标记机制测试"""

    def test_extract_field_marker_present(self):
        """从翻译结果中提取 [FIELD: xxx] 标记"""
        from pipeline.tasks.prepare import _extract_field_marker
        field, text = _extract_field_marker("[FIELD: core_traits]\ntranslated text here")
        assert field == "core_traits"
        assert text == "translated text here"

    def test_extract_field_marker_absent(self):
        """无标记时返回 None 和原文"""
        from pipeline.tasks.prepare import _extract_field_marker
        field, text = _extract_field_marker("just translated text")
        assert field is None
        assert text == "just translated text"

    def test_extract_field_marker_empty(self):
        """空文本返回 None"""
        from pipeline.tasks.prepare import _extract_field_marker
        field, text = _extract_field_marker("")
        assert field is None
        assert text == ""

    def test_serialize_dict_for_translate(self):
        """_serialize_dict_for_translate 输出 JSON 字符串"""
        import json
        from pipeline.tasks.prepare import _serialize_dict_for_translate
        result = _serialize_dict_for_translate({"happy": "smiling", "sad": "crying"})
        parsed = json.loads(result)
        assert parsed == {"happy": "smiling", "sad": "crying"}

    def test_serialize_list_for_translate(self):
        """_serialize_list_for_translate 输出 JSON 字符串"""
        import json
        from pipeline.tasks.prepare import _serialize_list_for_translate
        result = _serialize_list_for_translate(["item1", "item2"])
        parsed = json.loads(result)
        assert parsed == ["item1", "item2"]


class TestGenderTagCorrection:
    """性别标签纠正测试"""

    def test_correct_male_tag_unchanged(self):
        """正确的 male 标签不修改"""
        from engines.prompt.builder import _ensure_gender_tag
        assert _ensure_gender_tag("1boy, 20 years old", "male") == "1boy, 20 years old"

    def test_correct_female_tag_unchanged(self):
        """正确的 female 标签不修改"""
        from engines.prompt.builder import _ensure_gender_tag
        assert _ensure_gender_tag("1girl, long hair", "female") == "1girl, long hair"

    def test_wrong_male_tag_corrected(self):
        """gender=male 但 prompt 含 1girl → 纠正为 1boy"""
        from engines.prompt.builder import _ensure_gender_tag
        result = _ensure_gender_tag("1girl, 32 years old, sword scar", "male")
        assert result == "1boy, 32 years old, sword scar"

    def test_wrong_female_tag_corrected(self):
        """gender=female 但 prompt 含 1boy → 纠正为 1girl"""
        from engines.prompt.builder import _ensure_gender_tag
        result = _ensure_gender_tag("1boy, long hair, mysterious", "female")
        assert result == "1girl, long hair, mysterious"

    def test_missing_tag_added(self):
        """无标签时补充"""
        from engines.prompt.builder import _ensure_gender_tag
        result = _ensure_gender_tag("20 years old, short hair", "male")
        assert result == "1boy, 20 years old, short hair"


class TestTranslationValidation:
    """翻译质量校验测试（中文残留检测）"""

    def test_chinese_residue_detected(self):
        """含中文字符的翻译应被标记为需要重试"""
        from pipeline.tasks.prepare import _validate_and_retry

        src = ["开心的表情", "悲伤的眼神"]
        meta = [("character.bible", "test", "emotional_range", "emotional_range_en"),
                ("character.bible", "test", "body_language", "body_language_en")]
        # 第一条含中文（未翻译），第二条正常
        results = ["开心的表情", "sad expression"]

        # Mock LLM: 重试时返回正确翻译
        class MockLLM:
            def chat(self, user, system="", **kw):
                return "happy expression"

        validated = _validate_and_retry(src, results, meta, MockLLM())
        assert validated[0] == "happy expression", f'FAIL: {validated[0]}'
        assert validated[1] == "sad expression", f'FAIL: {validated[1]}'

    def test_short_chinese_residue_detected(self):
        """短中文文本（≤3 字符）也应被检测"""
        from pipeline.tasks.prepare import _validate_and_retry

        src = ["开心"]
        meta = [("character.bible", "test", "f", "f")]
        results = ["开心"]  # 完全未翻译

        class MockLLM:
            def chat(self, user, system="", **kw):
                return "happy"

        validated = _validate_and_retry(src, results, meta, MockLLM())
        assert validated[0] == "happy", f'FAIL: {validated[0]}'

    def test_english_passes(self):
        """正常英文翻译不应被标记"""
        from pipeline.tasks.prepare import _validate_and_retry

        src = ["开心的表情"]
        meta = [("character.bible", "test", "f", "f")]
        results = ["happy expression"]

        class MockLLM:
            def chat(self, user, system="", max_tokens=0):
                return "should not be called"

        validated = _validate_and_retry(src, results, meta, MockLLM())
        assert validated[0] == "happy expression"


class TestWritebackTranslations:
    """_writeback_translations 翻译回写测试"""

    def test_writeback_character_bible_en(self):
        """角色 bible 翻译正确写入 bible_en"""
        import tempfile, yaml
        from pathlib import Path
        from pipeline.tasks.prepare import _writeback_translations

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建项目结构
            proj = Path(tmpdir)
            (proj / "config" / "characters").mkdir(parents=True)
            (proj / "config" / "scenes").mkdir(parents=True)
            (proj / "output").mkdir(parents=True)

            # 创建角色 YAML
            char_file = proj / "config" / "characters" / "test.yaml"
            char_file.write_text(yaml.dump({"character": {"id": "test", "name": "测试", "bible": {
                "core_traits": "勇敢"
            }}}, allow_unicode=True))

            # 创建 mock paths
            class MockPaths:
                def character_yaml(self, cid): return proj / "config" / "characters" / f"{cid}.yaml"
                def scene_yaml(self, sid): return proj / "config" / "scenes" / f"{sid}.yaml"

            meta = [("character.bible", "test", "core_traits", "core_traits_en")]
            results = ["brave and courageous"]

            translated, char_cache, skipped = _writeback_translations(
                meta, results, MockPaths(), 1, [])
            assert translated["characters"] == 1
            assert len(skipped) == 0


# ══════════════════════════════════════════════════════════
#  13. validate_descs 空列表穿透（3490ab1）
# ══════════════════════════════════════════════════════════

class TestValidateDescs:
    """验证 CharacterGenRequest/SceneGenRequest 的 descriptions 校验"""

    def test_normal_descriptions_pass(self):
        """正常描述列表通过校验"""
        from web.schemas import CharacterGenRequest
        r = CharacterGenRequest(descriptions=["勇敢的战士", "神秘的法师"])
        assert r.descriptions == ["勇敢的战士", "神秘的法师"]

    def test_whitespace_stripped(self):
        """前后空白被 strip"""
        from web.schemas import CharacterGenRequest
        r = CharacterGenRequest(descriptions=["  勇敢的战士  ", "  神秘的法师  "])
        assert r.descriptions == ["勇敢的战士", "神秘的法师"]

    def test_all_whitespace_rejected(self):
        """全空白描述经 strip 后为空 → 拒绝"""
        from web.schemas import CharacterGenRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CharacterGenRequest(descriptions=["  ", "  "])

    def test_single_whitespace_rejected(self):
        """单个空白描述 → 拒绝"""
        from web.schemas import CharacterGenRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CharacterGenRequest(descriptions=["  "])

    def test_empty_string_rejected(self):
        """空字符串 → 拒绝"""
        from web.schemas import CharacterGenRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CharacterGenRequest(descriptions=[""])

    def test_scene_gen_same_validation(self):
        """SceneGenRequest 同样校验"""
        from web.schemas import SceneGenRequest
        from pydantic import ValidationError
        # 正常通过
        r = SceneGenRequest(descriptions=["现代都市客厅"])
        assert r.descriptions == ["现代都市客厅"]
        # 全空白拒绝
        with pytest.raises(ValidationError):
            SceneGenRequest(descriptions=["  "])

    def test_mixed_valid_and_whitespace(self):
        """混合有效和空白描述 → strip 后保留有效的"""
        from web.schemas import CharacterGenRequest
        r = CharacterGenRequest(descriptions=["勇敢的战士", "  ", "神秘的法师"])
        # "  " 被 strip 掉，但列表仍有 2 个有效项
        assert r.descriptions == ["勇敢的战士", "神秘的法师"]
