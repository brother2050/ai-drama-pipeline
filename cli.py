#!/usr/bin/env python3
"""
AI 短剧管线 v2 — 统一 CLI 入口

依赖: Redis + Celery（必选）
启动: python cli.py serve        → Web 工作台
      python cli.py worker       → Celery Worker
      python cli.py all 1        → 一键全流程
"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()
from infra.config import get_root as _get_root, SYSTEM_CONFIG_PATH, REPO_LOGS_DIR, load_yaml_full

ROOT = _get_root()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.network import port_ok as _port_open, redis_port as _redis_port

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cli")

# 从 infra.config 导入共享工具函数
from infra.config import cfg_get as _cfg_get


def _load_env():
    env_file = ROOT / ".env"
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


def _ensure_redis():
    """确保 Redis 运行（必选依赖）"""
    if _port_open(_redis_port()):
        return True

    console.print("[yellow]⚠ Redis 未运行，尝试启动...[/yellow]")
    redis = shutil.which("redis-server")
    if redis:
        subprocess.Popen([redis, "--daemonize", "yes"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        if _port_open(_redis_port()):
            console.print("[green]✅ Redis 已启动[/green]")
            return True

    # macOS Homebrew
    if shutil.which("brew"):
        subprocess.run(["brew", "services", "start", "redis"],
                       capture_output=True, timeout=30)
        time.sleep(1)
        if _port_open(_redis_port()):
            return True

    # Windows: 尝试 net start 或 sc start
    if sys.platform == "win32":
        for cmd in [["net", "start", "Redis"], ["sc", "start", "Redis"]]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
                time.sleep(2)
                if _port_open(_redis_port()):
                    return True
            except Exception:
                continue

    console.print("[red]❌ Redis 启动失败。请手动安装并启动 Redis[/red]")
    console.print("  Ubuntu: sudo apt install redis-server && sudo systemctl start redis")
    console.print("  macOS:  brew install redis && brew services start redis")
    return False


def _ensure_deps():
    """启动前检查"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)
    if not _ensure_postgres():
        sys.exit(1)


def _ensure_postgres():
    """确保 PostgreSQL 已配置且可达"""
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        console.print("[red]❌ AI_DRAMA_DB_DSN 未配置（PostgreSQL 必须）[/red]")
        console.print("  示例: AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama")
        console.print("  先创建数据库: CREATE DATABASE ai_drama;")
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
            console.print(f"[red]❌ PostgreSQL 连接被拒绝，请确认服务已启动[/red]")
            console.print(f"  Ubuntu: sudo systemctl start postgresql")
            console.print(f"  macOS:  brew services start postgresql@16")
            console.print(f"  Docker: docker run -d -p 5432:5432 postgres:16-alpine")
        elif "authentication failed" in msg:
            console.print(f"[red]❌ PostgreSQL 认证失败，请检查 DSN 中的用户名和密码[/red]")
            console.print(f"  当前 DSN: {dsn.split('@')[-1] if '@' in dsn else dsn}")
        elif "does not exist" in msg:
            console.print(f"[red]❌ 数据库不存在，请先创建: CREATE DATABASE ai_drama;[/red]")
        else:
            console.print(f"[red]❌ PostgreSQL 连接失败: {msg[:120]}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]❌ PostgreSQL 连接异常: {type(e).__name__}: {e}[/red]")
        return False


# ── CLI ──

@click.group()
@click.version_option("2.0.0", prog_name="drama")
def cli() -> None:
    """🎬 AI 短剧管线 v2 — 从剧本到成片，一键搞定"""
    pass


@cli.command()
@click.option("-p", "--port", default=8888, help="Web 端口")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--reload", is_flag=True, help="开发模式")
def serve(port, host, reload) -> None:
    """启动 Web 工作台"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)
    console.print(f"\n[bold green]🎬 Web 工作台启动中 — http://localhost:{port}[/bold green]\n")
    console.print("[dim]需要同时启动 worker: python cli.py worker[/dim]\n")
    import uvicorn
    uvicorn.run("web.app:create_app", factory=True, host=host, port=port, reload=reload, log_level="info")


@cli.command()
@click.option("--concurrency", "-c", default=2, help="并发数")
def worker(concurrency) -> None:
    """启动 Celery Worker（处理异步任务）"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)

    celery = shutil.which("celery")
    if not celery:
        console.print("[red]❌ celery 未安装。pip install celery redis[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]🔧 Celery Worker 启动中 (并发: {concurrency})[/bold cyan]\n")
    os.execvp(celery, [
        celery, "-A", "pipeline.celery_app", "worker",
        "--loglevel=info", f"--concurrency={concurrency}",
        "-Q", "drama",
        "--pool=threads",  # AI 任务 IO 密集，用线程池
    ])


def _check_postgres() -> tuple[bool, str, str]:
    """检查 PostgreSQL 状态 → (ok, address, reason)"""
    pg_dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not pg_dsn:
        return False, "未配置", "未配置"
    try:
        import psycopg2
        conn = psycopg2.connect(pg_dsn, connect_timeout=3)
        conn.close()
        return True, pg_dsn.split("@")[-1], ""
    except ImportError:
        return False, "未配置", "psycopg2 未安装 (pip install psycopg2-binary)"
    except Exception as e:
        logger.debug(f"{type(e).__name__}: {e}")
        return False, pg_dsn.split("@")[-1] if "@" in pg_dsn else "已配置", f"{type(e).__name__}: {str(e)[:60]}"


def _check_celery(redis_ok: bool) -> bool:
    """检查 Celery Worker 状态"""
    if not redis_ok:
        return False
    try:
        from pipeline.celery_app import app
        insp = app.control.inspect(timeout=2)
        return bool(insp.active())
    except Exception as e:
        logger.debug(f"{type(e).__name__}: {e}")
        return False


def _check_comfyui(cfg: dict) -> tuple[bool, str]:
    """检查 ComfyUI 状态 → (ok, url)"""
    url = cfg.get("comfyui", {}).get("url", "")
    if not url:
        return False, ""
    try:
        from infra.http_pool import get_fast_client
        api_key = cfg.get("comfyui", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = get_fast_client().get(f"{url}/system_stats", headers=headers)
        return r.status_code == 200, url
    except Exception:
        return False, url


def _check_llm(cfg: dict, defaults: dict) -> tuple[bool, str, str, bool]:
    """检查 LLM 状态 → (ok, backend, base_url, enabled)"""
    llm_cfg = cfg.get("llm", {})
    enabled = llm_cfg.get("enabled", False)
    backend = llm_cfg.get("backend", defaults.get("llm_backend", "openai"))
    base_url = llm_cfg.get("base_url", "")
    if not enabled:
        return False, backend, base_url, False
    if not base_url:
        return False, backend, base_url, True
    try:
        from infra.http_pool import get_fast_client
        check_url = base_url.rstrip("/")
        if not check_url.endswith("/v1"):
            check_url += "/v1"
        api_key = llm_cfg.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = get_fast_client().get(f"{check_url}/models", headers=headers)
        return r.status_code == 200, backend, base_url, True
    except Exception as e:
        logger.debug(f"LLM 检测失败: {e}")
        return False, backend, base_url, True


def _check_tts(cfg: dict, reg, defaults: dict, table: Table):
    """检查 TTS 状态并添加到表格"""
    tts = cfg.get("models", {}).get("tts_backend", defaults.get("tts_backend"))
    if not tts or not reg:
        return
    hc = reg.get_health_check("tts", tts)
    if not hc:
        return
    hc_type = hc.get("type", "")
    if hc_type == "api_key_env":
        env_name = hc.get("env", "")
        key = os.environ.get(env_name, "")
        table.add_row(f"TTS ({tts})", "[green]✅[/green]" if key else f"[yellow]⚠ {env_name} 未配置[/yellow]",
                       "云 API", "语音合成")
    elif hc_type == "http":
        api_url = _cfg_get(cfg, hc.get("config_key", ""), "")
        table.add_row(f"TTS ({tts})", "[green]✅[/green]" if api_url else "[yellow]⚠ 未配置[/yellow]",
                       api_url or "-", "语音合成")


def _print_status_warnings(redis, celery_ok, llm_enabled, llm_ok, llm_base_url):
    if not redis or not celery_ok:
        console.print("\n[red]⚠ Redis 和 Celery Worker 是必选依赖[/red]")
        console.print("  1. 启动 Redis: redis-server --daemonize yes")
        console.print("  2. 启动 Worker: python cli.py worker")
    if llm_enabled and not llm_ok:
        console.print("\n[yellow]⚠ LLM 已启用但连接失败，AI 生成功能不可用[/yellow]")
        console.print(f"  检查地址: {llm_base_url}")
        console.print("  如果使用 Ollama: ollama serve")
        console.print("  如果使用云 API: 检查 api_key 和 base_url")


@cli.command()
def status() -> None:
    """检查所有服务状态"""
    _load_env()
    table = Table(title="🎬 服务状态", show_lines=True)
    table.add_column("服务", style="cyan")
    table.add_column("状态", justify="center")
    table.add_column("端口/地址", justify="center")
    table.add_column("说明")

    redis = _port_open(_redis_port())
    table.add_row("Redis", "[green]✅[/green]" if redis else "[red]❌ 必选[/red]",
                   str(_redis_port()), "任务队列（必选）")

    pg_ok, pg_addr, pg_reason = _check_postgres()
    table.add_row("PostgreSQL", "[green]✅[/green]" if pg_ok else "[red]❌ 必选[/red]",
                   pg_addr, "数据库（必选）" if pg_ok else pg_reason)

    celery_ok = _check_celery(redis)
    table.add_row("Celery Worker", "[green]✅[/green]" if celery_ok else "[red]❌ 未启动[/red]",
                   "-", "异步任务处理（必选）")

    from infra.config import Config as _Config
    cfg_path = _resolve_config()
    try:
        cfg = _Config(cfg_path).data
    except Exception:
        cfg = load_yaml_full(cfg_path)

    comfyui_ok, comfyui_url = _check_comfyui(cfg)
    table.add_row("ComfyUI", "[green]✅[/green]" if comfyui_ok else "[yellow]⚠[/yellow]",
                   comfyui_url, "图片/视频生成")

    from flow.model_registry import ModelRegistry as _MR
    try:
        _reg, _defaults = _MR(), _MR().get_defaults()
    except Exception:
        _reg, _defaults = None, {}
    _check_tts(cfg, _reg, _defaults, table)

    llm_ok, llm_backend, llm_base_url, llm_enabled = _check_llm(cfg, _defaults)
    if not llm_enabled:
        table.add_row(f"LLM ({llm_backend})", "[yellow]⚠ 未启用[/yellow]",
                       llm_base_url or "-", "AI 生成（在 project.yaml 中设置 llm.enabled: true）")
    else:
        table.add_row(f"LLM ({llm_backend})", "[green]✅[/green]" if llm_ok else "[red]❌ 连接失败[/red]",
                       llm_base_url, "AI 内容生成")

    console.print(table)
    _print_status_warnings(redis, celery_ok, llm_enabled, llm_ok, llm_base_url)


@cli.command()
@click.argument("episode", type=int, default=1)
@click.argument("level", type=click.Choice(["draft", "standard", "high"]), default="draft")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--force", is_flag=True, help="强制覆盖已有文件")
def preview(episode, level, config_path, force):
    """快速预览（通过 Celery 异步执行）"""
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
    """准备阶段 — 批量预翻译（生产前运行一次）

    运行完毕后，drama produce/preview/all 可完全不依赖 LLM 全速运行。
    定妆照和场景图请通过 Web 工作台单独执行。
    """
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🔧 准备阶段 第{episode}集[/bold cyan]\n")
    console.print("[dim]  翻译角色/场景/分镜[/dim]\n")
    if not _run_via_celery("pipeline_ai_prepare", cfg, episode,
                           force=force,
                           translate=not no_translate):
        sys.exit(1)


@cli.command()
@click.argument("episode", type=int)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--force", is_flag=True, help="强制覆盖已有文件")
def produce(episode, vertical, config_path, force):
    """完整生产（通过 Celery 异步执行）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 生产 第{episode}集[/bold cyan]\n")
    if not _run_via_celery("pipeline_produce", cfg, episode, vertical=vertical, force=force):
        sys.exit(1)


@cli.command()
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
def post(episode, vertical, config_path):
    """后期合成"""
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


def _check_celery_worker() -> bool:
    """检查 Celery Worker 是否可用，不可用则打印提示并返回 False"""
    from pipeline.celery_app import app
    try:
        insp = app.control.inspect(timeout=3)
        if not insp.active():
            console.print("[red]❌ Celery Worker 未启动！[/red]")
            console.print("  请在另一个终端运行: [bold]drama worker[/bold]")
            return False
        return True
    except Exception as e:
        console.print(f"[red]❌ 无法连接 Celery（Redis 未运行？）: {e}[/red]")
        console.print("  请先启动 Redis: redis-server --daemonize yes")
        return False


def _poll_celery_task(task, progress, ptask) -> None:
    """轮询 Celery 任务进度并更新进度条"""
    while not task.ready():
        try:
            info = task.info if task.info else {}
            if isinstance(info, dict):
                progress.update(ptask, completed=info.get("progress", 0),
                                description=info.get("message", "") or "处理中...")
        except Exception as e:
            logger.debug(f"{type(e).__name__}: {e}")
        time.sleep(0.5)


def _handle_celery_result(task, result_handler=None) -> bool:
    """处理 Celery 任务最终结果，返回 True 表示成功"""
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
    elif isinstance(raw, RuntimeError):
        console.print(f"[red]❌ {raw}[/red]")
    elif isinstance(raw, Exception):
        console.print(f"[red]❌ Worker 异常: {type(raw).__name__}: {str(raw).splitlines()[0]}[/red]")
        console.print("[dim]  请检查 Worker 日志: celery -A pipeline.celery_app worker --loglevel=info[/dim]")
    else:
        console.print(f"[red]❌ {raw}[/red]")
    return False


def _run_via_celery(task_name: str, first_arg, *args, result_handler=None, **kwargs) -> bool:
    """通过 Celery 提交任务并等待完成。返回 True 表示成功，False 表示失败。

    Args:
        task_name: Celery 任务名
        first_arg: 任务第一个参数（config_path 或 plan_data 等）
        *args: 附加参数
        result_handler: 可选回调 (result) -> bool，返回 True 表示已自行处理结果
        **kwargs: 关键字参数
    """
    from pipeline.celery_app import app
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


@cli.command()
@click.option("-c", "--config", "config_path", default=None)
def portraits(config_path) -> None:
    """生成定妆照（通过 Celery）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
    if not _run_via_celery("pipeline_portraits", cfg):
        sys.exit(1)


# ── 项目管理 ──

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
        import yaml
        sys_path = SYSTEM_CONFIG_PATH
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
    from scripts.project_mgr import create_project
    create_project(name, ROOT, console, style=style, genre=genre)


@project.command("switch")
@click.argument("name")
def project_switch(name):
    from scripts.project_mgr import switch_project
    switch_project(name, ROOT, console)


@project.command("current")
def project_current() -> None:
    from scripts.project_mgr import show_current
    show_current(ROOT, console)


@project.command("delete")
@click.argument("name")
def project_delete(name):
    # 显示项目信息后确认
    from infra.config import projects_dir
    proj_dir = projects_dir() / name
    if not proj_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    # 统计镜头和角色数
    shot_count = 0
    try:
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_episodes_summary
        rows = get_episodes_summary(get_pool())
        shot_count = sum(r["shots"] for r in rows)
    except Exception:
        logger.debug("获取集统计失败")
        pass
    from infra.config import ProjectPaths
    chars_dir = ProjectPaths(proj_dir).characters_dir
    char_count = len(list(chars_dir.glob("*.yaml"))) if chars_dir.exists() else 0
    if not click.confirm(f"确认删除项目 '{name}'（{shot_count} 个镜头, {char_count} 个角色）？"):
        return
    from scripts.project_mgr import delete_project
    delete_project(name, ROOT, console)


@cli.command()
def env() -> None:
    """显示环境信息"""
    import platform
    from infra.gpu import get_generation_config
    gen = get_generation_config()
    _load_env()
    console.print(f"[cyan]OS:[/cyan]     {platform.system()} {platform.release()}")
    console.print(f"[cyan]Python:[/cyan] {platform.python_version()}")
    console.print("[cyan]GPU:[/cyan]    由三方工具管理（本地不检测）")
    res = gen.get('resolution')
    steps = gen.get('image_steps')
    if res and steps:
        console.print(f"[cyan]生成参数:[/cyan] {res} / steps={steps}")
    else:
        console.print("[cyan]生成参数:[/cyan] 使用各后端 models_registry.yaml 中的原生默认值")
    console.print(f"[cyan]Redis:[/cyan]  {'✅ 运行中' if _port_open(_redis_port()) else '❌ 未运行'}")
    # PostgreSQL
    pg_dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if pg_dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(pg_dsn, connect_timeout=3)
            conn.close()
            console.print(f"[cyan]PG:[/cyan]     ✅ {pg_dsn.split('@')[-1]}")
        except Exception:
            console.print(f"[cyan]PG:[/cyan]     ❌ 连接失败 ({pg_dsn.split('@')[-1] if '@' in pg_dsn else 'DSN 已配置'})")
    else:
        console.print("[cyan]PG:[/cyan]     ❌ 未配置 AI_DRAMA_DB_DSN")
    # 当前项目
    try:
        from infra.config import get_active_project_dir, ProjectPaths
        active = get_active_project_dir(ROOT)
        cfg_file = ProjectPaths(active).project_yaml
        if cfg_file.exists():
            import yaml
            data = load_yaml_full(cfg_file)
            proj_name = data.get("project", {}).get("name", active.name)
        else:
            proj_name = active.name
        console.print(f"[cyan]项目:[/cyan]   {proj_name} ({active})")
    except Exception:
        console.print("[cyan]项目:[/cyan]   未设置")


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
        console.print(f"  模式:   [yellow]追加（不覆盖已有数据）[/yellow]")
    console.print()

    if not _run_via_celery("pipeline_import_json", data, result_handler=_handle_import_result):
        sys.exit(1)


def _handle_import_result(result) -> bool:
    """导入任务的结果处理回调。返回 True 表示已处理。"""
    if isinstance(result, dict) and result.get("status") == STATUS_DONE:
        mode = result.get("mode", "full")
        if mode == "append":
            console.print(f"\n[bold green]✅ 追加导入成功！[/bold green]")
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
            console.print(f"\n[bold green]✅ 导入成功！[/bold green]")
            console.print(f"  项目: {result.get('project_name', '?')}")
            console.print(f"  角色: {result.get('characters', 0)} 个")
            console.print(f"  场景: {result.get('scenes', 0)} 个")
            console.print(f"  分镜: {result.get('shots', 0)} 个")
            console.print(f"  路径: {result.get('project_dir', '?')}")
        # 翻译状态
        translation = result.get("translation", {})
        if translation:
            if translation.get("complete"):
                console.print(f"  翻译: [green]✅ 完整 — 可直接进入生产管线[/green]")
            else:
                console.print(f"  翻译: [yellow]⚠ {translation['summary']}[/yellow]")
                console.print(f"         运行 [bold]drama prepare[/bold] 补全后可进入生产管线")
        return True
    if isinstance(result, dict) and result.get("status") == STATUS_ERROR:
        console.print(f"\n[red]❌ {result.get('reason', '导入失败')}[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]• {err}[/red]")
        return True
    return False


@cli.command("export")
@click.argument("episode", type=int, default=1)
@click.option("-o", "--output", default=None, help="输出 CSV 文件路径")
def export_csv(episode, output):
    """📤 导出分镜到 CSV 文件"""
    _load_env()
    from infra.database.storyboard_db import export_to_csv, get_episode_shots
    from infra.database.pool import get_pool
    from infra.config import get_active_project_dir

    try:
        active = get_active_project_dir(ROOT)
    except Exception:
        console.print("[red]❌ 未找到活动项目[/red]")
        return

    shots = get_episode_shots(get_pool(), episode)
    if not shots:
        console.print(f"[yellow]第{episode}集没有镜头[/yellow]")
        return

    if not output:
        from infra.config import ProjectPaths
        output = str(ProjectPaths(active).episode_dir(episode) / f"episode_{episode:02d}.csv")

    out_path = Path(output)
    count = export_to_csv(get_pool(), episode, out_path)
    console.print(f"[green]✅ 导出 {count} 个镜头到 {out_path}[/green]")


@cli.command()
@click.option("--logs", is_flag=True)
@click.option("--cache", is_flag=True)
@click.option("--yes", "-y", is_flag=True, help="跳过确认")
def clean(logs, cache, yes):
    """清理日志和缓存"""
    if logs and not yes:
        log_dir = REPO_LOGS_DIR
        log_files = list(log_dir.glob("*.log")) if log_dir.exists() else []
        total_size = sum(f.stat().st_size for f in log_files)
        if log_files:
            console.print(f"  将清理 {len(log_files)} 个日志文件（{total_size / 1024:.1f} KB）")
            if not click.confirm("确认清理日志？"):
                return
    if logs:
        log_dir = REPO_LOGS_DIR
        if log_dir.exists():
            for f in log_dir.glob("*.log"):
                f.write_text("")
        console.print("[green]✅ 日志已清理[/green]")
    if cache:
        for d in [ROOT / ".pytest_cache", ROOT / "__pycache__"]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        console.print("[green]✅ 缓存已清理[/green]")
    if not logs and not cache:
        console.print("[yellow]请指定: --logs 或 --cache[/yellow]")


# ── AI 生成 ──

@cli.group()
def generate():
    """🤖 AI 内容生成（需要 LLM 服务）"""
    pass


def _get_llm(config_path: str | None = None):
    """获取 LLM 实例"""
    _load_env()
    cfg_file = _resolve_config(config_path)
    from infra.config import Config
    cfg = Config(cfg_file)

    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        console.print("[red]❌ LLM 未启用[/red]")
        console.print(f"\n  请在项目配置文件中启用 LLM:")
        console.print(f"    文件: {cfg_file}")
        console.print(f"    设置: [bold]llm.enabled: true[/bold]")
        console.print(f"\n  并配置 LLM 后端（二选一）:")
        console.print(f"    本地: llm.backend: ollama + llm.base_url: http://localhost:11434")
        console.print(f"    云API: llm.backend: openai + llm.base_url: https://api.siliconflow.cn + llm.api_key: sk-xxx")
        sys.exit(1)

    from api.registry import Container
    cont = Container(cfg.data)
    try:
        return cont.get("llm"), cfg, cfg_file
    except Exception as e:
        console.print(f"[red]❌ LLM 初始化失败: {e}[/red]")
        sys.exit(1)


@generate.command("storyboard")
@click.argument("episode", type=int, default=1)
@click.option("-o", "--outline", default=None, help="大纲文件路径（txt/md）")
@click.option("--text", default=None, help="直接输入大纲文本")
@click.option("-d", "--duration", type=int, default=90, help="目标时长（秒，默认 90）")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--append", is_flag=True, help="追加到现有分镜表（不覆盖）")
def gen_storyboard(episode, outline, text, duration, config_path, append):
    """📝 从剧情大纲生成分镜表"""
    # 读取大纲（--outline 和 --text 互斥）
    if text and outline:
        console.print("[red]❌ --outline 和 --text 不能同时使用，请选择其中一个[/red]")
        sys.exit(1)
    if text:
        outline_text = text
    elif outline:
        p = Path(outline)
        if not p.exists():
            console.print(f"[red]❌ 文件不存在: {outline}[/red]")
            sys.exit(1)
        outline_text = p.read_text(encoding="utf-8")
    else:
        console.print("[yellow]请提供大纲: --outline <文件> 或 --text <文本>[/yellow]")
        sys.exit(1)

    if not outline_text.strip():
        console.print("[red]❌ 大纲为空[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)

    # 加载已有角色和场景
    from engines.llm_generator import generate_storyboard, StoryboardGenParams
    from infra.config import ProjectPaths
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    from infra.config import load_yaml_entities
    characters = load_yaml_entities(paths.characters_dir, "character")
    scenes = load_yaml_entities(paths.scenes_dir, "scene")

    console.print(f"\n[bold cyan]📝 生成分镜表 — 第{episode}集[/bold cyan]")
    console.print(f"[dim]大纲: {len(outline_text)} 字 | 目标: {duration}s | 角色: {len(characters)} | 场景: {len(scenes)}[/dim]\n")

    style = cfg.get("project", {}).get("style", "")
    genre = cfg.get("project", {}).get("genre", "")
    shots = generate_storyboard(llm, StoryboardGenParams(
        outline=outline_text, characters=characters, scenes=scenes,
        episode=episode, target_duration=duration, style=style, genre=genre,
    ))

    if not shots:
        console.print("[red]❌ 生成失败，未获得有效分镜[/red]")
        sys.exit(1)

    # 保存
    from engines.storyboard import save_storyboard, append_storyboard
    if append:
        append_storyboard(shots, episode)
    else:
        save_storyboard(shots, episode)

    total_sec = sum(int(s.get("duration", 4)) for s in shots)
    console.print(f"\n[bold green]✅ 生成完成！[/bold green]")
    console.print(f"  镜头数: {len(shots)}")
    console.print(f"  总时长: {total_sec} 秒 ({total_sec/60:.1f} 分钟)")
    console.print(f"  保存至: DB (第{episode}集)")

    # 显示预览表
    _print_shots_preview(shots)


@generate.command("characters")
@click.option("-d", "--desc", multiple=True, required=True, help="角色描述（可多次指定）")
@click.option("-c", "--config", "config_path", default=None)
def gen_characters(desc, config_path):
    """👤 从描述生成角色配置"""
    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.llm_generator import generate_characters

    console.print(f"\n[bold cyan]👤 生成角色配置[/bold cyan]")
    console.print(f"[dim]共 {len(desc)} 个角色描述[/dim]\n")

    try:
        chars = generate_characters(llm, list(desc))
    except RuntimeError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)

    if not chars:
        console.print("[red]❌ 生成失败[/red]")
        sys.exit(1)

    # 保存
    from infra.config import ProjectPaths, save_yaml
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    char_dir = paths.characters_dir
    char_dir.mkdir(parents=True, exist_ok=True)

    for char in chars:
        cid = char.get("id", "unknown")
        path = char_dir / f"{cid}.yaml"
        save_yaml(path, {"character": char})
        console.print(f"  ✅ {char.get('name', '?')} ({cid}) → {path.name}")

    console.print(f"\n[bold green]✅ 生成 {len(chars)} 个角色[/bold green]")


@generate.command("scenes")
@click.option("-d", "--desc", multiple=True, required=True, help="场景描述（可多次指定）")
@click.option("-c", "--config", "config_path", default=None)
def gen_scenes(desc, config_path):
    """🏔️ 从描述生成场景配置"""
    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.llm_generator import generate_scenes

    console.print(f"\n[bold cyan]🏔️ 生成场景配置[/bold cyan]")
    console.print(f"[dim]共 {len(desc)} 个场景描述[/dim]\n")

    try:
        scene_list = generate_scenes(llm, list(desc))
    except RuntimeError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)

    if not scene_list:
        console.print("[red]❌ 生成失败[/red]")
        sys.exit(1)

    from infra.config import ProjectPaths, save_yaml
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    scene_dir = paths.scenes_dir
    scene_dir.mkdir(parents=True, exist_ok=True)

    for scene in scene_list:
        sid = scene.get("id", "unknown")
        path = scene_dir / f"{sid}.yaml"
        save_yaml(path, {"scene": scene})
        console.print(f"  ✅ {scene.get('name', '?')} ({sid}) → {path.name}")

    console.print(f"\n[bold green]✅ 生成 {len(scene_list)} 个场景[/bold green]")


@generate.command("bible")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--outline", default=None, help="剧情大纲文件（用于推断人际关系）")
def gen_bible(config_path, outline):
    """📖 为所有角色生成角色圣经（Character Bible）"""
    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.character_bible import CharacterBible, generate_bible
    from infra.config import load_yaml_entities

    paths = Path(cfg_file).parent.parent
    chars = load_yaml_entities(Path(paths) / "config" / "characters", "character")
    if not chars:
        console.print("[red]❌ 没有角色，请先创建角色[/red]")
        sys.exit(1)

    outline_text = ""
    if outline:
        p = Path(outline)
        if p.exists():
            outline_text = p.read_text(encoding="utf-8")

    console.print(f"\n[bold cyan]📖 生成角色圣经[/bold cyan]")
    console.print(f"[dim]共 {len(chars)} 个角色[/dim]\n")

    bible = CharacterBible(str(paths))
    generated = 0
    for char in chars:
        cid = char.get("id", "?")
        cname = char.get("name", cid)
        console.print(f"  生成 {cname} ({cid})...")

        result = generate_bible(llm, char, outline=outline_text, other_chars=chars)
        if result:
            bible.save(cid, result)
            console.print(f"    ✅ 已保存")
            generated += 1
        else:
            console.print(f"    ⚠ 生成失败")

    console.print(f"\n[bold green]✅ 生成 {generated}/{len(chars)} 个角色圣经[/bold green]")


@generate.command("all")
@click.argument("episode", type=int, default=1)
@click.option("-o", "--outline", required=True, help="大纲文件路径")
@click.option("-d", "--duration", type=int, default=90, help="目标时长（秒）")
@click.option("-c", "--config", "config_path", default=None)
def gen_all(episode, outline, duration, config_path):
    """🚀 一键生成：大纲 → 角色 + 场景 + 分镜"""
    p = Path(outline)
    if not p.exists():
        console.print(f"[red]❌ 文件不存在: {outline}[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)
    outline_text = p.read_text(encoding="utf-8")

    console.print(f"\n[bold cyan]━━━ AI 全量生成 第{episode}集 ━━━[/bold cyan]\n")

    # 1) 让 LLM 从大纲中提取角色和场景描述，然后生成配置
    from engines.llm_generator import generate_storyboard, generate_characters, generate_scenes, StoryboardGenParams

    # 先生成分镜（会自动使用已有角色/场景）
    from infra.config import ProjectPaths
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    from infra.config import load_yaml_entities
    characters = load_yaml_entities(paths.characters_dir, "character")
    scenes = load_yaml_entities(paths.scenes_dir, "scene")

    console.print("[bold][1/3] 生成分镜表...[/bold]")
    style = cfg.get("project", {}).get("style", "")
    genre = cfg.get("project", {}).get("genre", "")
    try:
        shots = generate_storyboard(llm, StoryboardGenParams(
            outline=outline_text, characters=characters, scenes=scenes,
            episode=episode, target_duration=duration, style=style, genre=genre,
        ))
    except RuntimeError as e:
        console.print(f"[red]❌ 分镜生成失败: {e}[/red]")
        sys.exit(1)

    if shots:
        from engines.storyboard import save_storyboard
        save_storyboard(shots, episode)
        console.print(f"  ✅ {len(shots)} 个镜头")
    else:
        console.print("  ⚠ 分镜生成失败")

    console.print("\n[bold green]✅ 全量生成完成！[/bold green]")

    if shots:
        total_sec = sum(int(s.get("duration", 4)) for s in shots)
        console.print(f"  分镜: {len(shots)} 镜头, {total_sec}秒")
        _print_shots_preview(shots)




def _print_shots_preview(shots: list[dict]):
    """打印分镜预览表"""
    table = Table(title="分镜预览", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("场景", width=12)
    table.add_column("角色", width=12)
    table.add_column("动作", width=25)
    table.add_column("台词", width=20)
    table.add_column("景别", width=8)
    table.add_column("情绪", width=8)
    table.add_column("时长", width=4, justify="right")

    for shot in shots[:20]:  # 最多显示 20 个
        table.add_row(
            shot.get("shot_id", "?"),
            shot.get("scene_id", ""),
            shot.get("characters", ""),
            (shot.get("action", "")[:22] + "...") if len(shot.get("action", "")) > 22 else shot.get("action", ""),
            (shot.get("dialogue", "")[:17] + "...") if len(shot.get("dialogue", "")) > 17 else shot.get("dialogue", ""),
            shot.get("shot_type", ""),
            shot.get("emotion", ""),
            str(shot.get("duration", "")),
        )

    if len(shots) > 20:
        table.add_row("...", "", "", f"还有 {len(shots)-20} 个镜头", "", "", "", "")

    console.print(table)


if __name__ == "__main__":
    cli()
