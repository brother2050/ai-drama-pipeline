"""CLI 管线命令 — preview / prepare / produce / post / all / portraits"""
from __future__ import annotations

import sys

import click
from rich.console import Console

from cli import config_option

console = Console()


def register_pipeline_commands(cli):
    """注册管线命令到主 CLI 组"""

    @cli.command()
    @click.argument("episode", type=int, default=1)
    @click.argument("level", type=click.Choice(["draft", "standard", "high"]), default="draft")
    @config_option
    @click.option("--force", is_flag=True, help="强制覆盖已有文件")
    @click.option("--local", is_flag=True, help="本地执行（不走 Celery，无需 Redis/PostgreSQL）")
    def preview(episode, level, config_path, force, local):
        """快速预览"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        cfg = _resolve_config(config_path)

        if local:
            # 本地模式：直接调用 run_preview，不依赖 Celery/Redis/PostgreSQL
            from cli import _load_env
            _load_env()
            console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level}) — 本地模式[/bold cyan]\n")
            from pipeline.preview import run_preview
            try:
                run_preview(cfg, episode, level, force=force)
            except Exception as e:
                console.print(f"[red]❌ 预览失败: {e}[/red]")
                sys.exit(1)
        else:
            _ensure_deps()
            console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level})[/bold cyan]\n")
            if not _run_via_celery("pipeline_preview", cfg, episode, level, force=force):
                sys.exit(1)

    @cli.command()
    @click.argument("episode", type=int, default=1)
    @config_option
    @click.option("--force", is_flag=True, help="强制覆盖已有翻译")
    @click.option("--no-translate", is_flag=True, help="跳过翻译")
    @click.option("--local", is_flag=True, help="本地执行（不走 Celery）")
    def prepare(episode, config_path, force, no_translate, local):
        """准备阶段 — 批量预翻译（生产前运行一次，仅翻译，不含角色圣经生成）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        cfg = _resolve_config(config_path)

        if local:
            from cli import _load_env
            _load_env()
            console.print(f"\n[bold cyan]🔧 准备阶段 第{episode}集 — 本地模式[/bold cyan]\n")
            from engines.llm_generator import batch_translate_shots
            try:
                batch_translate_shots(cfg, episode, force=force, translate=not no_translate)
            except Exception as e:
                console.print(f"[red]❌ 准备阶段失败: {e}[/red]")
                sys.exit(1)
            console.print("[bold green]✅ 准备阶段完成！[/bold green]")
        else:
            _ensure_deps()
            console.print(f"\n[bold cyan]🔧 准备阶段 第{episode}集[/bold cyan]\n")
            if not _run_via_celery("pipeline_ai_prepare", cfg, episode,
                                   force=force, translate=not no_translate):
                sys.exit(1)

    @cli.command()
    @click.argument("episode", type=int)
    @click.option("--vertical", is_flag=True, help="横转竖")
    @config_option
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
    @config_option
    @click.option("--local", is_flag=True, help="本地执行（不走 Celery）")
    def post(episode, vertical, config_path, local):
        """后期合成"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        cfg = _resolve_config(config_path)

        if local:
            from cli import _load_env
            _load_env()
            console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集 — 本地模式[/bold cyan]\n")
            from post.production import run_post
            try:
                run_post(cfg, episode, vertical)
            except Exception as e:
                console.print(f"[red]❌ 后期合成失败: {e}[/red]")
                sys.exit(1)
            console.print("[bold green]✅ 后期合成完成！[/bold green]")
        else:
            _ensure_deps()
            console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集[/bold cyan]\n")
            if not _run_via_celery("pipeline_post", cfg, episode, vertical=vertical):
                sys.exit(1)

    @cli.command("all")
    @click.argument("episode", type=int, default=1)
    @click.option("--vertical", is_flag=True, help="横转竖")
    @config_option
    @click.option("--force", is_flag=True, help="强制覆盖已有文件")
    def run_all(episode, vertical, config_path, force):
        """一键全流程（依次运行 prepare → produce → post）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print(f"\n[bold cyan]━━━ 全流程 第{episode}集 ━━━[/bold cyan]\n")
        for i, (label, task_name, kwargs) in enumerate([
            ("准备", "pipeline_prepare", {"force": force}),
            ("生产", "pipeline_produce", {"vertical": vertical, "force": force}),
            ("后期", "pipeline_post", {"vertical": vertical}),
        ], 1):
            console.print(f"[bold][{i}/3] {label}[/bold]")
            ok = _run_via_celery(task_name, cfg, episode, **kwargs)
            if not ok:
                console.print(f"\n[red]❌ 流程在「{label}」步骤失败，已终止[/red]")
                sys.exit(1)
        console.print("\n[bold green]✅ 全流程完成！[/bold green]")

    @cli.command()
    @config_option
    def portraits(config_path) -> None:
        """生成定妆照（通过 Celery）"""
        from cli import _ensure_deps, _resolve_config, _run_via_celery
        _ensure_deps()
        cfg = _resolve_config(config_path)
        console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
        if not _run_via_celery("pipeline_portraits", cfg):
            sys.exit(1)
