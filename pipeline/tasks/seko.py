"""Celery 任务定义 — Seko 影视策划案导入"""
from __future__ import annotations
from infra.config import load_yaml_full

from infra.constants import STATUS_DONE
from infra.normalize import name_to_safe_id
import logging
import re
from pathlib import Path

from pipeline.app import app
from pipeline.tasks.helpers import _paths

logger = logging.getLogger(__name__)
def _parse_seko_characters(steps: list[dict], elements: list[dict] | None = None) -> list[dict]:
    """从 Seko steps 中解析角色列表，关联 elements 图片"""
    char_step = next((s for s in steps if s.get("step") == "character_design"), None)
    if not char_step:
        return []

    output = char_step.get("stepOutput", "")
    characters = []
    used_ids: set[str] = set()
    # 按 "- 角色名" 分割
    blocks = re.split(r"\n(?=- )", output)
    for block in blocks:
        block = block.strip()
        if not block.startswith("- "):
            continue
        # 提取角色名和描述（第一行）
        first_line = block.split("\n")[0]
        match = re.match(r"^- ([^：:]+)[：:](.*)", first_line)
        if not match:
            continue
        char_name = match.group(1).strip()
        char_desc = re.sub(r"\s*<Prompt>.*", "", match.group(2), flags=re.DOTALL).strip()

        # 提取 Prompt
        prompt_match = re.search(r"<Prompt>(.*?)</Prompt>", block, re.DOTALL)
        prompt_text = prompt_match.group(1).strip() if prompt_match else ""

        # 生成 ID：名字转 safe id，去重
        safe_id = name_to_safe_id(char_name, f"char_{len(characters) + 1:02d}")
        base_id = safe_id
        suffix = 2
        while safe_id in used_ids:
            safe_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(safe_id)

        # 查找对应的 element 图片 URL
        seko_image_url = ""
        if elements:
            char_element = next(
                (e for e in elements if e.get("elementType") == "CHARACTER" and (e.get("elementName") or "").strip() == char_name),
                None,
            )
            if char_element and char_element.get("elementUrl"):
                seko_image_url = char_element["elementUrl"]

        characters.append({
            "id": safe_id,
            "name": char_name,
            "appearance": char_desc,
            "prompt": prompt_text,
            "source": "seko",
            "seko_image_url": seko_image_url,
        })

    return characters


def _parse_seko_scenes(steps: list[dict], elements: list[dict] | None = None) -> list[dict]:
    """从 Seko steps 中解析场景列表，关联 elements 图片"""
    scene_step = next((s for s in steps if s.get("step") == "scene_design"), None)
    if not scene_step:
        return []

    output = scene_step.get("stepOutput", "")
    scenes = []
    used_ids: set[str] = set()
    blocks = re.split(r"\n(?=- )", output)
    for block in blocks:
        block = block.strip()
        if not block.startswith("- "):
            continue
        first_line = block.split("\n")[0]
        match = re.match(r"^- ([^：:]+)[：:](.*)", first_line)
        if not match:
            continue
        scene_name = match.group(1).strip()
        scene_desc = re.sub(r"\s*<Prompt>.*", "", match.group(2), flags=re.DOTALL).strip()

        prompt_match = re.search(r"<Prompt>(.*?)</Prompt>", block, re.DOTALL)
        prompt_text = prompt_match.group(1).strip() if prompt_match else ""

        safe_id = name_to_safe_id(scene_name, f"scene_{len(scenes) + 1:02d}")
        base_id = safe_id
        suffix = 2
        while safe_id in used_ids:
            safe_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(safe_id)

        # 查找对应的 element 图片 URL
        seko_image_url = ""
        if elements:
            scene_element = next(
                (e for e in elements if e.get("elementType") == "SCENE" and (e.get("elementName") or "").strip() == scene_name),
                None,
            )
            if scene_element and scene_element.get("elementUrl"):
                seko_image_url = scene_element["elementUrl"]

        scenes.append({
            "id": safe_id,
            "name": scene_name,
            "description": scene_desc,
            "prompt": prompt_text,
            "source": "seko",
            "seko_image_url": seko_image_url,
        })

    return scenes


def _extract_editable_block(text: str, start_tag: str = ":editable[") -> str:
    """从文本中提取 :editable[...] 块内容（支持嵌套括号）"""
    match = re.search(re.escape(start_tag), text)
    if not match:
        return ""
    bracket_pos = match.end() - 1
    depth = 0
    for i in range(bracket_pos, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return text[bracket_pos + 1:i].strip()
    return ""


def _parse_shot_fields(desc_raw: str) -> dict:
    """从镜头描述中解析各字段"""
    fields = {"scene": "", "action": "", "camera": "", "shot_type": "", "duration": 4}

    scene_match = re.search(r"场景[：:]\s*([^\n]+)", desc_raw)
    if scene_match:
        fields["scene"] = scene_match.group(1).strip()

    duration_match = re.search(r"时长[：:]\s*(\d+)", desc_raw)
    if duration_match:
        from infra.constants import clip_duration
        fields["duration"] = clip_duration(int(duration_match.group(1)))

    action_match = re.search(r"画面[：:]\s*\[(.+?)\]\s*(.+?)(?:\n运镜|$)", desc_raw, re.DOTALL)
    if action_match:
        fields["shot_type"] = action_match.group(1).strip()
        fields["action"] = action_match.group(2).strip().replace("\n", " ").strip()

    camera_match = re.search(r"运镜[：:]\s*([^\n]+)", desc_raw)
    if camera_match:
        fields["camera"] = camera_match.group(1).strip()

    return fields


def _parse_shot_dialogue(block: str) -> tuple[str, str]:
    """从分镜块中提取台词和角色名 → (characters, dialogue)"""
    dialogue_raw = _extract_editable_block(block, "配音台词.*?:editable[")
    dialogue_raw = dialogue_raw.replace("\\n", "\n")
    if not dialogue_raw:
        return "", ""
    d_match = re.match(r'中文配音[：:]\s*\[([^\]]+)\]\s*(.*)', dialogue_raw, re.DOTALL)
    if d_match:
        return d_match.group(1).strip(), d_match.group(2).strip()
    return "", ""


def _parse_seko_storyboard(steps: list[dict], episode: int) -> list[dict]:
    """从 Seko steps 中解析分镜表"""
    sb_step = next((s for s in steps if s.get("step") == "storyboard"), None)
    if not sb_step:
        return []

    output = sb_step.get("stepOutput", "")
    shots = []

    shot_blocks = re.findall(r':::shot\{name="([^"]+)"\}(.*?)(?=\n\s*:::shot\{|\n\s*</Scene>|\Z)', output, re.DOTALL)
    for shot_name, block in shot_blocks:
        shot_id = f"{len(shots) + 1:03d}"

        desc_raw = _extract_editable_block(block)
        desc_raw = desc_raw.replace("\\n", "\n")
        fields = _parse_shot_fields(desc_raw)
        characters, dialogue = _parse_shot_dialogue(block)

        shots.append({
            "episode": episode, "shot_id": shot_id,
            "scene_name": fields["scene"], "characters": characters,
            "action": fields["action"], "dialogue": dialogue,
            "camera": fields["camera"], "shot_type": fields["shot_type"],
            "duration": str(fields["duration"]), "outfit": "", "emotion": "",
            "action_en": "", "dialogue_en": "",
        })

    return shots


def _download_seko_image(url: str, output_path: str, timeout: int = 20, retries: int = 3) -> bool:
    """下载单张 Seko 图片（指数退避重试，超时缩短防阻塞 worker）"""
    from infra.http_pool import get_client
    import time as _time

    client = get_client(timeout=timeout)
    for attempt in range(retries):
        try:
            with client.stream("GET", url, headers={"User-Agent": "Mozilla/5.0 (compatible; ai-drama-pipeline/2.0)"}) as response:
                response.raise_for_status()
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(64 * 1024):
                        f.write(chunk)
            logger.info(f"Seko 图片下载成功: {output_path}")
            return True
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Seko 图片下载失败 (尝试 {attempt + 1}/{retries}), {wait}s 后重试: {e}")
                _time.sleep(wait)
            else:
                logger.warning(f"Seko 图片下载失败: {type(e).__name__}")
    return False


@app.task(bind=True, name="pipeline_seko_import", soft_time_limit=900)
def seko_import_task(
    self,
    config_path: str,
    proposal_data: dict,
    episode: int = 1,
    import_characters: bool = True,
    import_scenes: bool = True,
    import_storyboard: bool = True,
    download_images: bool = True,
    project_name: str = "",
) -> dict:
    """Seko 策划案导入任务（异步）

    解析 Seko 返回的策划案 JSON，将角色/场景/分镜导入项目，
    并异步下载关联图片。

    project_name: 创建新项目并导入（留空则导入 config_path 指向的项目）。
                  创建失败时自动回滚删除空项目。
    """
    from pipeline.tasks.helpers import _project_scope_from_config

    created_project_dir = None
    if project_name:
        from scripts.project_mgr import create_project
        from infra.config import projects_dir, get_root, invalidate_config_cache
        from rich.console import Console
        _ROOT = get_root()
        proj_dir = projects_dir(_ROOT)
        created_project_dir = proj_dir / project_name
        create_project(project_name, _ROOT, Console())
        from infra.config.paths import ProjectPaths
        config_path = str(ProjectPaths(created_project_dir).project_yaml)
        # 重置缓存（Celery worker 进程内 + DB 项目解析）
        invalidate_config_cache()
        from infra.database._db import _reset_project_cache
        _reset_project_cache()

    try:
        with _project_scope_from_config(config_path):
            ctx = {
                "task": self,
                "paths": _paths(config_path),
                "steps": proposal_data.get("steps", []),
                "elements": proposal_data.get("elements", []),
                "episode": episode,
                "flags": {
                    "characters": import_characters,
                    "scenes": import_scenes,
                    "storyboard": import_storyboard,
                    "images": download_images,
                },
                "result": {"characters": 0, "scenes": 0, "shots": 0,
                           "images_downloaded": 0, "images_failed": 0},
                "chars": [],
                "scenes": [],
            }
            result = _seko_import_inner(ctx)
            if created_project_dir and result.get("status") == STATUS_ERROR:
                import shutil
                shutil.rmtree(str(created_project_dir), ignore_errors=True)
                logger.warning(f"导入失败，已回滚项目 '{project_name}'")
            return result
    except Exception as e:
        if created_project_dir:
            import shutil
            shutil.rmtree(str(created_project_dir), ignore_errors=True)
            logger.warning(f"导入异常，已回滚项目 '{project_name}': {e}")
        raise


def _import_seko_characters(chars: list[dict], paths) -> int:
    """导入 Seko 角色到项目，返回导入数"""
    from infra.models import normalize_character
    from infra.config import save_yaml

    char_dir = paths.characters_dir
    char_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for char in chars:
        cid = char["id"]
        char_yaml = normalize_character({
            "id": cid, "name": char.get("name", ""),
            "appearance": char.get("appearance", ""), "source": "seko"})
        if char.get("seko_image_url"):
            char_yaml["seko_image_url"] = char["seko_image_url"]
        save_yaml(char_dir / f"{cid}.yaml", {"character": char_yaml})
        count += 1
    return count


def _import_seko_scenes(scenes: list[dict], paths) -> int:
    """导入 Seko 场景到项目，返回导入数"""
    from infra.config import save_yaml
    from infra.models import normalize_scene

    scene_dir = paths.scenes_dir
    scene_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for scene in scenes:
        sid = scene["id"]
        scene_yaml = normalize_scene({
            "id": sid, "name": scene.get("name", ""),
            "description": scene.get("description", ""),
            "lighting": "", "reference_images": [], "source": "seko"})
        if scene.get("seko_image_url"):
            scene_yaml["seko_image_url"] = scene["seko_image_url"]
        save_yaml(scene_dir / f"{sid}.yaml", {"scene": scene_yaml})
        count += 1
    return count


def _download_seko_images(elements: list[dict], char_id_map: dict, scene_id_map: dict,
                          paths, task) -> tuple[int, int]:
    """下载 Seko 图片 → (成功数, 失败数)"""

    total = len(elements)
    downloaded, failed = 0, 0
    for idx, elem in enumerate(elements):
        url = elem.get("elementUrl")
        name = (elem.get("elementName") or "").strip()
        elem_type = elem.get("elementType", "")
        if not url or not name:
            continue

        entity_id, img_dir, yaml_path, asset_type, entity_key = _resolve_element(
            elem_type, name, idx, char_id_map, scene_id_map, paths)

        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / "cover.png"

        progress = int(70 + (idx + 1) / total * 25)
        task.update_state(state="PROGRESS", meta={
            "step": "seko_import", "progress": progress,
            "message": f"下载图片 [{idx + 1}/{total}] {name}..."})

        if _download_seko_image(url, str(img_path)):
            downloaded += 1
            if yaml_path and yaml_path.exists():
                try:
                    data = load_yaml_full(yaml_path)
                    entity = data.get(entity_key, {})
                    entity["reference_images"] = [f"/api/assets/{asset_type}/{entity_id}/cover.png"]
                    data[entity_key] = entity
                    from infra.config import save_yaml
                    save_yaml(yaml_path, data)
                except Exception as e:
                    logger.debug(f"更新 YAML reference_images 失败: {e}")
        else:
            failed += 1
    return downloaded, failed


def _seko_import_inner(ctx: dict) -> dict:
    """Seko 导入核心逻辑（在 project_scope 内执行）"""
    task = ctx["task"]
    paths = ctx["paths"]
    steps = ctx["steps"]
    elements = ctx["elements"]
    episode = ctx["episode"]
    flags = ctx["flags"]
    result = ctx["result"]

    # ── 1. 导入角色 ──
    if flags["characters"]:
        task.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 10, "message": "解析角色..."})
        ctx["chars"] = _parse_seko_characters(steps, elements)
        result["characters"] = _import_seko_characters(ctx["chars"], paths)

    # ── 2. 导入场景 ──
    if flags["scenes"]:
        task.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 30, "message": "解析场景..."})
        ctx["scenes"] = _parse_seko_scenes(steps, elements)
        result["scenes"] = _import_seko_scenes(ctx["scenes"], paths)

    # ── 3. 导入分镜 ──
    char_id_map = {c["name"]: c["id"] for c in ctx.get("chars", [])}
    scene_id_map = {s["name"]: s["id"] for s in ctx.get("scenes", [])}

    if flags["storyboard"]:
        task.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 50, "message": "解析分镜..."})
        shots = _parse_seko_storyboard(steps, episode)
        if shots:
            from engines.utils.shot import postprocess_shots
            shots = postprocess_shots(shots, episode)
            for shot in shots:
                chars_field = shot.get("characters", "")
                if chars_field:
                    # 分镜 characters 存名称（不替换为 hash ID）
                    pass
                scene_field = shot.get("scene_name", "")
                # 分镜 scene_name 存名称（不替换为 hash ID）
            from engines.content.storyboard import save_storyboard
            save_storyboard(shots, episode)
            result["shots"] = len(shots)

    # ── 4. 下载图片 ──
    if flags["images"] and elements:
        task.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 70, "message": "下载图片..."})
        result["images_downloaded"], result["images_failed"] = _download_seko_images(
            elements, char_id_map, scene_id_map, paths, task)

    task.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 100, "message": "导入完成"})
    return {"status": STATUS_DONE, **result}


def _resolve_element(elem_type: str, name: str, idx: int,
                     char_id_map: dict, scene_id_map: dict, paths) -> tuple:
    """解析 element 类型，返回 (entity_id, img_dir, yaml_path, asset_type, entity_key)"""
    if elem_type == "CHARACTER":
        entity_id = char_id_map.get(name)
        if not entity_id:
            from infra.config import load_yaml_entities
            for c in load_yaml_entities(paths.characters_dir, "character"):
                if c.get("name") == name:
                    entity_id = c["id"]
                    break
        if not entity_id:
            entity_id = name_to_safe_id(name, f"char_{idx + 1:02d}")
        return (entity_id, paths.character_asset_dir(entity_id),
                paths.character_yaml(entity_id), "characters", "character")

    if elem_type == "SCENE":
        entity_id = scene_id_map.get(name)
        if not entity_id:
            from infra.config import load_yaml_entities
            for s in load_yaml_entities(paths.scenes_dir, "scene"):
                if s.get("name") == name:
                    entity_id = s["id"]
                    break
        if not entity_id:
            entity_id = name_to_safe_id(name, f"scene_{idx + 1:02d}")
        return (entity_id, paths.scene_asset_dir(entity_id),
                paths.scene_yaml(entity_id), "scenes", "scene")

    return (f"elem_{idx}", paths.assets_dir / "seko" / f"elem_{idx}", None, "seko", "")
