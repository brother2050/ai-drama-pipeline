"""CLI 导入/导出命令 — import / export"""
from __future__ import annotations

import logging
import sys

import click
from rich.console import Console

from infra.constants import STATUS_DONE, STATUS_ERROR

console = Console()
logger = logging.getLogger("cli")


def register_io_commands(cli):
    """注册 import / export 命令到主 CLI 组"""

    @cli.command("import")
    @click.argument("file", type=click.Path(exists=True))
    @click.option("--name", default=None, help="项目名（覆盖 JSON 中的 project_name）")
    @click.option("--append", "-a", is_flag=True, help="追加模式：向已有项目追加 shots（不覆盖已有数据）")
    def import_json(file, name, append):
        """📥 从 JSON 导入剧本项目

        支持两种模式：
        \b
        全量导入（默认）：首次导入，创建新项目
          drama import plan.json

        追加导入：向已有项目追加分镜（解决 LLM 输出截断问题）
          drama import batch2.json --append
        """
        from cli import _ensure_deps, _run_via_celery
        _ensure_deps()
        import json as _json
        from pathlib import Path as _Path

        p = _Path(file)
        if p.suffix.lower() != ".json":
            console.print("[red]❌ 只支持 .json 文件[/red]")
            sys.exit(1)

        try:
            with open(p, encoding="utf-8") as f:
                data = _json.load(f)
        except _json.JSONDecodeError as e:
            console.print(f"[red]❌ JSON 格式错误: {e}[/red]")
            sys.exit(1)

        if not isinstance(data, dict):
            console.print("[red]❌ JSON 顶层必须是对象[/red]")
            sys.exit(1)

        if name:
            data["project_name"] = name
        if not data.get("project_name"):
            console.print("[red]❌ JSON 中缺少 project_name 字段[/red]")
            sys.exit(1)
        if append:
            data["append"] = True

        mode_label = "追加导入" if append else "导入剧本项目"
        console.print(f"\n[bold cyan]📥 {mode_label}[/bold cyan]\n")
        console.print(f"  项目名: {data.get('project_name', '?')}")
        if data.get('characters'):
            console.print(f"  角色:   {len(data.get('characters', []))} 个")
        if data.get('scenes'):
            console.print(f"  场景:   {len(data.get('scenes', []))} 个")
        console.print(f"  分镜:   {len(data.get('shots', []))} 个")
        if append:
            console.print("  模式:   [yellow]追加（不覆盖已有数据）[/yellow]")
        console.print()

        if not _run_via_celery("pipeline_import_json", data, result_handler=_handle_import_result):
            sys.exit(1)

    @cli.command("export")
    @click.argument("episode", type=int, default=1)
    @click.option("-o", "--output", default=None, help="输出 CSV 文件路径")
    def export_csv(episode, output):
        """📤 导出分镜到 CSV 文件"""
        from cli import _load_env
        _load_env()
        from infra.database.storyboard_db import export_to_csv, get_episode_shots
        from infra.database.pool import get_pool
        from infra.config import get_active_project_dir

        try:
            get_active_project_dir()
        except Exception:
            console.print("[red]❌ 未找到活动项目[/red]")
            return

        shots = get_episode_shots(get_pool(), episode)
        if not shots:
            console.print(f"[yellow]第{episode}集没有镜头[/yellow]")
            return

        if not output:
            from infra.config import ProjectPaths
            from cli import ROOT
            output = str(ProjectPaths(get_active_project_dir(ROOT)).episode_dir(episode) / f"episode_{episode:02d}.csv")

        from pathlib import Path
        out_path = Path(output)
        count = export_to_csv(get_pool(), episode, out_path)
        console.print(f"[green]✅ 导出 {count} 个镜头到 {out_path}[/green]")


def _handle_import_result(result) -> bool:
    """导入任务的结果处理回调。返回 True 表示已处理。"""
    if isinstance(result, dict) and result.get("status") == STATUS_DONE:
        mode = result.get("mode", "full")
        if mode == "append":
            console.print("\n[bold green]✅ 追加导入成功！[/bold green]")
            console.print(f"  项目: {result.get('project_name', '?')}")
            added_c = result.get("added_characters", 0)
            added_s = result.get("added_scenes", 0)
            added_sh = result.get("added_shots", 0)
            if added_c:
                console.print(f"  新增角色: {added_c} 个")
            if added_s:
                console.print(f"  新增场景: {added_s} 个")
            console.print(f"  追加分镜: {added_sh} 个")
        else:
            console.print("\n[bold green]✅ 导入成功！[/bold green]")
            console.print(f"  项目: {result.get('project_name', '?')}")
            console.print(f"  角色: {result.get('characters', 0)} 个")
            console.print(f"  场景: {result.get('scenes', 0)} 个")
            console.print(f"  分镜: {result.get('shots', 0)} 个")
            console.print(f"  路径: {result.get('project_dir', '?')}")
        translation = result.get("translation", {})
        if translation:
            if translation.get("complete"):
                console.print("  翻译: [green]✅ 完整 — 可直接进入生产管线[/green]")
            else:
                console.print(f"  翻译: [yellow]⚠ {translation['summary']}[/yellow]")
                console.print("         在 Web 工作台执行「🔧 准备阶段」补全后可进入生产管线")
        return True
    if isinstance(result, dict) and result.get("status") == STATUS_ERROR:
        console.print(f"\n[red]❌ {result.get('reason', '导入失败')}[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]• {err}[/red]")
        return True
    return False
