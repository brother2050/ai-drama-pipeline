"""CLI 管线命令 — preview / prepare / produce / post / all / portraits"""
from __future__ import annotations

import sys

import click
from rich.console import Console

console = Console()


def register_pipeline_commands(cli):
    """注册管线命令到主 CLI 组"""

    @cli.command()
    @click.argument("episode", type=int, default=1)
    @click.argument("level", type=click.Choice(["draft", "standard", "high"]), default="draft")
    @click.option("-c", "--config", "config_path", default=None)
    @click.option("--force", is_flag=True, help="强制覆盖已有文件")
    def preview(episode, level, config_path, force):
        """快速预览（通过 Celery 异步执行）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level})[/bold cyan]\n")
        if not _run_via_celery("pipeline_preview", cfg, episode, level, force=force):
            sys.exit(1)

    @cli.command()
    @click.argument("episode", type=int, default=1)
    @click.option("-c", "--config", "config_path", default=None)
    @click.option("--force", is_flag=True, help="强制覆盖已有翻译")
    @click.option("--no-translate", is_flag=True, help="跳过翻译")
    def prepare(episode, config_path, force, no_translate):
        """准备阶段 — 批量预翻译（生产前运行一次）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]🔧 准备阶段 第{episode}集[/bold cyan]\n")
        if not _run_via_celery("pipeline_ai_prepare", cfg, episode,
                               force=force, translate=not no_translate):
            sys.exit(1)

    @cli.command()
    @click.argument("episode", type=int)
    @click.option("--vertical", is_flag=True, help="横转竖")
    @click.option("-c", "--config", "config_path", default=None)
    @click.option("--force", is_flag=True, help="强制覆盖已有文件")
    def produce(episode, vertical, config_path, force):
        """完整生产（通过 Celery 异步执行）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]🎬 生产 第{episode}集[/bold cyan]\n")
        if not _run_via_celery("pipeline_produce", cfg, episode, vertical=vertical, force=force):
            sys.exit(1)

    @cli.command()
    @click.argument("episode", type=int)
    @click.option("--vertical", is_flag=True, help="横转竖")
    @click.option("-c", "--config", "config_path", default=None)
    def post(episode, vertical, config_path):
        """后期合成"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集[/bold cyan]\n")
        if not _run_via_celery("pipeline_post", cfg, episode, vertical=vertical):
            sys.exit(1)

    @cli.command("all")
    @click.argument("episode", type=int, default=1)
    @click.option("--vertical", is_flag=True, help="横转竖")
    @click.option("-c", "--config", "config_path", default=None)
    @click.option("--force", is_flag=True, help="强制覆盖已有文件")
    def run_all(episode, vertical, config_path, force):
        """一键全流程（等价于依次运行 preview → produce → post）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]━━━ 全流程 第{episode}集 ━━━[/bold cyan]\n")
        for i, (label, task_name) in enumerate([
            ("预览", "pipeline_preview"),
            ("生产", "pipeline_produce"),
            ("后期", "pipeline_post"),
        ], 1):
            console.print(f"[bold][{i}/3] {label}[/bold]")
            if task_name == "pipeline_post":
                ok = _run_via_celery(task_name, cfg, episode, vertical=vertical)
            elif task_name == "pipeline_produce":
                ok = _run_via_celery(task_name, cfg, episode, vertical=vertical, force=force)
            else:
                ok = _run_via_celery(task_name, cfg, episode, force=force)
            if not ok:
                console.print(f"\n[red]❌ 流程在「{label}」步骤失败，已终止[/red]")
                sys.exit(1)
        console.print("\n[bold green]✅ 全流程完成！[/bold green]")

    @cli.command()
    @click.option("-c", "--config", "config_path", default=None)
    def portraits(config_path) -> None:
        """生成定妆照（通过 Celery）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
        if not _run_via_celery("pipeline_portraits", cfg):
            sys.exit(1)
