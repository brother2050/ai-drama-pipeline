"""项目管理 — 纯 Python

所有项目（含默认）统一存放在 projects/ 下。
每个项目完全独立：自己的角色、场景、剧本、配置。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "default"

# ── 风格/题材预设（从 system.yaml 的 presets 段读取） ──
# 默认值仅用于 system.yaml 缺失时的兜底，正常情况下不应触发


def get_presets() -> tuple[dict, dict]:
    """获取风格/题材预设（从 system.yaml 的 presets 段读取）"""
    from infra.config import load_config, SYSTEM_CONFIG_PATH
    sys_cfg = load_config(SYSTEM_CONFIG_PATH)
    presets = sys_cfg.get("presets", {})
    styles = presets.get("styles", {})
    genres = presets.get("genres", {})
    return styles, genres


# 默认项目配置模板
_DEFAULT_PROJECT_YAML = """\
# AI 短剧管线 v2 — 项目配置
# 系统级配置（ComfyUI、TTS、LLM 等）请编辑 config/system.yaml

project:
  name: "{name}"
  episodes: 1
  fps: 24
  resolution: [1280, 720]
  style: "{style}"
  genre: "{genre}"

# 定妆照配置
# portraits:
#   auto_outfit: false  # 管线自动生成 outfit 参考图（默认 true，设为 false 仅生成主图）

# 项目级覆盖（可选，取消注释可覆盖系统配置）
# comfyui:
#   url: "http://192.168.1.100:8188"
# llm:
#   enabled: true
"""

from infra.config import get_root as _get_root, projects_dir as _projects_dir, load_yaml_full  # noqa: E402

_ROOT = _get_root()


def _ensure_project_dirs(project_dir: Path) -> None:
    """确保项目具备完整的目录结构"""
    from infra.config import ProjectPaths
    ProjectPaths(project_dir).ensure_dirs()


def _scaffold_default_config(project_dir: Path, name: str, style: str = "cinematic", genre: str = "urban") -> None:
    """为新项目生成默认配置文件（已存在时仅更新项目名称和风格）"""
    from infra.config import ProjectPaths, save_yaml
    paths = ProjectPaths(project_dir)

    # project.yaml — 始终确保名称和风格正确
    cfg_path = paths.project_yaml
    if cfg_path.exists():
        # 已有配置：只更新项目名称和风格，不覆盖其他自定义内容
        data = load_yaml_full(cfg_path)
        data.setdefault("project", {})["name"] = name
        data["project"]["style"] = style
        data["project"]["genre"] = genre
        save_yaml(cfg_path, data)
    else:
        # 无配置：从模板生成
        cfg_path.write_text(
            _DEFAULT_PROJECT_YAML.format(name=name, style=style, genre=genre),
            encoding="utf-8",
        )


def _seed_default_characters(project_dir: Path) -> None:
    """写入默认角色和场景配置"""
    from infra.config import ProjectPaths, save_yaml
    from config.default_storyboard import DEFAULT_CHARACTERS, DEFAULT_SCENES
    from infra.models import normalize_character, normalize_scene
    paths = ProjectPaths(project_dir)

    char_dir = paths.characters_dir
    char_dir.mkdir(parents=True, exist_ok=True)
    for char in DEFAULT_CHARACTERS:
        path = char_dir / f"{char['id']}.yaml"
        if not path.exists():
            save_yaml(path, {"character": normalize_character(char)})

    scene_dir = paths.scenes_dir
    scene_dir.mkdir(parents=True, exist_ok=True)
    for scene in DEFAULT_SCENES:
        path = scene_dir / f"{scene['id']}.yaml"
        if not path.exists():
            save_yaml(path, {"scene": normalize_scene(scene)})


def _seed_default_storyboard() -> None:
    """将默认分镜写入 DB（仅当 DB 为空时）"""
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_all_episodes, save_episode_shots
        from infra.database._db import project_scope
        from config.default_storyboard import DEFAULT_SHOTS
        pool = get_pool()
        if get_all_episodes(pool):
            return
        # 显式绑定项目作用域，避免 .active 竞态
        with project_scope(DEFAULT_PROJECT):
            save_episode_shots(pool, 1, DEFAULT_SHOTS)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"默认分镜种子跳过: {e}")



def list_projects(console):
    from infra.config import get_active_project_dir
    proj_dir = _projects_dir()
    proj_dir.mkdir(exist_ok=True)
    active = get_active_project_dir(_ROOT)

    from rich.table import Table
    t = Table(title="📂 项目列表")
    t.add_column("", width=3)
    t.add_column("名称", style="cyan")
    t.add_column("路径")
    t.add_column("角色数", justify="center")
    t.add_column("分镜数", justify="center")
    t.add_column("状态")

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

        # 统计角色数
        chars_dir = dp.characters_dir
        char_count = len(list(chars_dir.glob("*.yaml"))) if chars_dir.exists() else 0

        # 统计分镜数
        sb_count = 0
        try:
            from infra.database.pool import get_pool
            from infra.database.storyboard_db import get_episodes_summary
            rows = get_episodes_summary(get_pool())
            sb_count = sum(r["shots"] for r in rows)
        except Exception as e:
            logger.debug(f"获取集统计失败: {e}")
        is_active = d.resolve() == active.resolve()
        t.add_row(
            "→" if is_active else "",
            name, str(d),
            str(char_count), str(sb_count),
            "[green]当前[/green]" if is_active else "",
        )

    console.print(t)


def create_project(name: str, root: Path, console, style: str = "cinematic", genre: str = "urban"):
    """创建新项目 — 目录结构 + 项目配置 + 默认分镜"""
    proj_dir = _projects_dir()
    proj_dir.mkdir(exist_ok=True)
    project_dir = proj_dir / name
    if project_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 已存在[/red]")
        return

    # 1. 创建完整目录结构
    _ensure_project_dirs(project_dir)

    # 2. 生成项目配置
    _scaffold_default_config(project_dir, name, style=style, genre=genre)

    # 3. 仅默认项目写入示例角色/场景（新项目从空白开始）
    if name == DEFAULT_PROJECT:
        _seed_default_characters(project_dir)

    # 4. 写入默认分镜到 DB（仅默认项目 + DB 为空时）
    if name == DEFAULT_PROJECT:
        _seed_default_storyboard()

    # 5. 设置为活动项目
    (proj_dir / ".active").write_text(str(project_dir), encoding="utf-8")
    from infra.database._db import _reset_project_cache
    _reset_project_cache()

    console.print(f"[green]✅ 项目 '{name}' 已创建并设为当前[/green]")
    console.print(f"[dim]  路径: {project_dir}[/dim]")
    console.print(f"[dim]  风格: {style} | 题材: {genre}[/dim]")
    if name == DEFAULT_PROJECT:
        from config.default_storyboard import DEFAULT_CHARACTERS, DEFAULT_SCENES, DEFAULT_SHOTS
        console.print(f"[dim]  已生成: {len(DEFAULT_CHARACTERS)} 角色 + {len(DEFAULT_SCENES)} 场景 + {len(DEFAULT_SHOTS)} 分镜[/dim]")
    console.print("[dim]  下一步: drama serve 启动工作台[/dim]")


def switch_project(name: str, root: Path, console):
    proj_dir = _projects_dir()
    d = proj_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    # 确保目标项目目录完整
    _ensure_project_dirs(d)
    _scaffold_default_config(d, name)

    (proj_dir / ".active").write_text(str(d), encoding="utf-8")
    from infra.database._db import _reset_project_cache
    _reset_project_cache()
    console.print(f"[green]✅ 已切换到: {name}[/green]")

    # 显示项目概要
    from infra.config import ProjectPaths
    dp = ProjectPaths(d)
    cfg = dp.project_yaml
    if cfg.exists():
        data = load_yaml_full(cfg)
        proj = data.get("project", {})
        style = proj.get('style', 'cinematic')
        genre = proj.get('genre', 'urban')
        console.print(f"[dim]  集数: {proj.get('episodes', 1)}, 分辨率: {proj.get('resolution', [1280, 720])}[/dim]")
        console.print(f"[dim]  风格: {style}, 题材: {genre}[/dim]")

    chars_dir = dp.characters_dir
    if chars_dir.exists():
        chars = [f.stem for f in chars_dir.glob("*.yaml") if not f.stem.endswith(".example")]
        if chars:
            console.print(f"[dim]  角色: {', '.join(chars)}[/dim]")


def delete_project(name: str, root: Path, console):
    if name == DEFAULT_PROJECT:
        console.print("[red]❌ 不能删除默认项目[/red]")
        return
    proj_dir = _projects_dir()
    d = proj_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    from infra.config import get_active_project_dir
    active = get_active_project_dir(root)
    if active.resolve() == d.resolve():
        (proj_dir / ".active").write_text(str(proj_dir / DEFAULT_PROJECT), encoding="utf-8")
        from infra.database._db import _reset_project_cache
        _reset_project_cache()

    # 清理数据库中属于该项目的记录（避免孤立数据干扰重建同名项目）
    _cleanup_project_db(d)

    shutil.rmtree(d, ignore_errors=True)
    console.print(f"[green]✅ 项目 '{name}' 已删除[/green]")


def _cleanup_project_db(project_dir: Path) -> None:
    """清理数据库中属于该项目的所有记录（目录删除前调用）"""
    try:
        from infra.database.pool import get_pool
        pool = get_pool()
    except Exception as e:
        logger.debug(f"数据库连接池不可用，跳过清理: {e}")
        return

    proj_name = project_dir.name
    proj_str = str(project_dir)

    try:
        from infra.database._db import project_scope
        from infra.database.comfyui_assets import delete_by_project as _del_assets

        # comfyui_assets（按 project 名称匹配）
        _del_assets(pool, proj_name)
        logger.info(f"  清理 comfyui_assets: {proj_str}")

        with project_scope(proj_name):
            # 1. 直接按 project 删除所有 DB 记录（不依赖 YAML 文件）
            _delete_by_project_name(pool, proj_name)

    except Exception as e:
        logger.warning(f"数据库清理失败: {e}")


def _delete_by_project_name(pool, project: str) -> None:
    """按 project 名直接删除所有 DB 表记录（不依赖 YAML 文件）"""
    from infra.database._db import query

    _VALID_TABLES = {"generation_status", "shots"}
    tables_and_key = [
        ("generation_status", "project"),
        ("shots", "project"),
    ]

    for table, key_col in tables_and_key:
        if table not in _VALID_TABLES:
            logger.warning(f"  跳过未白名单的表: {table}")
            continue
        try:
            with query(pool) as cur:
                cur.execute(f"DELETE FROM {table} WHERE {key_col} = %s", (project,))
                count = cur.rowcount
                if count > 0:
                    logger.info(f"  清理 {table}: {count} 条记录")
        except Exception as e:
            logger.debug(f"  清理 {table} 跳过: {e}")
