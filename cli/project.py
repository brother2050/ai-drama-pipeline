"""CLI 项目管理命令 — project 组（list / new / switch / current / delete）"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()
logger = logging.getLogger("cli")

from infra.config import SYSTEM_CONFIG_PATH, load_yaml_full


def register_project_commands(cli):
    """注册 project 命令组到主 CLI 组"""

    @cli.group()
    def project() -> None:
        """项目管理"""
        pass

    @project.command("list")
    def project_list() -> None:
        from scripts.project_mgr import list_projects
        list_projects(console)

    @project.command("new")
    @click.argument("name")
    @click.option("--style", default="cinematic",
                  help="视觉风格（如 cinematic/anime/realistic 等，--list-presets 查看全部）")
    @click.option("--genre", default="urban",
                  help="题材类型（如 urban/romance/suspense 等，--list-presets 查看全部）")
    @click.option("--list-presets", is_flag=True, help="列出所有可用的 style 和 genre 预设")
    def project_new(name, style, genre, list_presets):
        if list_presets:
            sys_path = Path(SYSTEM_CONFIG_PATH)
            if sys_path.exists():
                data = load_yaml_full(sys_path)
                presets = data.get("presets", {})
                console.print("\n[bold cyan]🎨 视觉风格 (--style)[/bold cyan]")
                for k, v in presets.get("styles", {}).items():
                    console.print(f"  [green]{k:20s}[/green] {v}")
                console.print(f"\n[bold cyan]🎭 题材类型 (--genre)[/bold cyan]")
                for k, v in presets.get("genres", {}).items():
                    console.print(f"  [green]{k:20s}[/green] {v}")
            else:
                console.print("[red]❌ config/system.yaml 不存在[/red]")
            return
        from cli import ROOT
        from scripts.project_mgr import create_project
        create_project(name, ROOT, console, style=style, genre=genre)

    @project.command("switch")
    @click.argument("name")
    def project_switch(name):
        from cli import ROOT
        from scripts.project_mgr import switch_project
        switch_project(name, ROOT, console)

    @project.command("current")
    def project_current() -> None:
        from cli import ROOT
        from scripts.project_mgr import show_current
        show_current(ROOT, console)

    @project.command("delete")
    @click.argument("name")
    def project_delete(name):
        from infra.config import projects_dir
        proj_dir = projects_dir() / name
        if not proj_dir.exists():
            console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
            return
        shot_count = 0
        try:
            from infra.database.pool import get_pool
            from infra.database.storyboard_db import get_episodes_summary
            rows = get_episodes_summary(get_pool())
            shot_count = sum(r["shots"] for r in rows)
        except Exception:
            logger.debug("获取集统计失败")
        from infra.config import ProjectPaths
        chars_dir = ProjectPaths(proj_dir).characters_dir
        char_count = len(list(chars_dir.glob("*.yaml"))) if chars_dir.exists() else 0
        if not click.confirm(f"确认删除项目 '{name}'（{shot_count} 个镜头, {char_count} 个角色）？"):
            return
        from cli import ROOT
        from scripts.project_mgr import delete_project
        delete_project(name, ROOT, console)
