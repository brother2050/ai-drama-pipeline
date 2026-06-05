"""Celery 任务定义 — AI 生成（分镜/角色/场景/准备/对话编辑）"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import json
import logging

from pipeline.celery_app import app
from pipeline.tasks.helpers import _init_ctx, _project_scope_from_config
from infra.json_parse import parse_llm_json
from engines.llm_generator import StoryboardGenParams

logger = logging.getLogger(__name__)
@app.task(bind=True, name="pipeline_ai_storyboard", soft_time_limit=600)
def ai_storyboard_task(self, config_path: str, episode: int, outline: str,
                       duration: int = 90, append: bool = False):
    """AI 生成分镜表 + 自动补全角色/场景（面向新用户）"""
    with _project_scope_from_config(config_path):
        return _ai_storyboard_inner(self, config_path, episode, outline, duration, append)


def _ai_storyboard_inner(self, config_path, episode, outline, duration, append):
    """ai_storyboard 核心逻辑（在 project_scope 内执行）"""
    from engines.storyboard import save_storyboard, append_storyboard

    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 10, "message": "正在初始化 LLM..."})
    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    style, genre = cfg.get("project", {}).get("style", ""), cfg.get("project", {}).get("genre", "")

    # 1. 生成分镜
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 30, "message": "AI 正在生成分镜..."})
    shots = _generate_shots(llm, outline, episode, duration, style, genre)
    if isinstance(shots, dict):
        return shots  # error dict

    # 2. 生成引用的角色/场景
    char_ids, scene_ids = _extract_entity_ids(shots)
    if char_ids or scene_ids:
        self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 60,
                          "message": f"正在生成 {len(char_ids)} 个角色、{len(scene_ids)} 个场景..."})
    id_remap, warnings, err = _generate_entities_for_storyboard(llm, shots, char_ids, scene_ids, outline, style, genre, cfg.paths)
    if err:
        return {"status": STATUS_ERROR, "reason": err}

    # 3. 回写 + 保存
    if id_remap:
        from engines.entity_utils import remap_shot_ids
        remap_shot_ids(shots, id_remap)
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 90, "message": "正在保存..."})
    (append_storyboard if append else save_storyboard)(shots, episode)

    result = {"status": STATUS_DONE, "episode": episode, "count": len(shots),
              "total_duration": sum(int(s.get("duration", 4)) for s in shots), "shots": shots,
              "generated_characters": list(id_remap.keys())[:len(char_ids)],
              "generated_scenes": list(id_remap.keys())[len(char_ids):]}
    if warnings:
        result["warnings"] = warnings
    return result


def _generate_shots(llm, outline, episode, duration, style, genre):
    """生成分镜，成功返回 list[dict]，失败返回 error dict"""
    from engines.llm_generator import generate_storyboard
    try:
        shots = generate_storyboard(llm, StoryboardGenParams(
            outline=outline, characters=[], scenes=[],
            episode=episode, target_duration=duration, style=style, genre=genre))
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 生成失败: {e}"}
    if not shots:
        return {"status": STATUS_ERROR, "reason": "LLM 未能生成有效分镜"}
    return shots


def _generate_entities_for_storyboard(llm, shots, char_ids, scene_ids, outline, style, genre, paths):
    """生成角色+场景，返回 (id_remap, warnings, error_or_None)"""
    id_remap, warnings = {}, []
    if char_ids:
        result = _generate_entities_for_storyboard_core(
            llm, shots, char_ids, outline, style, genre, paths, "character", "ch")
        if result.get("error"):
            return {}, [], result["error"]
        id_remap.update(result.get("id_remap", {}))
        warnings = result.get("warnings", [])
    if scene_ids:
        result = _generate_entities_for_storyboard_core(
            llm, shots, scene_ids, outline, style, genre, paths, "scene", "sc")
        if result.get("error"):
            return {}, [], result["error"]
        id_remap.update(result.get("id_remap", {}))
        warnings.extend(result.get("warnings", []))
    return id_remap, warnings, None


def _generate_entities_for_storyboard_core(llm, shots, entity_ids, outline, style, genre, paths, entity_key, prefix) -> dict:
    """为分镜生成角色/场景配置（统一入口）

    从分镜数据构建描述 → 调用 LLM 生成 → 保存到 YAML。
    """
    from engines.entity_utils import generate_and_save, build_entity_descriptions

    sorted_ids = sorted(entity_ids)
    descriptions = build_entity_descriptions(shots, sorted_ids, outline, style, genre, entity_key)
    out_dir = paths.characters_dir if entity_key == "character" else paths.scenes_dir

    result = generate_and_save(
        llm, descriptions, entity_key, out_dir, prefix, expected_ids=sorted_ids)

    if result.get("status") == "error":
        return {"error": result["reason"]}
    return {"id_remap": result.get("id_remap", {}), "warnings": result.get("warnings", []),
            "generated": result.get("entities", [])}


def _extract_entity_ids(shots: list[dict]) -> tuple[set[str], set[str]]:
    """从分镜中提取所有引用的角色/场景 ID"""
    from engines.shot_utils import parse_char_ids
    char_ids, scene_ids = set(), set()
    for shot in shots:
        char_ids.update(parse_char_ids(shot))
        sid = (shot.get("scene_id") or "").strip()
        if sid:
            scene_ids.add(sid)
    return char_ids, scene_ids


@app.task(bind=True, name="pipeline_ai_characters", soft_time_limit=300)
def ai_characters_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成角色（异步）"""
    with _project_scope_from_config(config_path):
        from engines.entity_utils import generate_and_save

        self.update_state(state="PROGRESS", meta={"step": "ai_characters", "progress": 20, "message": "AI 正在生成角色..."})
        cfg, cont = _init_ctx(config_path)
        try:
            llm = cont.get("llm")
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

        result = generate_and_save(
            llm, descriptions, "character", cfg.paths.characters_dir, "ch")
        if result.get("status") == "error":
            return {"status": STATUS_ERROR, "reason": result["reason"]}
        return {"status": STATUS_DONE, "count": result["count"], "characters": result["entities"]}


@app.task(bind=True, name="pipeline_ai_scenes", soft_time_limit=300)
def ai_scenes_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成场景（异步）"""
    with _project_scope_from_config(config_path):
        from engines.entity_utils import generate_and_save

        self.update_state(state="PROGRESS", meta={"step": "ai_scenes", "progress": 20, "message": "AI 正在生成场景..."})
        cfg, cont = _init_ctx(config_path)
        try:
            llm = cont.get("llm")
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

        result = generate_and_save(
            llm, descriptions, "scene", cfg.paths.scenes_dir, "sc")
        if result.get("status") == "error":
            return {"status": STATUS_ERROR, "reason": result["reason"]}
        return {"status": STATUS_DONE, "count": result["count"], "scenes": result["entities"]}


# ══════════════════════════════════════════════════════════
#  对话式编辑 — LLM Chat Edit
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="ai_chat_edit", soft_time_limit=300)
def ai_chat_edit_task(self, config_path: str, episode: int, message: str, current_shots: list) -> dict:
    """对话式编辑分镜 — 用自然语言修改分镜表"""
    with _project_scope_from_config(config_path):
        return _ai_chat_edit_inner(self, config_path, episode, message, current_shots)


def _ai_chat_edit_inner(self, config_path, episode, message, current_shots):
    """对话式编辑核心逻辑（在 project_scope 内执行）"""
    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 10, "message": "正在初始化 LLM..."})
    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 30, "message": "AI 正在理解指令..."})
    prompt = _build_chat_edit_prompt(message, current_shots)

    try:
        response = llm.chat(prompt)
        result = parse_llm_json(response)
    except Exception as e:
        logger.error(f"chat_edit 异常: {e}", exc_info=True)
        return {"status": STATUS_ERROR, "reason": f"LLM 执行失败: {e}"}

    if result is None:
        logger.warning(f"chat_edit JSON 解析失败，原始响应: {response[:500]}")
        return {"status": STATUS_ERROR, "reason": "LLM 返回的不是有效 JSON"}
    if isinstance(result, dict) and "error" in result:
        return {"status": STATUS_ERROR, "reason": result["error"]}
    if not isinstance(result, list):
        return {"status": STATUS_ERROR, "reason": "LLM 返回格式不正确"}

    err = _validate_chat_edit_output(result)
    if err:
        return {"status": STATUS_ERROR, "reason": err}

    for shot in result:
        shot["episode"] = episode
    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 90, "message": "编辑完成"})
    resp = {"status": STATUS_DONE, "shots": result, "message": f"已修改 {len(result)} 个镜头"}
    if len(current_shots) > MAX_SHOTS_FOR_EDIT:
        resp["truncated"] = True
        resp["total_shots"] = len(current_shots)
        resp["message"] += f"（注意：分镜表共 {len(current_shots)} 个镜头，AI 只看到了前 {MAX_SHOTS_FOR_EDIT} 个）"
    return resp


MAX_SHOTS_FOR_EDIT = 50


def _build_chat_edit_prompt(message: str, current_shots: list) -> str:
    """构建对话式编辑 prompt"""
    truncation_note = ""
    shots_for_prompt = current_shots
    if len(current_shots) > MAX_SHOTS_FOR_EDIT:
        shots_for_prompt = current_shots[:MAX_SHOTS_FOR_EDIT]
        truncation_note = f"\n注意：分镜表共 {len(current_shots)} 个镜头，此处只显示前 {MAX_SHOTS_FOR_EDIT} 个。"
    shots_json = json.dumps(shots_for_prompt, ensure_ascii=False, indent=2)
    return f"""你是一个分镜表编辑助手。用户会用自然语言描述对分镜表的修改需求。
当前分镜表（JSON 格式）：
{shots_json}{truncation_note}

用户指令：{message}

请根据用户的指令修改分镜表，返回修改后的完整分镜表 JSON 数组。
只返回 JSON 数组，不要其他文字。确保所有字段都保留。
如果用户的指令不清晰或无法执行，返回一个 JSON 对象：{{"error": "原因说明"}}"""


def _validate_chat_edit_output(result: list) -> str | None:
    """校验 chat_edit 输出，返回错误信息或 None"""
    required = {"shot_id", "scene_id", "characters", "action", "dialogue"}
    invalid = []
    for i, shot in enumerate(result):
        if not isinstance(shot, dict):
            invalid.append(f"第{i+1}项不是对象")
            continue
        missing = required - set(shot.keys())
        if missing:
            invalid.append(f"shot_id={shot.get('shot_id', '?')} 缺少: {', '.join(missing)}")
    if invalid:
        logger.warning(f"chat_edit 输出校验失败: {invalid[:5]}")
        return f"LLM 返回的分镜数据不完整（{len(invalid)} 处）: {'; '.join(invalid[:3])}"
    return None


# ══════════════════════════════════════════════════════════
#  准备阶段 — 批量预翻译（角色/场景/分镜）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_ai_prepare", soft_time_limit=600)
def ai_prepare_task(self, config_path: str, episode: int,
                    force: bool = False, translate: bool = True) -> dict:
    """准备阶段 — 批量预翻译角色/场景/分镜的中→英文本

    纯翻译步骤：角色圣经生成已移至 Web 工作台「📝 分镜表」→「🤖 AI 生成角色圣经」。
    运行完毕后，生产管线可完全不依赖 LLM 全速运行。
    """
    with _project_scope_from_config(config_path):
        return _ai_prepare_inner(self, config_path, episode, force, translate)


def _serialize_dict_values(d: dict) -> str:
    """将 dict 值序列化为编号文本（翻译用）"""
    return "\n".join(f"{i+1}. {v}" for i, v in enumerate(d.values()) if v)


def _serialize_list_items(items: list) -> str:
    """将 list 项序列化为编号文本（翻译用）"""
    return "\n".join(f"{i+1}. {v}" for i, v in enumerate(items) if v)


def _deserialize_numbered(raw: str, keys: list | None = None) -> dict | list:
    """将编号文本反序列化为 dict 或 list"""
    import re
    lines = []
    for line in raw.strip().splitlines():
        m = re.match(r"^\d+\s*[.)]\s*(.+)", line.strip())
        if m:
            lines.append(m.group(1).strip())
    if keys is not None:
        return dict(zip(keys, lines[:len(keys)]))
    return lines


def _collect_bible_texts(char: dict, cid: str, all_texts: list[str],
                         text_meta: list[tuple[str, str, str, str]], force: bool = False) -> None:
    """收集角色 bible 段的待翻译文本"""
    bible = char.get("bible", {})
    if not isinstance(bible, dict):
        return

    # 简单字符串字段
    for field, en_field in [("core_traits", "core_traits_en"),
                            ("speech_patterns", "speech_patterns_en")]:
        if bible.get(field) and (force or not bible.get(en_field)):
            all_texts.append(bible[field])
            text_meta.append(("character.bible", cid, field, en_field))

    # dict 字段（值需要翻译）
    for field, en_field in [("relationships", "relationships_en"),
                            ("emotional_range", "emotional_range_en"),
                            ("body_language", "body_language_en")]:
        data = bible.get(field, {})
        if isinstance(data, dict) and data and (force or not bible.get(en_field)):
            serialized = _serialize_dict_values(data)
            if serialized:
                all_texts.append(serialized)
                text_meta.append(("character.bible_dict", cid, field, en_field))

    # list 字段
    for field, en_field in [("habits", "habits_en"), ("taboos", "taboos_en")]:
        items = bible.get(field, [])
        if isinstance(items, list) and items and (force or not bible.get(en_field)):
            serialized = _serialize_list_items(items)
            if serialized:
                all_texts.append(serialized)
                text_meta.append(("character.bible_list", cid, field, en_field))


def _collect_translation_texts(paths, force: bool = False) -> tuple[list[str], list[tuple[str, str, str, str]]]:
    """收集所有待翻译文本 → (texts, meta)"""
    from infra.config import load_yaml_full
    all_texts: list[str] = []
    text_meta: list[tuple[str, str, str, str]] = []

    # 角色
    char_dir = paths.characters_dir
    if char_dir.exists():
        for f in sorted(char_dir.glob("*.yaml")):
            if f.stem.endswith(".example"):
                continue
            try:
                data = load_yaml_full(f)
                char = data.get("character", {})
                cid = char.get("id", f.stem)
            except Exception as e:
                logger.warning(f"跳过损坏的角色配置 {f.name}: {e}")
                continue
            if char.get("appearance") and (force or not char.get("appearance_prompt_en")):
                all_texts.append(char["appearance"])
                text_meta.append(("character", cid, "appearance", "appearance_prompt_en"))
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict):
                for okey, odata in outfits.items():
                    if isinstance(odata, dict) and odata.get("description") and (force or not odata.get("description_en")):
                        all_texts.append(odata["description"])
                        text_meta.append(("character.outfits", f"{cid}.{okey}", "description", "description_en"))
            _collect_bible_texts(char, cid, all_texts, text_meta, force)

    # 场景
    scene_dir = paths.scenes_dir
    if scene_dir.exists():
        for f in sorted(scene_dir.glob("*.yaml")):
            if f.stem.endswith(".example"):
                continue
            try:
                data = load_yaml_full(f)
                scene = data.get("scene", {})
                sid = scene.get("id", f.stem)
            except Exception as e:
                logger.warning(f"跳过损坏的场景配置 {f.name}: {e}")
                continue
            if scene.get("description") and (force or not scene.get("description_en")):
                all_texts.append(scene["description"])
                text_meta.append(("scene", sid, "description", "description_en"))
            if scene.get("lighting") and (force or not scene.get("lighting_en")):
                all_texts.append(scene["lighting"])
                text_meta.append(("scene", sid, "lighting", "lighting_en"))

    return all_texts, text_meta


def _writeback_translations(text_meta, results, paths, episode, shots) -> tuple[dict, dict]:
    """回写翻译结果到 YAML + DB，返回统计"""
    from infra.config import save_yaml
    translated = {"characters": 0, "scenes": 0, "shots": 0}

    # 角色（含 outfit 子字段）
    char_cache = _load_entity_cache(text_meta, results, "character", paths.character_yaml, "character")
    for cid, data in char_cache.items():
        save_yaml(paths.character_yaml(cid), data)
        translated["characters"] += 1

    # 场景
    scene_cache = _load_entity_cache(text_meta, results, "scene", paths.scene_yaml, "scene")
    for sid, data in scene_cache.items():
        save_yaml(paths.scene_yaml(sid), data)
        translated["scenes"] += 1

    # 分镜
    shot_updates: dict[str, dict] = {}
    for i, (entity_type, entity_id, _, en_field) in enumerate(text_meta):
        if entity_type == "shot":
            shot_updates.setdefault(entity_id, {})[en_field] = results[i]
    updated_shots = sum(1 for s in shots if s.get("shot_id") in shot_updates and not s.update(shot_updates[s["shot_id"]]))
    if updated_shots:
        from engines.storyboard import save_storyboard
        save_storyboard(shots, episode)
        translated["shots"] = updated_shots

    return translated, char_cache


def _load_entity_cache(text_meta, results, entity_type, yaml_fn, entity_key) -> dict[str, dict]:
    """从 text_meta 加载实体 YAML 到缓存，处理 outfit/bible 子字段"""
    from infra.config import load_yaml_full
    cache: dict[str, dict] = {}

    def _ensure(eid: str) -> dict:
        if eid not in cache:
            fpath = yaml_fn(eid)
            cache[eid] = load_yaml_full(fpath) if fpath.exists() else {entity_key: {"id": eid}}
        return cache[eid]

    for i, (etype, eid, _, en_field) in enumerate(text_meta):
        if etype == entity_type:
            _ensure(eid).setdefault(entity_key, {})[en_field] = results[i]

        elif etype == f"{entity_type}.outfits":
            cid, okey = eid.split(".", 1)
            _ensure(cid).setdefault(entity_key, {}).setdefault("outfits", {}).setdefault(okey, {})[en_field] = results[i]

        elif etype == f"{entity_type}.bible":
            _ensure(eid).setdefault(entity_key, {}).setdefault("bible", {})[en_field] = results[i]

        elif etype == f"{entity_type}.bible_dict":
            bible = _ensure(eid).setdefault(entity_key, {}).setdefault("bible", {})
            orig = bible.get(en_field.removesuffix("_en"), {})
            orig_keys = list(orig.keys()) if isinstance(orig, dict) else None
            bible[en_field] = _deserialize_numbered(results[i], orig_keys)

        elif etype == f"{entity_type}.bible_list":
            bible = _ensure(eid).setdefault(entity_key, {}).setdefault("bible", {})
            bible[en_field] = _deserialize_numbered(results[i])

    return cache


def _generate_view_prompts(char_cache, llm, paths) -> int:
    """为已翻译的角色生成视角专属 prompt，返回成功数"""
    from engines.prompt import batch_generate_appearance_prompts
    from infra.config import save_yaml

    chars_with_appearance = [d.get("character", {}) for d in char_cache.values()
                             if d.get("character", {}).get("appearance_prompt_en")]
    if not chars_with_appearance or not llm:
        return 0
    try:
        view_mapping = batch_generate_appearance_prompts(chars_with_appearance, llm)
        for cid, prompts in view_mapping.items():
            if cid not in char_cache:
                continue
            char = char_cache[cid].setdefault("character", {})
            char["appearance_prompt_en"] = prompts.get("prompt_en", "")
            char["body_features"] = prompts.get("body_features", "")
            save_yaml(paths.character_yaml(cid), char_cache[cid])
        if view_mapping:
            logger.info(f"  ✅ 视角 prompt 生成完成: {len(view_mapping)} 个角色")
        return len(view_mapping)
    except Exception as e:
        logger.warning(f"  ⚠ 视角 prompt 生成失败: {e}")
        return 0


def _collect_shot_texts(shots: list[dict], all_texts: list[str], text_meta: list, force: bool = False) -> None:
    """补充待翻译的分镜文本（action/dialogue）"""
    for shot in shots:
        sid = shot.get("shot_id", "")
        if shot.get("action") and (force or not shot.get("action_en")):
            all_texts.append(shot["action"])
            text_meta.append(("shot", sid, "action", "action_en"))
        if shot.get("dialogue") and shot.get("dialogue") != "......" and (force or not shot.get("dialogue_en")):
            all_texts.append(shot["dialogue"])
            text_meta.append(("shot", sid, "dialogue", "dialogue_en"))


def _run_quality_gate(paths, result: dict) -> None:
    """运行质量门禁，将警告注入 result"""
    try:
        from engines.quality_gate import check_quality
        issues = check_quality("after_prepare", str(paths.root))
        if issues:
            for w in [i for i in issues if i["severity"] == "warning"]:
                logger.warning(f"⚠ 质量检查: {w['name']} — {w['message']}")
            result["quality_issues"] = issues
    except Exception as e:
        logger.debug(f"质量门禁跳过: {e}")


_BIBLE_REQUIRED_FIELDS = ("speech_patterns", "relationships", "emotional_range", "body_language")


def _bible_is_incomplete(bible: dict) -> bool:
    """检查 bible 是否缺少关键字段（只有 core_traits 视为不完整）"""
    if not bible or not isinstance(bible, dict):
        return True
    for field in _BIBLE_REQUIRED_FIELDS:
        val = bible.get(field)
        if not val or (isinstance(val, (dict, list)) and not val):
            return True
    return False


def _ensure_bibles(llm, paths) -> int:
    """为 bible 不完整的角色自动生成圣经，返回补全数"""
    from infra.config import load_yaml_entities, load_yaml_full, save_yaml
    from engines.character_bible import generate_bible

    chars = load_yaml_entities(paths.characters_dir, "character")
    incomplete = [c for c in chars if _bible_is_incomplete(c.get("bible", {}))]
    if not incomplete:
        return 0

    logger.info(f"发现 {len(incomplete)} 个角色圣经不完整，自动生成...")
    count = 0
    for char in incomplete:
        cid = char.get("id", "?")
        try:
            bible = generate_bible(llm, char)
            if not bible:
                logger.warning(f"  ⚠ 角色 {cid} 圣经生成失败（LLM 返回空）")
                continue
            # 合并：保留已有的 core_traits/core_traits_en，补全其他字段
            existing_bible = char.get("bible", {}) or {}
            merged = {**existing_bible, **bible}
            merged.setdefault("core_traits", existing_bible.get("core_traits", ""))
            merged.setdefault("core_traits_en", existing_bible.get("core_traits_en", ""))
            char["bible"] = merged

            # 回写 YAML
            fpath = paths.character_yaml(cid)
            data = load_yaml_full(fpath) if fpath.exists() else {"character": {}}
            data.setdefault("character", {})["bible"] = merged
            save_yaml(fpath, data)
            count += 1
            logger.info(f"  ✅ 角色 {cid} 圣经已补全")
        except Exception as e:
            logger.warning(f"  ⚠ 角色 {cid} 圣经生成异常: {e}")

    return count


def _ai_prepare_inner(self, config_path, episode, force, translate):
    """准备阶段核心逻辑（在 project_scope 内执行）"""
    from engines.prompt import batch_translate_to_english
    from engines.storyboard import load_storyboard

    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 5, "message": "正在初始化..."})
    cfg, cont = _init_ctx(config_path)
    paths = cfg.paths

    if not translate:
        return {"status": STATUS_DONE, "message": "跳过翻译（--no-translate）"}

    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    # 1. 补全空的 bible 字段（角色圣经）
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 8, "message": "检查角色圣经..."})
    bible_count = _ensure_bibles(llm, paths)

    # 2. 收集待翻译文本
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 15, "message": "扫描角色/场景/分镜..."})
    all_texts, text_meta = _collect_translation_texts(paths, force)
    shots = load_storyboard(episode)
    _collect_shot_texts(shots, all_texts, text_meta, force)

    if not all_texts:
        result = {"status": STATUS_DONE, "message": "无需翻译（所有字段已有英文版）",
                  "characters": 0, "scenes": 0, "shots": 0}
        if bible_count:
            result["bibles_generated"] = bible_count
        return result

    # 3. 批量翻译
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 40,
                      "message": f"正在翻译 {len(all_texts)} 条文本..."})
    try:
        results = batch_translate_to_english(all_texts, llm)
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"翻译失败: {e}"}

    # 4. 回写 + 视角 prompt
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 80, "message": "正在保存..."})
    translated, char_cache = _writeback_translations(text_meta, results, paths, episode, shots)

    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 90, "message": "生成视角 prompt..."})
    translated["view_prompts"] = _generate_view_prompts(char_cache, llm, paths)

    msg = f"翻译完成: {translated['characters']} 角色, {translated['scenes']} 场景, {translated['shots']} 镜头"
    if bible_count:
        msg += f"，补全 {bible_count} 个角色圣经"
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 100, "message": msg})
    result = {"status": STATUS_DONE, "message": msg, **translated}
    if bible_count:
        result["bibles_generated"] = bible_count
    _run_quality_gate(paths, result)
    return result


# ══════════════════════════════════════════════════════════
#  Seko 策划案导入（异步，含图片下载）
# ══════════════════════════════════════════════════════════
