"""CLI 入口 — drama 命令组

模块结构：
  cli/__init__.py    — 主组 + 共享工具函数
  cli/io.py          — import / export
  cli/system.py      — serve / worker / status / env / clean
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

from infra.config import get_root as _get_root  # noqa: E402

ROOT = _get_root()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 共享工具函数 ──────────────────────────────────────

def _load_env():
    from infra.config.core import ENV_FILE_PATH
    env_file = ENV_FILE_PATH
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        except ImportError:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _resolve_config(config_path: str | None = None) -> str:
    if config_path:
        return str(Path(config_path).resolve())
    from infra.config import resolve_project_config
    try:
        return resolve_project_config(ROOT)
    except FileNotFoundError:
        console.print("[red]❌ 未找到 config/project.yaml，请先初始化默认项目[/red]")
        sys.exit(1)


def _ensure_deps():
    """启动前检查（Redis + PostgreSQL + 初始化全局资源）"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)
    if not _ensure_postgres():
        sys.exit(1)
    from infra.globals import init_globals
    init_globals()
    # 启动文件系统监控（角色/场景 YAML 变化自动失效缓存）
    _start_file_monitor()


def _start_file_monitor():
    """启动文件系统监控（延迟初始化，需要活动项目目录）"""
    try:
        from infra.config import get_active_project_dir
        from infra.globals import start_file_monitor
        proj_dir = get_active_project_dir(ROOT)
        config_dir = proj_dir / "config"
        if config_dir.exists():
            start_file_monitor(config_dir)
    except Exception as e:
        from rich.console import Console
        Console().print(f"[dim]文件监控启动跳过: {e}[/dim]")


def _ensure_redis() -> bool:
    import shutil
    import subprocess
    import time
    from infra.network import port_ok as _port_open, redis_port as _redis_port

    if _port_open(_redis_port()):
        return True

    console.print("[yellow]⚠ Redis 未运行，尝试启动...[/yellow]")

    def _wait_for_port() -> bool:
        for _ in range(6):
            time.sleep(0.5)
            if _port_open(_redis_port()):
                return True
        return False

    redis = shutil.which("redis-server")
    if redis:
        proc = subprocess.Popen([redis, "--daemonize", "yes"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proc.wait(timeout=2)
            if proc.returncode and proc.returncode != 0:
                stderr = proc.stderr.read().decode(errors="replace")[:200] if proc.stderr else ""
                console.print(f"[red]❌ Redis 启动失败 (exit {proc.returncode}): {stderr}[/red]")
                return False
        except subprocess.TimeoutExpired:
            pass
        if _wait_for_port():
            console.print("[green]✅ Redis 已启动[/green]")
            return True

    if shutil.which("brew"):
        subprocess.run(["brew", "services", "start", "redis"], capture_output=True, timeout=30)
        if _wait_for_port():
            return True

    if sys.platform == "win32":
        for cmd in [["net", "start", "Redis"], ["sc", "start", "Redis"]]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
            except Exception:
                continue
            if _wait_for_port():
                return True

    console.print("[red]❌ Redis 启动失败。请手动安装并启动 Redis[/red]")
    return False


def _ensure_postgres() -> bool:
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        console.print("[red]❌ AI_DRAMA_DB_DSN 未配置（PostgreSQL 必须）[/red]")
        console.print("  示例: AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama")
        return False
    try:
        import psycopg2
    except ImportError:
        console.print("[red]❌ psycopg2 未安装。pip install psycopg2-binary[/red]")
        return False
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        return True
    except psycopg2.OperationalError as e:
        msg = str(e).strip()
        if "Connection refused" in msg or "could not connect" in msg:
            console.print("[red]❌ PostgreSQL 连接被拒绝，请确认服务已启动[/red]")
        elif "authentication failed" in msg:
            console.print("[red]❌ PostgreSQL 认证失败，请检查 DSN 中的用户名和密码[/red]")
        elif "does not exist" in msg:
            console.print("[red]❌ 数据库不存在，请先创建: CREATE DATABASE ai_drama;[/red]")
        else:
            console.print(f"[red]❌ PostgreSQL 连接失败: {msg[:120]}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]❌ PostgreSQL 连接异常: {type(e).__name__}: {e}[/red]")
        return False


# ── Celery 共享工具 ──────────────────────────────────

def _check_celery_worker() -> bool:
    from pipeline.app import app
    try:
        insp = app.control.inspect(timeout=3)
        if not insp.active():
            console.print("[red]❌ Celery Worker 未启动！[/red]")
            console.print("  请在另一个终端运行: [bold]drama worker[/bold]")
            return False
        return True
    except Exception as e:
        console.print(f"[red]❌ 无法连接 Celery（Redis 未运行？）: {e}[/red]")
        return False


def _poll_celery_task(task, progress, ptask) -> None:
    import time
    while not task.ready():
        try:
            info = task.info if task.info else {}
            if isinstance(info, dict):
                progress.update(ptask, completed=info.get("progress", 0),
                                description=info.get("message", "") or "处理中...")
        except Exception:
            pass
        time.sleep(0.5)


def _handle_celery_result(task, result_handler=None) -> bool:
    from infra.constants import STATUS_SKIPPED
    if task.successful():
        result = task.result
        if result_handler and result_handler(result):
            return True
        if isinstance(result, dict):
            if result.get("status") == STATUS_SKIPPED:
                console.print(f"[yellow]⏭ 已跳过: {result.get('reason', '')}[/yellow]")
            else:
                console.print(f"[dim]结果: {result}[/dim]")
        return True

    raw = task.result
    if isinstance(raw, dict) and raw.get("reason"):
        console.print(f"[red]❌ {raw['reason']}[/red]")
    elif isinstance(raw, dict) and raw.get("message"):
        console.print(f"[red]❌ {raw['message']}[/red]")
    elif isinstance(raw, Exception):
        console.print(f"[red]❌ {raw}[/red]")
    else:
        console.print(f"[red]❌ {raw}[/red]")
    return False


def _run_via_celery(task_name: str, first_arg, *args, result_handler=None, **kwargs) -> bool:
    from pipeline.app import app
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

    if not _check_celery_worker():
        return False

    task = app.send_task(task_name, args=[first_arg, *args], kwargs=kwargs)
    console.print(f"[dim]任务已提交: {task.id}[/dim]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                  TimeElapsedColumn(), console=console) as progress:
        ptask = progress.add_task("等待中...", total=100)
        _poll_celery_task(task, progress, ptask)
        progress.update(ptask, description=("[red]❌ 失败[/red]" if task.failed() else "[green]✅ 完成[/green]"),
                        completed=100 if task.successful() else None)
        return _handle_celery_result(task, result_handler)


# ── 主 CLI 组 ──────────────────────────────────────

@click.group()
@click.version_option("2.0.0", prog_name="drama")
def cli() -> None:
    """🎬 AI 短剧管线 v2 — 从剧本到成片，一键搞定"""
    pass


# 注册子命令组
from cli.system import register_system_commands  # noqa: E402
from cli.io import register_io_commands  # noqa: E402

register_system_commands(cli)
register_io_commands(cli)
