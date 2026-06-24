"""CLI workflow 子命令 — drama workflow check

功能:
  - 预检 ComfyUI 工作流 JSON 文件（不连接 ComfyUI 服务器）
  - 可选连接 ComfyUI 服务器获取 schema 后做深度预检
  - 支持批量检查 workflows/ 目录下所有 JSON 文件
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)


def register_workflow_commands(cli_group: click.Group) -> None:
    """注册 workflow 子命令组"""

    @cli_group.group()
    def workflow() -> None:
        """ComfyUI 工作流管理"""
        pass

    @workflow.command()
    @click.argument("workflow_file", type=click.Path(exists=True), required=False)
    @click.option("--comfyui-url", "-u", default=None, help="ComfyUI 服务器地址（用于深度预检）")
    @click.option("--api-key", "-k", default="", help="ComfyUI API Key")
    @click.option("--all", "check_all", is_flag=True, default=False, help="检查 workflows/ 目录下所有工作流")
    @click.option("--strict", "-s", is_flag=True, default=False, help="严格模式（warning 也算失败）")
    @click.option("--cache-file", default=None, help="schema 缓存文件路径")
    def check(workflow_file: str | None, comfyui_url: str | None, api_key: str,
              check_all: bool, strict: bool, cache_file: str | None) -> None:
        """预检 ComfyUI 工作流 JSON

        不连接 ComfyUI 时仅做结构检查（悬空引用、必填输入等）。
        连接 ComfyUI 后可做深度预检（节点类型有效性、模型文件存在性等）。

        \b
        用法:
          drama workflow check workflows/01_first_frame_flux.json
          drama workflow check --all
          drama workflow check workflows/01_first_frame_flux.json -u http://127.0.0.1:8188
        """
        from engines.workflow.preflight import WorkflowPreflightChecker
        from engines.workflow.schema_cache import ComfyUISchemaCache

        # 确定 schema 缓存
        root = Path(__file__).resolve().parent.parent
        cache_path = cache_file or str(root / "data" / "comfyui_schema_cache.json")

        schema_cache = None
        if comfyui_url:
            schema_cache = ComfyUISchemaCache(
                comfyui_url=comfyui_url,
                cache_file=cache_path,
                api_key=api_key,
            )
            console.print(f"[dim]正在从 ComfyUI 获取节点 schema...[/dim]")
            if not schema_cache.refresh():
                console.print("[yellow]⚠ 无法连接 ComfyUI 服务器，将仅做结构检查[/yellow]")
        else:
            # 尝试从本地缓存加载
            schema_cache = ComfyUISchemaCache(cache_file=cache_path)
            if schema_cache._load_from_file():
                console.print(f"[dim]已加载本地 schema 缓存: {len(schema_cache.get_all_node_types())} 个节点类型[/dim]")
            else:
                schema_cache = None
                console.print("[dim]无 schema 缓存可用，仅做结构检查[/dim]")

        checker = WorkflowPreflightChecker(schema_cache=schema_cache, strict=strict)

        # 确定要检查的文件列表
        if check_all:
            wf_dir = root / "workflows"
            if not wf_dir.exists():
                console.print(f"[red]❌ workflows 目录不存在: {wf_dir}[/red]")
                sys.exit(1)
            files = sorted(wf_dir.glob("*.json"))
            if not files:
                console.print(f"[yellow]⚠ workflows 目录下无 JSON 文件[/yellow]")
                return
        elif workflow_file:
            files = [Path(workflow_file)]
        else:
            console.print("[red]❌ 请指定工作流文件或使用 --all[/red]")
            sys.exit(1)

        # 执行检查
        all_passed = True
        for wf_file in files:
            console.print(f"\n[bold cyan]检查: {wf_file.name}[/bold cyan]")
            try:
                wf_data = json.loads(wf_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                console.print(f"  [red]❌ JSON 解析失败: {e}[/red]")
                all_passed = False
                continue

            result = checker.check(wf_data)

            # 输出结果
            status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
            console.print(f"  状态: {status} ({result.checks_passed}/{result.checks_run} 项通过)")

            if result.issues:
                table = Table(show_header=True, header_style="bold")
                table.add_column("级别", width=8)
                table.add_column("节点", width=20)
                table.add_column("字段", width=15)
                table.add_column("问题", min_width=40)
                for issue in result.issues:
                    level_color = "red" if issue.level == "error" else "yellow"
                    table.add_row(
                        f"[{level_color}]{issue.level.upper()}[/{level_color}]",
                        issue.node_id or "-",
                        issue.field or "-",
                        issue.message,
                    )
                console.print(table)

            if not result.passed:
                all_passed = False

        # 总结
        console.print(f"\n{'='*60}")
        if all_passed:
            console.print(f"[green]✓ 全部 {len(files)} 个工作流预检通过[/green]")
        else:
            console.print(f"[red]✗ {len(files)} 个工作流中有失败项[/red]")
            sys.exit(1)

    @workflow.command()
    @click.option("--comfyui-url", "-u", required=True, help="ComfyUI 服务器地址")
    @click.option("--api-key", "-k", default="", help="ComfyUI API Key")
    @click.option("--cache-file", default=None, help="schema 缓存文件路径")
    def fetch_schema(comfyui_url: str, api_key: str, cache_file: str | None) -> None:
        """从 ComfyUI 服务器获取节点 schema 并缓存到本地

        用法:
          drama workflow fetch-schema -u http://127.0.0.1:8188
        """
        from engines.workflow.schema_cache import ComfyUISchemaCache

        root = Path(__file__).resolve().parent.parent
        cache_path = cache_file or str(root / "data" / "comfyui_schema_cache.json")

        cache = ComfyUISchemaCache(
            comfyui_url=comfyui_url,
            cache_file=cache_path,
            api_key=api_key,
        )
        console.print(f"[dim]正在从 {comfyui_url} 获取节点 schema...[/dim]")
        if cache.refresh(force=True):
            node_count = len(cache.get_all_node_types())
            lora_count = len(cache.get_lora_files())
            ckpt_count = len(cache.get_checkpoint_files())
            vae_count = len(cache.get_vae_files())
            console.print(f"[green]✓ schema 缓存成功[/green]")
            console.print(f"  节点类型: {node_count}")
            console.print(f"  LoRA 文件: {lora_count}")
            console.print(f"  Checkpoint 文件: {ckpt_count}")
            console.print(f"  VAE 文件: {vae_count}")
            console.print(f"  缓存路径: {cache_path}")
        else:
            console.print(f"[red]❌ 获取 schema 失败，请检查 ComfyUI 服务器是否运行[/red]")
            sys.exit(1)

    @workflow.command()
    @click.argument("workflow_file1", type=click.Path(exists=True))
    @click.argument("workflow_file2", type=click.Path(exists=True))
    def diff(workflow_file1: str, workflow_file2: str) -> None:
        """对比两个工作流 JSON 的差异

        用法:
          drama workflow diff workflows/01_first_frame_flux.json workflows/01_first_frame_sd15.json
        """
        from engines.workflow.differ import WorkflowDiffer

        wf1 = json.loads(Path(workflow_file1).read_text(encoding="utf-8"))
        wf2 = json.loads(Path(workflow_file2).read_text(encoding="utf-8"))

        differ = WorkflowDiffer()
        summary = differ.summary(wf1, wf2)

        console.print(f"\n[bold]对比: {Path(workflow_file1).name} vs {Path(workflow_file2).name}[/bold]")
        console.print(f"  节点数: {summary['total_before']} → {summary['total_after']}")
        if summary["added"]:
            console.print(f"  [green]新增节点: {summary['added']}[/green]")
        if summary["removed"]:
            console.print(f"  [red]删除节点: {summary['removed']}[/red]")
        if summary["modified"]:
            console.print(f"  [yellow]修改节点: {summary['modified']}[/yellow]")

        if summary["added"] or summary["removed"] or summary["modified"]:
            console.print("\n[dim]详细差异:[/dim]")
            diff_text = differ.diff(wf1, wf2)
            console.print(diff_text)
        else:
            console.print("[green]两个工作流完全相同[/green]")
