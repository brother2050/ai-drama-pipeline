"""Celery 任务定义 — 准备阶段（批量翻译 + 视角 prompt）

职责：
  - 扫描缺失的英文字段
  - 批量翻译（UID 标记，按 UID 匹配结果）
  - 回写 YAML + DB
  - 生成视角 prompt
"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import json
import logging
import re

from pipeline.app import app
from pipeline.tasks.helpers import _build_ctx, _project_scope_from_config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  准备阶段 — 补全缺失的英文字段（翻译兜底）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_ai_prepare", soft_time_limit=600)
def ai_prepare_task(self, config_path: str, episode: int,
                    force: bool = False, translate: bool = True) -> dict:
    """准备阶段 — 补全缺失的英文字段 + 生成视角 prompt

    新生成的角色/场景已自带中英双语（LLM 一次生成）。
    此阶段仅作兜底：扫描缺失的英文字段，批量翻译补全。
    """
    with _project_scope_from_config(config_path):
        return _ai_prepare_inner(self, config_path, episode, force, translate)


# ── 序列化工具 ──────────────────────────────────────

def _serialize_dict_for_translate(d: dict) -> str:
    """将 dict 序列化为 JSON 字符串（翻译用）"""
    return json.dumps(d, ensure_ascii=False)


def _serialize_list_for_translate(items: list) -> str:
    """将 list 序列化为 JSON 字符串（翻译用）"""
    return json.dumps(items, ensure_ascii=False)


# ── 翻译质量检测 ──────────────────────────────────────

def _has_chinese(text: str, min_count: int = 3, min_ratio: float = 0.15) -> bool:
    """检查文本是否含中文字符（≥min_count 个或比例 ≥min_ratio）"""
    cn = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    return cn >= min_count or cn / max(len(text), 1) >= min_ratio


def _is_bad_translation(src: str, tgt: str) -> bool:
    """统一的翻译质量检查 — 源为中文时，翻译不应仍含中文"""
    if not tgt or not tgt.strip():
        return True
    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', src):
        if _has_chinese(tgt):
            return True
    if len(src) > 10 and len(tgt.split()) < 3:
        return True
    return False


# ── 收集缺失文本 ──────────────────────────────────────

def _collect_bible_missing(char: dict, cid: str, all_texts: list[str],
                           text_meta: list[tuple], force: bool = False) -> None:
    """收集角色 bible 中缺失英文的字段"""
    bible = char.get("bible", {})
    if not isinstance(bible, dict):
        return
    bible_en = char.get("bible_en", {})
    if not isinstance(bible_en, dict):
        return

    # 字符串字段
    for field in ("core_traits", "speech_patterns", "voice_description"):
        if bible.get(field) and (force or not bible_en.get(f"{field}_en")):
            all_texts.append(bible[field])
            text_meta.append(("character.bible", cid, field, f"{field}_en"))

    # dict 字段 — 含 relationships（键名是角色名也需翻译，LLM 会一并处理）
    for field in ("emotional_range", "body_language", "relationships"):
        data = bible.get(field, {})
        if isinstance(data, dict) and data and (force or not bible_en.get(f"{field}_en")):
            all_texts.append(_serialize_dict_for_translate(data))
            text_meta.append(("character.bible_dict", cid, field, f"{field}_en"))

    # list 字段
    for field in ("habits", "taboos"):
        items = bible.get(field, [])
        if isinstance(items, list) and items and (force or not bible_en.get(f"{field}_en")):
            all_texts.append(_serialize_list_for_translate(items))
            text_meta.append(("character.bible_list", cid, field, f"{field}_en"))


def _collect_missing_texts(paths, episode: int, force: bool = False) -> tuple[list[str], list[tuple]]:
    """收集所有缺失英文的文本 → (texts, meta)

    meta 元组: (entity_type, entity_id, src_field, tgt_field)
    """
    from infra.config import load_character, load_yaml_full

    all_texts: list[str] = []
    text_meta: list[tuple] = []

    # 角色
    char_dir = paths.characters_dir
    if char_dir.exists():
        for f in sorted(char_dir.glob("*.yaml")):
            if f.stem.endswith(".example"):
                continue
            try:
                char = load_character(char_dir, f.stem)
                cid = char.get("id", f.stem)
            except Exception as e:
                logger.warning(f"跳过损坏的角色配置 {f.name}: {e}")
                continue

            # outfits
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict):
                for okey, odata in outfits.items():
                    if isinstance(odata, dict) and odata.get("description") and (force or not odata.get("description_en")):
                        all_texts.append(odata["description"])
                        text_meta.append(("character.outfits", f"{cid}.{okey}", "description", "description_en"))

            # bible → bible_en
            _collect_bible_missing(char, cid, all_texts, text_meta, force)

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

    # 分镜（action/dialogue）
    from engines.content.storyboard import load_storyboard
    shots = load_storyboard(episode)
    for shot in shots:
        sid = shot.get("shot_id", "")
        if shot.get("action") and (force or not shot.get("action_en")):
            all_texts.append(shot["action"])
            text_meta.append(("shot", sid, "action", "action_en"))
        if shot.get("dialogue") and shot.get("dialogue") != "......" and (force or not shot.get("dialogue_en")):
            all_texts.append(shot["dialogue"])
            text_meta.append(("shot", sid, "dialogue", "dialogue_en"))

    return all_texts, text_meta


# ── 上下文标记处理 ──────────────────────────────────────

# 匹配一个或多个 context marker: [CHAR:xxx], [SCENE:xxx|FIELD:yyy], [SHOT:xxx|FIELD:yyy], [OUTFIT:xxx]
_RE_CONTEXT_MARKER = re.compile(r'^(?:\[(?:CHAR|SCENE|SHOT|OUTFIT):[^\]]+\]\s*)+')


def _strip_context_markers(text: str) -> str:
    """剥离翻译文本开头的上下文标记"""
    if not text:
        return text
    return _RE_CONTEXT_MARKER.sub('', text).strip()


def _extract_field_marker(text: str) -> tuple[str | None, str]:
    """从翻译结果中提取 [FIELD: xxx] 标记，返回 (field_name, cleaned_text)"""
    if not text:
        return None, text
    cleaned = _strip_context_markers(text)
    m = re.match(r'^\[FIELD:\s*(\w+)\]\s*(.*)', cleaned, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    return None, cleaned


# ── 回写翻译结果 ──────────────────────────────────────

def _writeback_translations(text_meta: list[tuple], results: list[str],
                            paths, episode: int, shots: list[dict]) -> tuple[dict, dict, list]:
    """回写翻译结果到 YAML + DB，返回 (统计, char_cache, skipped_items)"""
    from infra.config import save_yaml, load_yaml_full
    translated = {"characters": 0, "scenes": 0, "shots": 0}
    skipped_items = []
    char_cache: dict[str, dict] = {}

    # 按实体分组收集翻译结果
    char_updates: dict[str, dict] = {}    # cid → {field: value}
    scene_updates: dict[str, dict] = {}   # sid → {field: value}
    shot_updates: dict[str, dict] = {}    # shot_id → {field: value}

    for i, (etype, eid, src_field, tgt_field) in enumerate(text_meta):
        if i >= len(results) or not results[i]:
            skipped_items.append((etype, eid, src_field, tgt_field))
            continue
        translated_text = results[i]

        if etype == "character":
            char_updates.setdefault(eid, {})[tgt_field] = translated_text
        elif etype == "character.outfits":
            cid, okey = eid.split(".", 1)
            char_updates.setdefault(cid, {}).setdefault("__outfits__", {})[f"{okey}.{tgt_field}"] = translated_text
        elif etype == "character.bible":
            char_updates.setdefault(eid, {}).setdefault("__bible_en__", {})[tgt_field] = translated_text
        elif etype in ("character.bible_dict", "character.bible_list"):
            expected_type = dict if etype.endswith("_dict") else list
            try:
                parsed = json.loads(translated_text)
                value = parsed if isinstance(parsed, expected_type) else translated_text
            except (json.JSONDecodeError, ValueError):
                value = translated_text
            char_updates.setdefault(eid, {}).setdefault("__bible_en__", {})[tgt_field] = value
        elif etype == "scene":
            scene_updates.setdefault(eid, {})[tgt_field] = translated_text
        elif etype == "shot":
            shot_updates.setdefault(eid, {})[tgt_field] = translated_text

    # 写入角色
    for cid, updates in char_updates.items():
        fpath = paths.character_yaml(cid)
        data = load_yaml_full(fpath) if fpath.exists() else {"character": {"id": cid}}
        char = data.setdefault("character", {"id": cid})

        # 直接字段
        for k, v in updates.items():
            if not k.startswith("__"):
                char[k] = v

        # outfits
        outfit_updates = updates.get("__outfits__", {})
        for compound_key, val in outfit_updates.items():
            okey, field = compound_key.split(".", 1)
            outfits = char.setdefault("outfits", {})
            if okey not in outfits:
                outfits[okey] = {"description": "", "description_en": "", "reference_images": []}
            outfits[okey][field] = val

        # bible_en
        bible_en_updates = updates.get("__bible_en__", {})
        bible_en = char.setdefault("bible_en", {})
        for k, v in bible_en_updates.items():
            bible_en[k] = v

        save_yaml(fpath, data)
        char_cache[cid] = data
        translated["characters"] += 1

    # 写入场景
    for sid, updates in scene_updates.items():
        fpath = paths.scene_yaml(sid)
        data = load_yaml_full(fpath) if fpath.exists() else {"scene": {"id": sid}}
        scene = data.setdefault("scene", {"id": sid})
        for k, v in updates.items():
            scene[k] = v
        save_yaml(fpath, data)
        translated["scenes"] += 1

    # 写入分镜
    if shot_updates:
        for s in shots:
            sid = s.get("shot_id")
            if sid in shot_updates:
                s.update(shot_updates[sid])
        from engines.content.storyboard import save_storyboard
        save_storyboard(shots, episode)
        translated["shots"] = len(shot_updates)

    return translated, char_cache, skipped_items


# ── 视角 prompt 生成 ──────────────────────────────────────

def _generate_view_prompts(char_cache, llm, paths, force: bool = False) -> tuple[int, str | None]:
    """为角色生成 AI 绘图 prompt，返回 (成功数, 错误信息或 None)"""
    from engines.prompt.builder import batch_generate_appearance_prompts
    from infra.config import save_yaml

    chars_with_appearance = [
        d.get("character", {}) for d in char_cache.values()
        if d.get("character", {}).get("appearance")
        and (force or not d.get("character", {}).get("appearance_prompt_en"))
    ]
    if not chars_with_appearance or not llm:
        return 0, None
    try:
        view_mapping = batch_generate_appearance_prompts(chars_with_appearance, llm)
        for cid, prompts in view_mapping.items():
            if cid not in char_cache:
                continue
            char = char_cache[cid].setdefault("character", {})
            char["appearance_prompt_en"] = prompts.get("appearance_prompt_en", "")
            char["body_features"] = prompts.get("body_features", "")
            save_yaml(paths.character_yaml(cid), char_cache[cid])
        if view_mapping:
            logger.info(f"  ✅ 视角 prompt 生成完成: {len(view_mapping)} 个角色")

        failed_count = len(chars_with_appearance) - len(view_mapping)
        if failed_count > 0:
            return len(view_mapping), f"{failed_count}/{len(chars_with_appearance)} 个角色的视角 prompt 生成失败"
        return len(view_mapping), None
    except Exception as e:
        logger.warning(f"  ⚠ 视角 prompt 生成失败: {e}")
        return 0, f"视角 prompt 生成异常: {e}"


# ── 质量门禁 ──────────────────────────────────────

def _run_quality_gate(paths, result: dict) -> None:
    """运行质量门禁，将警告注入 result"""
    try:
        from engines.quality_gate import check_quality
        issues = check_quality("after_prepare", str(paths.root))
        if issues:
            for w in [i for i in issues if i["severity"] == "warning"]:
                details = w.get("details", [])
                if details:
                    shown = "; ".join(details[:5])
                    suffix = f"（还有 {len(details) - 5} 项）" if len(details) > 5 else ""
                    logger.warning(f"⚠ 质量检查: {w['name']} — {w['message']}（{shown}{suffix}）")
                else:
                    logger.warning(f"⚠ 质量检查: {w['name']} — {w['message']}")
            result["quality_issues"] = issues
    except Exception as e:
        logger.warning(f"质量门禁跳过: {e}")


# ── 核心逻辑 ──────────────────────────────────────

def _ai_prepare_inner(self, config_path, episode, force, translate):
    """准备阶段核心逻辑 — 补全缺失的英文字段 + 视角 prompt"""
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 5, "message": "正在初始化..."})
    cfg, cont = _build_ctx(config_path)
    paths = cfg.paths

    if not translate:
        return {"status": STATUS_DONE, "message": "跳过翻译（--no-translate）"}

    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    # 1. 收集缺失的英文字段
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 10, "message": "扫描缺失英文字段..."})
    all_texts, text_meta = _collect_missing_texts(paths, episode, force)

    if not all_texts:
        char_cache = _load_char_cache(paths)
        self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 90, "message": "生成视角 prompt..."})
        view_count, _ = _generate_view_prompts(char_cache, llm, paths, force=force)
        return {"status": STATUS_DONE, "message": "无需翻译（所有字段已有英文版）",
                "characters": 0, "scenes": 0, "shots": 0, "view_prompts": view_count}

    # 2. 批量翻译
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 30,
                      "message": f"正在翻译 {len(all_texts)} 条文本..."})
    try:
        results = _batch_translate_texts(all_texts, llm, self)
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"翻译失败: {e}"}

    # 3. 翻译质量校验 + 重试失败项
    self.update_state(state="PROGRESS", meta={"step": "validate", "progress": 65, "message": "校验翻译质量..."})
    results = _validate_and_retry(all_texts, results, text_meta, llm)

    # 4. 回写
    self.update_state(state="PROGRESS", meta={"step": "writeback", "progress": 80, "message": "正在保存..."})
    from engines.content.storyboard import load_storyboard
    shots = load_storyboard(episode)
    translated, char_cache, skipped_items = _writeback_translations(text_meta, results, paths, episode, shots)

    # 5. 视角 prompt
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 90, "message": "生成视角 prompt..."})
    view_count, view_error = _generate_view_prompts(char_cache, llm, paths, force=force)
    translated["view_prompts"] = view_count

    # 6. 汇总
    msg = f"翻译完成: {translated['characters']} 角色, {translated['scenes']} 场景, {translated['shots']} 镜头"
    self.update_state(state="PROGRESS", meta={"step": "prepare", "progress": 100, "message": msg})
    result = {"status": STATUS_DONE, "message": msg, **translated}
    if view_error:
        result.setdefault("translation_warnings", []).append(f"视角 prompt: {view_error}")
    if skipped_items:
        by_type: dict[str, int] = {}
        for etype, *_ in skipped_items:
            by_type[etype.split(".")[0]] = by_type.get(etype.split(".")[0], 0) + 1
        detail = "; ".join(f"{t}: {n} 项" for t, n in by_type.items())
        result["translation_warnings"] = [f"{len(skipped_items)} 条翻译失败: {detail}"]
    _run_quality_gate(paths, result)
    return result


# ── 批量翻译 ──────────────────────────────────────

def _batch_translate_texts(all_texts: list[str], llm: object, task_self=None) -> list[str]:
    """批量翻译 — UID 标记，按 UID 精确匹配结果"""
    from engines.prompt.translate import batch_translate_to_english, translate_to_english

    # 为每条文本分配 UID
    uid_to_idx: dict[str, int] = {}
    uid_texts: list[tuple[str, str]] = []  # (uid, text)
    for i, text in enumerate(all_texts):
        uid = f"t{i:06x}"
        uid_to_idx[uid] = i
        uid_texts.append((uid, text))

    results = [""] * len(all_texts)

    # 按批次处理
    batch_size = 15
    batches = [uid_texts[i:i + batch_size] for i in range(0, len(uid_texts), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if task_self:
            progress = 30 + int(35 * batch_idx / max(len(batches), 1))
            task_self.update_state(state="PROGRESS", meta={
                "step": "translate", "progress": progress,
                "message": f"翻译批次 {batch_idx + 1}/{len(batches)}..."})

        texts = [text for _, text in batch]
        try:
            batch_results = batch_translate_to_english(texts, llm)
            for j, (uid, _) in enumerate(batch):
                if j < len(batch_results) and batch_results[j]:
                    results[uid_to_idx[uid]] = batch_results[j]
        except Exception as e:
            logger.warning(f"翻译批次 {batch_idx + 1} 失败: {e}")

    return results


def _validate_and_retry(all_texts: list[str], results: list[str],
                        text_meta: list[tuple], llm: object) -> list[str]:
    """翻译质量校验 + 重试失败项：检测空/中文翻译 → 批量重试 → 逐条兜底"""
    from engines.prompt.translate import batch_translate_to_english, translate_to_english

    # 检测不合格翻译
    bad_indices = [i for i, (src, tgt) in enumerate(zip(all_texts, results))
                   if _is_bad_translation(src, tgt)]
    if not bad_indices:
        return results

    logger.warning(f"翻译校验: {len(bad_indices)}/{len(all_texts)} 条不合格，重试...")

    # 批量重试
    retry_texts = [all_texts[i] for i in bad_indices]
    try:
        retried = batch_translate_to_english(retry_texts, llm)
        still_bad = []
        for j, idx in enumerate(bad_indices):
            if j < len(retried) and retried[j] and not _is_bad_translation(all_texts[idx], retried[j]):
                results[idx] = retried[j]
            else:
                still_bad.append(idx)
        logger.info(f"  批量重试: {len(bad_indices) - len(still_bad)}/{len(bad_indices)} 成功")
    except Exception as e:
        logger.warning(f"批量重试异常: {e}")
        still_bad = bad_indices

    # 逐条兜底
    for idx in still_bad:
        try:
            translated = translate_to_english(all_texts[idx], llm)
            if translated and not _is_bad_translation(all_texts[idx], translated):
                results[idx] = translated
        except Exception:
            pass

    final_bad = sum(1 for i in still_bad if not results[i] or _is_bad_translation(all_texts[i], results[i]))
    if final_bad:
        logger.warning(f"  翻译仍有 {final_bad} 条不合格")

    return results


# ── 角色缓存 ──────────────────────────────────────

def _load_char_cache(paths) -> dict:
    """加载角色缓存（用于视角 prompt 生成）"""
    from infra.config import load_character as _load_char
    char_cache = {}
    char_dir = paths.characters_dir
    if char_dir.exists():
        for f in sorted(char_dir.glob("*.yaml")):
            if f.stem.endswith(".example"):
                continue
            try:
                char = _load_char(char_dir, f.stem)
                cid = char.get("id", f.stem)
                if char.get("appearance"):
                    char_cache[cid] = {"character": char}
            except Exception:
                continue
    return char_cache
