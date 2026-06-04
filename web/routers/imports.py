"""API 路由 — 项目管理 / 导入 / Seko / 训练"""
from __future__ import annotations
from infra.config import load_yaml_full

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from web.routers.deps import (
    ROOT, _merged_cfg, _cfg_path, _paths, _check_id, _submit_task, _reset_proj_cache,
)

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import (
    ProjectCreate, ProjectSwitch,
    SekoProposalRequest, SekoProposalStatusRequest, SekoProposalModifyRequest,
    SekoImportRequest,
    TrainingRequest,
    ImportPromptParams,
)


# ══════════════════════════════════════════════════════════
# 项目管理
# ══════════════════════════════════════════════════════════

@router.get("/projects")
def list_projects() -> dict:
    proj_dir = _paths().projects_dir
    proj_dir.mkdir(exist_ok=True)
    active_file = proj_dir / ".active"
    active_path = active_file.read_text().strip() if active_file.exists() else None
    if not active_path:
        active_path = str(proj_dir / "default")
    result = []
    for d in sorted(proj_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        from infra.config import ProjectPaths
        dp = ProjectPaths(d)
        cfg = dp.project_yaml
        if cfg.exists():
            data = load_yaml_full(cfg)
            name = data.get("project", {}).get("name", d.name)
        else:
            name = d.name
        result.append({"name": name, "path": str(d), "active": active_path == str(d), "isDefault": d.name == "default"})
    default_name = "默认"
    default_cfg = ProjectPaths(proj_dir / "default").project_yaml
    if default_cfg.exists():
        data = load_yaml_full(default_cfg)
        default_name = data.get("project", {}).get("name", "默认")
    return {"projects": result, "defaultName": default_name}


@router.post("/projects/new")
def create_project(req: ProjectCreate) -> dict:
    from scripts.project_mgr import create_project
    from rich.console import Console
    create_project(req.name, ROOT, Console(), style=req.style, genre=req.genre)
    _reset_proj_cache()
    return {"status": "ok", "name": req.name, "style": req.style, "genre": req.genre}


@router.get("/projects/presets")
def get_project_presets() -> dict:
    from scripts.project_mgr import get_presets
    styles, genres = get_presets()
    return {"styles": styles, "genres": genres}


@router.post("/projects/switch")
def switch_project(req: ProjectSwitch) -> dict:
    from scripts.project_mgr import switch_project
    from rich.console import Console
    proj_dir = _paths().projects_dir
    project_dir = proj_dir / req.name
    if project_dir.exists() and project_dir.is_dir():
        switch_project(req.name, ROOT, Console())
        _reset_proj_cache()
        return {"status": "ok"}
    for d in proj_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        from infra.config import ProjectPaths
        cfg = ProjectPaths(d).project_yaml
        if cfg.exists():
            data = load_yaml_full(cfg)
            if req.name == data.get("project", {}).get("name", ""):
                switch_project(d.name, ROOT, Console())
                _reset_proj_cache()
                return {"status": "ok"}
    raise HTTPException(404, f"项目 '{req.name}' 不存在")


@router.delete("/projects/{name}")
def delete_project(name: str) -> dict:
    if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef]+$", name):
        raise HTTPException(400, "无效的项目名")
    if name == "default":
        raise HTTPException(400, "不能删除默认项目")
    from scripts.project_mgr import delete_project
    from rich.console import Console
    try:
        delete_project(name, ROOT, Console())
    except Exception as e:
        raise HTTPException(400, str(e))
    _reset_proj_cache()
    return {"status": "ok", "name": name}


# ══════════════════════════════════════════════════════════
# Seko 影视策划案
# ══════════════════════════════════════════════════════════

@router.post("/seko/proposal")
def seko_generate_proposal(req: SekoProposalRequest) -> dict:
    from api.backends.seko.proposal import generate_proposal
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})
    result = generate_proposal(req.prompt, api_key=req.api_key, config=seko_cfg)
    if result.get("code") == 200:
        data = result.get("data", {})
        return {"status": "submitted", "task_id": data.get("taskId"), "raw": result}
    raise HTTPException(502, result.get("msg", "策划案生成失败"))


@router.post("/seko/proposal/status")
def seko_proposal_status(req: SekoProposalStatusRequest) -> dict:
    from api.backends.seko.proposal import (
        check_proposal_status, wait_for_proposal, download_elements_images,
    )
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})
    if req.wait:
        result = wait_for_proposal(req.task_id, api_key=req.api_key, config=seko_cfg, interval=req.interval)
    else:
        result = check_proposal_status(req.task_id, api_key=req.api_key, config=seko_cfg)
    downloaded = []
    if req.download_dir and result.get("code") == 200:
        data = result.get("data", {})
        if data.get("taskStatus") == "OK":
            _check_id(req.task_id, "task_id")
            if req.download_dir == "__project_assets__":
                download_dir = str(_paths().seko_asset_dir(req.task_id))
            else:
                if ".." in req.download_dir.split("/"):
                    raise HTTPException(400, "非法下载目录")
                download_dir = os.path.join(req.download_dir, req.task_id)
            downloaded = download_elements_images(data, download_dir)
    return {
        "status": result.get("data", {}).get("taskStatus", "UNKNOWN"),
        "task_id": req.task_id,
        "downloaded": downloaded,
        "raw": result,
    }


@router.post("/seko/proposal/modify")
def seko_modify_proposal(req: SekoProposalModifyRequest) -> dict:
    from api.backends.seko.proposal import modify_proposal
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})
    result = modify_proposal(req.task_id, req.prompt, api_key=req.api_key, config=seko_cfg)
    if result.get("code") == 200:
        data = result.get("data", {})
        return {"status": "submitted", "task_id": data.get("taskId"), "raw": result}
    raise HTTPException(502, result.get("msg", "策划案修改失败"))


@router.post("/seko/proposal/import")
def seko_import_proposal(req: SekoImportRequest) -> dict:
    from pipeline.tasks import seko_import_task
    from scripts.project_mgr import create_project
    from rich.console import Console
    proj_dir = _paths().projects_dir
    if req.project_name:
        project_dir = proj_dir / req.project_name
        if project_dir.exists():
            raise HTTPException(409, f"项目 '{req.project_name}' 已存在")
        create_project(req.project_name, ROOT, Console())
        _reset_proj_cache()
    cfg = _cfg_path()
    try:
        return _submit_task(
            seko_import_task, cfg,
            req.proposal_data, req.episode,
            req.import_characters, req.import_scenes,
            req.import_storyboard, req.download_images,
        )
    except Exception as e:
        if req.project_name:
            import shutil
            shutil.rmtree(str(proj_dir / req.project_name), ignore_errors=True)
            _reset_proj_cache()
            logger.warning(f"导入任务提交失败，已回滚项目 '{req.project_name}'")
        raise HTTPException(503, f"任务提交失败: {e}")


# ══════════════════════════════════════════════════════════
# LoRA 训练
# ══════════════════════════════════════════════════════════

@router.post("/training/lora")
def train_lora(req: TrainingRequest) -> dict:
    _check_id(req.char_id, "角色 ID")
    char_yaml_path = _paths().character_yaml(req.char_id)
    if not char_yaml_path.exists():
        raise HTTPException(404, f"角色 {req.char_id} 不存在")
    cfg = _cfg_path()
    from pipeline.tasks import train_lora_task
    return _submit_task(train_lora_task, cfg, req.char_id,
                        trigger_word=req.trigger_word, steps=req.steps,
                        learning_rate=req.learning_rate, rank=req.rank,
                        resolution=req.resolution, force=req.force)


@router.get("/training/status/{char_id}")
def training_status(char_id: str) -> dict:
    _check_id(char_id, "角色 ID")
    p = _paths()
    project = str(p.root)
    from infra.asset_tracker import comfyui_asset_name
    lora_dir = p.loras_dir
    lora_name = comfyui_asset_name(project, char_id, f"{char_id}_lora.safetensors")
    candidates = [
        lora_dir / lora_name,
        lora_dir / f"{char_id}_lora.safetensors",
        lora_dir / f"{char_id}.safetensors",
    ]
    lora_path = None
    for c in candidates:
        if c.exists():
            lora_path = c
            break
    char_yaml = p.character_yaml(char_id)
    has_lora = lora_path is not None
    lora_size = lora_path.stat().st_size if has_lora else 0
    lora_path_in_yaml = ""
    if char_yaml.exists():
        try:
            data = load_yaml_full(char_yaml)
            lora_path_in_yaml = data.get("character", {}).get("lora_path", "")
        except Exception as e:
            logger.debug(f"{type(e).__name__}: {e}")
    return {
        "char_id": char_id, "has_lora": has_lora, "lora_size": lora_size,
        "lora_path": str(lora_path) if has_lora else "",
        "lora_path_in_yaml": lora_path_in_yaml,
    }


# ══════════════════════════════════════════════════════════
# 导入提示词模板
# ══════════════════════════════════════════════════════════

def _load_prompt_presets() -> dict:
    """加载系统预设（shot_types/cameras/emotions/style_desc/genre_desc）"""
    from infra.config import SYSTEM_CONFIG_PATH
    presets = {"style_desc": "", "genre_desc": "", "shot_types_str": "", "cameras_str": "", "emotions_str": ""}
    sys_path = Path(SYSTEM_CONFIG_PATH)
    if not sys_path.exists():
        return presets
    sys_cfg = load_yaml_full(sys_path)
    p = sys_cfg.get("presets", {})
    presets["shot_types_str"] = "、".join(p.get("shot_types", {}).keys()) or ""
    presets["cameras_str"] = "、".join(p.get("cameras", {}).keys()) or ""
    presets["emotions_str"] = "、".join(p.get("emotions", {}).keys()) or ""
    return presets


def _build_prompt_replacements(params, style_desc: str, genre_desc: str,
                               presets: dict, last_shot_info: str, episodes_summary: str) -> dict:
    """构建模板替换字典"""
    batch_size = params.shot_end - params.shot_start + 1
    return {
        "project_name": params.project_name,
        "episode": str(params.episode),
        "style": params.style, "style_desc": style_desc,
        "genre": params.genre, "genre_desc": genre_desc,
        "duration": str(params.duration), "batch_size": str(batch_size),
        "shot_start": f"{params.shot_start:03d}", "shot_end": f"{params.shot_end:03d}",
        "last_shot_info": last_shot_info or "（无，请从 001 开始）",
        "shot_types": presets.get("shot_types_str") or "（未配置）",
        "cameras": presets.get("cameras_str") or "（未配置）",
        "emotions": presets.get("emotions_str") or "（未配置）",
        "episodes_summary": episodes_summary or "（尚未分析，请先运行角色+场景提取）",
        "script_content": "${script_content}",
    }


@router.get("/import/prompt-template")
def get_import_prompt_template(params: ImportPromptParams = Depends()):
    template_id = params.template_id
    if not template_id:
        template_id = "import_prompt_setup" if (params.mode == "setup" or params.shot_start <= 1) else "import_prompt_shots"

    from infra.config import PROMPT_TEMPLATES_PATH
    tpl_path = Path(PROMPT_TEMPLATES_PATH)
    if not tpl_path.exists():
        raise HTTPException(500, "提示词模板文件不存在: config/prompt_templates.yaml")
    tpl_data = load_yaml_full(tpl_path)
    tpl = tpl_data.get(template_id)
    if not tpl:
        raise HTTPException(404, f"模板 '{template_id}' 不存在，可用: {list(tpl_data.keys())}")

    presets = _load_prompt_presets()
    style_desc = params.style
    genre_desc = params.genre
    if presets.get("style_desc"):
        style_desc = presets["style_desc"]
    if presets.get("genre_desc"):
        genre_desc = presets["genre_desc"]

    last_shot_info = params.last_shot_info
    if not last_shot_info and params.shot_start > 1:
        last_shot_info = _get_last_shot_info(params.episode)

    episodes_summary = _get_episodes_summary()
    replacements = _build_prompt_replacements(params, style_desc, genre_desc, presets, last_shot_info, episodes_summary)

    prompt = tpl.get("template", "")
    # 单次替换：用 re.sub 一次性替换所有 ${key}，避免二次替换
    import re as _re
    def _replace_var(m):
        var_name = m.group(1)
        return replacements.get(var_name, m.group(0))
    prompt = _re.sub(r'\$\{(\w+)\}', _replace_var, prompt)

    project_stats = _get_project_stats()
    return {
        "prompt": prompt.strip(), "template_id": template_id,
        "shot_start": params.shot_start, "shot_end": params.shot_end,
        "project_stats": project_stats, "episodes_summary": episodes_summary,
        "meta": {
            "project_name": params.project_name, "episode": params.episode,
            "style": params.style, "style_desc": style_desc,
            "genre": params.genre, "genre_desc": genre_desc, "duration": params.duration,
        },
    }


def _get_project_stats() -> dict:
    try:
        from infra.database.storyboard_db import get_episodes_summary
        from infra.database.pool import get_pool
        rows = get_episodes_summary(get_pool())
        episodes = [{"episode": r["episode"], "shot_count": r["shots"]} for r in rows]
        total = sum(r["shots"] for r in rows)
        return {"episodes": episodes, "total_shots": total}
    except Exception:
        return {"episodes": [], "total_shots": 0}


def _get_episodes_summary() -> str:
    try:
        from infra.config import get_active_project_dir, ProjectPaths, load_config
        proj_dir = get_active_project_dir(ROOT)
        paths = ProjectPaths(proj_dir)
        if not paths.project_yaml.exists():
            return ""
        cfg = load_config(str(paths.project_yaml))
        return cfg.get("project", {}).get("episodes_summary", "")
    except Exception:
        return ""


def _get_last_shot_info(episode: int = 1) -> str:
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_episode_shots
        shots = get_episode_shots(get_pool(), episode)
        if not shots:
            return ""
        last = shots[-1]
        parts = [f"shot_id: {last.get('shot_id', '?')}"]
        if last.get("scene_id"):
            parts.append(f"scene: {last['scene_id']}")
        if last.get("characters"):
            parts.append(f"characters: {last['characters']}")
        if last.get("action"):
            action = last["action"]
            parts.append(f"action: {action[:80]}{'...' if len(action) > 80 else ''}")
        if last.get("dialogue") and last.get("dialogue") != "......":
            parts.append(f"dialogue: {last['dialogue'][:50]}")
        if last.get("emotion"):
            parts.append(f"emotion: {last['emotion']}")
        return " | ".join(parts)
    except Exception:
        return ""


@router.get("/import/prompt-templates")
def list_import_prompt_templates() -> dict:
    from infra.config import PROMPT_TEMPLATES_PATH
    tpl_path = Path(PROMPT_TEMPLATES_PATH)
    if not tpl_path.exists():
        return {"templates": []}
    data = load_yaml_full(tpl_path)
    return {
        "templates": [
            {"id": key, "name": val.get("name", key), "description": val.get("description", "")}
            for key, val in data.items()
            if isinstance(val, dict) and "template" in val
        ]
    }


@router.post("/import/json")
def import_json(plan_data: dict = Body(..., description="ImportPlan JSON")):
    from pipeline.tasks import import_json_task
    try:
        return _submit_task(import_json_task, plan_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"任务提交失败: {e}")
