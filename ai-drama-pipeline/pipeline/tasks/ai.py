"""Celery 任务定义 — AI 生成（分镜/实体/对话编辑）

阶段职责分离：
  - ai_storyboard_task: 只生成分镜（注入已有角色/场景提升质量）
  - ai_entities_task: 从分镜提取引用，批量生成缺失的角色/场景
  - ai_chat_edit_task: 对话式编辑分镜
  - ai_prepare_task: 批量翻译 + 视角 prompt（在 prepare.py 中）
"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import json
import logging

from pipeline.app import app
from pipeline.tasks.helpers import _build_ctx, _project_scope_from_config
from infra.json_parse import parse_llm_json
from engines.content.llm import StoryboardGenParams

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  阶段 1: AI 分镜 — 只生成分镜，不碰实体
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_ai_storyboard", soft_time_limit=600)
def ai_storyboard_task(self, config_path: str, episode: int, outline: str,
                       duration: int = 90, append: bool = False):
    """AI 生成分镜表（只生成分镜，不生成角色/场景）

    注入已有角色/场景到 LLM prompt，提升分镜质量。
    实体生成由 ai_entities_task 独立负责。
    """
    with _project_scope_from_config(config_path):
        return _ai_storyboard_inner(self, config_path, episode, outline, duration, append)


def _ai_storyboard_inner(self, config_path, episode, outline, duration, append):
    """ai_storyboard 核心逻辑"""
    from engines.content.storyboard import save_storyboard, append_storyboard
    from infra.config import load_yaml_entities

    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 10, "message": "正在初始化 LLM..."})
    cfg, cont = _build_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    style, genre = cfg.get("project", {}).get("style", ""), cfg.get("project", {}).get("genre", "")

    # 读取已有角色/场景注入 prompt（提升分镜质量，LLM 用已有实体名）
    characters = load_yaml_entities(cfg.paths.characters_dir, "character")
    scenes = load_yaml_entities(cfg.paths.scenes_dir, "scene")

    # 1. 生成分镜
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 30, "message": "AI 正在生成分镜..."})
    shots_result = _generate_shots(llm, outline, episode, duration, style, genre, characters, scenes)
    if isinstance(shots_result, dict):
        if "status" in shots_result:
            return shots_result
        shots = shots_result["shots"]
        gen_warnings = shots_result.get("warnings", [])
    else:
        shots = shots_result
        gen_warnings = []

    # 2. 保存分镜
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 90, "message": "正在保存..."})
    from engines.content.storyboard import validate_shot
    invalid_shots = []
    for s in shots:
        errs = validate_shot(s)
        if errs:
            invalid_shots.append(f"shot_id={s.get('shot_id', '?')}: {', '.join(errs)}")
    if invalid_shots:
        logger.warning(f"分镜数据校验: {len(invalid_shots)} 个镜头有问题: {'; '.join(invalid_shots[:5])}")
    (append_storyboard if append else save_storyboard)(shots, episode)

    # 统计引用的实体（仅报告，不生成）
    char_names, scene_names = _extract_entity_names(shots)
    existing_char_names = {c["name"] for c in characters}
    existing_scene_names = {s["name"] for s in scenes}
    missing_chars = sorted(char_names - existing_char_names)
    missing_scenes = sorted(scene_names - existing_scene_names)

    result = {"status": STATUS_DONE, "episode": episode, "count": len(shots),
              "total_duration": sum(int(s.get("duration", 4)) for s in shots), "shots": shots,
              "missing_characters": missing_chars, "missing_scenes": missing_scenes}
    if gen_warnings:
        result["warnings"] = gen_warnings
    if missing_chars or missing_scenes:
        result.setdefault("warnings", []).append(
            f"引用了 {len(missing_chars)} 个未创建的角色、{len(missing_scenes)} 个未创建的场景，"
            f"请执行「👥 AI 实体生成」或手动创建")
    return result


def _generate_shots(llm, outline, episode, duration, style, genre, characters=None, scenes=None):
    """生成分镜，成功返回 list[dict]，失败返回 error dict"""
    from engines.content.llm import generate_storyboard
    try:
        shots, gen_warnings = generate_storyboard(llm, StoryboardGenParams(
            outline=outline, characters=characters or [], scenes=scenes or [],
            episode=episode, target_duration=duration, style=style, genre=genre))
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 生成失败: {e}"}
    if not shots:
        detail = gen_warnings[0] if gen_warnings else "LLM 未能生成有效分镜"
        return {"status": STATUS_ERROR, "reason": detail}
    if gen_warnings:
        return {"shots": shots, "warnings": gen_warnings}
    return shots


def _extract_entity_names(shots: list[dict]) -> tuple[set[str], set[str]]:
    """从分镜中提取所有引用的角色/场景名"""
    from engines.utils.shot import parse_char_names
    char_names, scene_names = set(), set()
    for shot in shots:
        char_names.update(parse_char_names(shot))
        sid = (shot.get("scene_name") or "").strip()
        if sid:
            scene_names.add(sid)
    return char_names, scene_names


def _dedup_scene_names(shots: list[dict], scene_names: set[str], llm: object) -> dict[str, str]:
    """检测并合并重复的 scene_name（LLM 常为同一物理位置生成不同 ID）

    使用 LLM 审查所有 scene_name + 关联 action，返回 {旧id: 规范id} 映射。
    场景数 ≤ 5 或 LLM 不可用时跳过（不需要去重）。
    """
    if len(scene_names) <= 5 or not llm:
        return {}

    # 构建每个 scene_name 关联的 action 描述（取前 3 条）
    scene_actions: dict[str, list[str]] = {}
    for shot in shots:
        sid = (shot.get("scene_name") or "").strip()
        if sid:
            scene_actions.setdefault(sid, []).append(shot.get("action", "")[:100])

    scene_list = []
    for sid in sorted(scene_names):
        actions = scene_actions.get(sid, [])[:3]
        action_text = " | ".join(a for a in actions if a)
        scene_list.append(f"- {sid}: {action_text}")

    scene_desc = "\n".join(scene_list)
    prompt = f"""以下是一部短剧中出现的所有场景 ID 及其关联画面描述。
请检查是否有不同 scene_name 实际指向同一物理位置的情况。

场景列表：
{scene_desc}

规则：
- 只合并确定是同一物理位置的场景（如同一客厅、同一条街）
- 不要合并不同时间/氛围的同一地点（如"白天客厅"和"深夜客厅"可保留不同）
- 如果没有需要合并的，返回空对象 {{}}

输出格式（严格 JSON 对象，key=旧id, value=保留的规范id）：
{{"old_id": "canonical_id", ...}}

只输出 JSON，不要其他文字。"""

    try:
        from infra.json_parse import parse_llm_json
        raw = llm.chat(prompt, system="你是场景去重助手。只输出 JSON。")
        result = parse_llm_json(raw)
        if isinstance(result, dict) and result:
            # 校验：所有 key/value 必须在 scene_names 中
            valid = {k: v for k, v in result.items()
                     if k in scene_names and v in scene_names and k != v}
            if valid:
                logger.info(f"场景去重: {len(valid)} 个 scene_name 需合并 → {set(valid.values())}")
                return valid
    except Exception as e:
        logger.warning(f"场景去重跳过（LLM 调用失败）: {e}")
    return {}


def _apply_scene_remap(shots: list[dict], remap: dict[str, str], episode: int) -> None:
    """将 scene_name 重映射应用到分镜数据并更新 DB"""
    if not remap:
        return
    updated = 0
    for shot in shots:
        sid = (shot.get("scene_name") or "").strip()
        if sid in remap:
            shot["scene_name"] = remap[sid]
            updated += 1
    if updated:
        from engines.content.storyboard import save_storyboard
        save_storyboard(shots, episode)
        logger.info(f"场景去重: 更新了 {updated} 个镜头的 scene_name")


# ══════════════════════════════════════════════════════════
#  阶段 2: AI 实体 — 从分镜提取引用，批量生成缺失的角色/场景
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_ai_entities", soft_time_limit=600)
def ai_entities_task(self, config_path: str, episode: int) -> dict:
    """AI 批量生成分镜引用的角色和场景（只生成缺失的，不覆盖已有）

    从 DB 读取分镜 → 提取引用的实体 ID → 过滤已有 → LLM 批量生成 → 保存 YAML
    """
    with _project_scope_from_config(config_path):
        return _ai_entities_inner(self, config_path, episode)


def _ai_entities_inner(self, config_path, episode):
    """ai_entities 核心逻辑"""
    from engines.content.storyboard import load_storyboard
    from engines.utils.entity import generate_and_save, build_entity_descriptions
    from infra.config import load_existing_entities

    self.update_state(state="PROGRESS", meta={"step": "ai_entities", "progress": 10, "message": "正在初始化 LLM..."})
    cfg, cont = _build_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    # 1. 从 DB 读取分镜
    self.update_state(state="PROGRESS", meta={"step": "ai_entities", "progress": 15, "message": "扫描分镜引用..."})
    shots = load_storyboard(episode)
    if not shots:
        return {"status": STATUS_ERROR, "reason": f"第{episode}集没有分镜，请先生成分镜"}

    # 2. 提取引用的实体名，过滤已有
    char_names, scene_names = _extract_entity_names(shots)
    existing_char_names = {e["name"] for e in load_existing_entities(cfg.paths.characters_dir, "character")}
    existing_scene_names = {e["name"] for e in load_existing_entities(cfg.paths.scenes_dir, "scene")}

    # 场景去重：LLM 常为同一物理位置生成不同 scene_name，合并后再生成实体
    scene_remap = _dedup_scene_names(shots, scene_names, llm)
    if scene_remap:
        _apply_scene_remap(shots, scene_remap, episode)
        _, scene_names = _extract_entity_names(shots)

    missing_chars = sorted(char_names - existing_char_names)
    missing_scenes = sorted(scene_names - existing_scene_names)

    if not missing_chars and not missing_scenes:
        return {"status": STATUS_DONE, "message": "所有引用的实体已存在，无需生成",
                "characters": 0, "scenes": 0}

    style = cfg.get("project", {}).get("style", "")
    genre = cfg.get("project", {}).get("genre", "")
    outline = ""  # 从分镜反推描述，不需要大纲

    warnings = []
    generated_chars, generated_scenes = [], []

    # 3. 生成缺失的角色
    if missing_chars:
        self.update_state(state="PROGRESS", meta={"step": "ai_entities", "progress": 30,
                          "message": f"正在生成 {len(missing_chars)} 个角色..."})
        descriptions = build_entity_descriptions(shots, missing_chars, outline, style, genre, "character")
        result = generate_and_save(llm, descriptions, "character", cfg.paths.characters_dir)
        if result.get("status") == STATUS_ERROR:
            warnings.append(f"角色生成失败: {result['reason']}")
        else:
            generated_chars = result.get("entities", [])
            warnings.extend(result.get("warnings", []))

    # 4. 生成缺失的场景
    if missing_scenes:
        progress = 70 if missing_chars else 30
        self.update_state(state="PROGRESS", meta={"step": "ai_entities", "progress": progress,
                          "message": f"正在生成 {len(missing_scenes)} 个场景..."})
        descriptions = build_entity_descriptions(shots, missing_scenes, outline, style, genre, "scene")
        result = generate_and_save(llm, descriptions, "scene", cfg.paths.scenes_dir)
        if result.get("status") == STATUS_ERROR:
            warnings.append(f"场景生成失败: {result['reason']}")
        else:
            generated_scenes = result.get("entities", [])
            warnings.extend(result.get("warnings", []))

    msg = f"实体生成完成: {len(generated_chars)} 角色, {len(generated_scenes)} 场景"
    self.update_state(state="PROGRESS", meta={"step": "ai_entities", "progress": 100, "message": msg})
    result = {"status": STATUS_DONE, "message": msg,
              "characters": len(generated_chars), "scenes": len(generated_scenes),
              "generated_characters": generated_chars, "generated_scenes": generated_scenes}
    if warnings:
        result["warnings"] = warnings
    return result


def _ai_entity_task(self, config_path, descriptions, step, msg, entity_key, dir_fn, result_key):
    """AI 生成实体（角色/场景）通用逻辑"""
    with _project_scope_from_config(config_path):
        from engines.utils.entity import generate_and_save
        self.update_state(state="PROGRESS", meta={"step": step, "progress": 20, "message": msg})
        cfg, cont = _build_ctx(config_path)
        try:
            llm = cont.get("llm")
        except Exception as e:
            return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}
        result = generate_and_save(llm, descriptions, entity_key, dir_fn(cfg.paths))
        if result.get("status") == STATUS_ERROR:
            return {"status": STATUS_ERROR, "reason": result["reason"]}
        return {"status": STATUS_DONE, "count": result["count"], result_key: result["entities"]}


@app.task(bind=True, name="pipeline_ai_characters", soft_time_limit=300)
def ai_characters_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成角色（异步）"""
    return _ai_entity_task(self, config_path, descriptions, "ai_characters", "AI 正在生成角色...",
                           "character", lambda p: p.characters_dir, "characters")


@app.task(bind=True, name="pipeline_ai_scenes", soft_time_limit=300)
def ai_scenes_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成场景（异步）"""
    return _ai_entity_task(self, config_path, descriptions, "ai_scenes", "AI 正在生成场景...",
                           "scene", lambda p: p.scenes_dir, "scenes")


# ══════════════════════════════════════════════════════════
#  对话式编辑 — LLM Chat Edit
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline_ai_chat_edit", soft_time_limit=300)
def ai_chat_edit_task(self, config_path: str, episode: int, message: str, current_shots: list) -> dict:
    """对话式编辑分镜 — 用自然语言修改分镜表"""
    with _project_scope_from_config(config_path):
        return _ai_chat_edit_inner(self, config_path, episode, message, current_shots)


def _ai_chat_edit_inner(self, config_path, episode, message, current_shots):
    """对话式编辑核心逻辑（在 project_scope 内执行）"""
    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 10, "message": "正在初始化 LLM..."})
    _, cont = _build_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": STATUS_ERROR, "reason": f"LLM 初始化失败: {e}"}

    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 30, "message": "AI 正在理解指令..."})
    # 收集角色/场景名称列表，帮助 LLM 理解引用
    char_names, scene_names = [], []
    try:
        from infra.config import load_project_entities
        cfg_obj, _ = _build_ctx(config_path)
        chars, scenes = load_project_entities(cfg_obj.paths)
        char_names = list(chars.keys())
        scene_names = list(scenes.keys())
    except Exception:
        pass
    prompt = _build_chat_edit_prompt(message, current_shots, char_names, scene_names)

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

    # 后处理：shot_id 去重、duration 截断、引号清理、emotion 校验
    from engines.utils.shot import postprocess_shots
    result = postprocess_shots(result, episode)

    for shot in result:
        shot["episode"] = episode

    # 截断时保留未修改的尾部镜头（LLM 只看到前 MAX_SHOTS_FOR_EDIT 个）
    if len(current_shots) > MAX_SHOTS_FOR_EDIT:
        tail_shots = current_shots[MAX_SHOTS_FOR_EDIT:]
        for s in tail_shots:
            s["episode"] = episode
        # 去重：如果 LLM 生成的 shot_id 与尾部冲突，保留 LLM 版本，丢弃尾部重复
        llm_ids = {s.get("shot_id") for s in result}
        deduped_tail = [s for s in tail_shots if s.get("shot_id") not in llm_ids]
        if len(deduped_tail) < len(tail_shots):
            logger.warning(f"chat_edit: 截断合并时丢弃了 {len(tail_shots) - len(deduped_tail)} 个重复 shot_id 的尾部镜头")
        result = result + deduped_tail
        logger.info(f"chat_edit: 保留 {len(deduped_tail)} 个未修改的尾部镜头")

    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 90, "message": "编辑完成"})

    # 自动保存编辑结果到 DB（与 ai_storyboard_task 行为一致，防止前端未保存导致丢失）
    from engines.content.storyboard import save_storyboard
    save_storyboard(result, episode)

    resp = {"status": STATUS_DONE, "shots": result, "message": f"已修改 {min(len(result), MAX_SHOTS_FOR_EDIT)} 个镜头（共 {len(result)} 个）"}
    return resp


MAX_SHOTS_FOR_EDIT = 50


def _build_chat_edit_prompt(message: str, current_shots: list, characters: list[str] | None = None, scenes: list[str] | None = None) -> str:
    """构建对话式编辑 prompt"""
    truncation_note = ""
    shots_for_prompt = current_shots
    if len(current_shots) > MAX_SHOTS_FOR_EDIT:
        shots_for_prompt = current_shots[:MAX_SHOTS_FOR_EDIT]
        truncation_note = f"\n注意：分镜表共 {len(current_shots)} 个镜头，此处只显示前 {MAX_SHOTS_FOR_EDIT} 个。"
    shots_json = json.dumps(shots_for_prompt, ensure_ascii=False, indent=2)

    context = ""
    if characters:
        context += f"\n已知角色名：{', '.join(characters)}"
    if scenes:
        context += f"\n已知场景名：{', '.join(scenes)}"

    return f"""你是一个分镜表编辑助手。用户会用自然语言描述对分镜表的修改需求。
当前分镜表（JSON 格式）：
{shots_json}{truncation_note}{context}

用户指令：{message}

请根据用户的指令修改分镜表，返回修改后的完整分镜表 JSON 数组。
只返回 JSON 数组，不要其他文字。确保所有字段都保留。
镜头总数必须保持在 {len(shots_for_prompt)} 个左右（±3），不得大幅增减。
如果用户的指令不清晰或无法执行，返回一个 JSON 对象：{{"error": "原因说明"}}"""


def _validate_chat_edit_output(result: list) -> str | None:
    """校验 chat_edit 输出，返回错误信息或 None"""
    required = {"shot_id", "scene_name", "characters", "action", "dialogue"}
    invalid = []
    seen_ids: set[str] = set()
    for i, shot in enumerate(result):
        if not isinstance(shot, dict):
            invalid.append(f"第{i+1}项不是对象")
            continue
        missing = required - set(shot.keys())
        if missing:
            invalid.append(f"shot_id={shot.get('shot_id', '?')} 缺少: {', '.join(missing)}")
        sid = shot.get("shot_id", "")
        if sid:
            if sid in seen_ids:
                invalid.append(f"重复的 shot_id: {sid}")
            seen_ids.add(sid)
    if invalid:
        logger.warning(f"chat_edit 输出校验失败: {invalid[:5]}")
        return f"LLM 返回的分镜数据不完整（{len(invalid)} 处）: {'; '.join(invalid[:3])}"
    return None

