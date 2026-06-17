"""CLI 系统命令 — serve / worker / status / env / clean"""
from __future__ import annotations

import logging
import os
import shutil
import sys

import click
from rich.console import Console
from rich.table import Table

console = Console()

logger = logging.getLogger("cli")


def register_system_commands(cli):
    """注册系统命令到主 CLI 组"""

    @cli.command()
    @click.option("-p", "--port", default=8888, help="Web 端口")
    @click.option("--host", default="0.0.0.0", help="监听地址")
    @click.option("--reload", is_flag=True, help="开发模式")
    def serve(port, host, reload) -> None:
        """启动 Web 工作台"""
        from cli import _load_env
        _load_env()
        from cli import _ensure_redis
        if not _ensure_redis():
            sys.exit(1)
        from infra.globals import init_globals, shutdown_globals, start_file_monitor
        init_globals()
        # 启动文件系统监控
        try:
            from infra.config import get_active_project_dir
            from cli import ROOT
            proj_dir = get_active_project_dir(ROOT)
            config_dir = proj_dir / "config"
            if config_dir.exists():
                start_file_monitor(config_dir)
        except Exception as e:
            logger.debug(f"文件监控启动跳过: {e}")
        console.print(f"\n[bold green]🎬 Web 工作台启动中 — http://localhost:{port}[/bold green]\n")
        console.print("[dim]需要同时启动 worker: python cli.py worker[/dim]\n")
        import atexit
        atexit.register(shutdown_globals)
        import uvicorn
        uvicorn.run("web.app:create_app", factory=True, host=host, port=port, reload=reload, log_level="info")

    @cli.command()
    @click.option("--concurrency", "-c", default=2, help="并发数")
    def worker(concurrency) -> None:
        """启动 Celery Worker（处理异步任务）"""
        import sys
        from cli import _load_env
        _load_env()
        from cli import _ensure_redis
        if not _ensure_redis():
            sys.exit(1)

        celery = shutil.which("celery")
        if not celery:
            # venv 场景：celery 可能不在 PATH 中，但在同一 bin 目录
            venv_celery = os.path.join(os.path.dirname(sys.executable), "celery")
            if os.path.isfile(venv_celery) and os.access(venv_celery, os.X_OK):
                celery = venv_celery
        if not celery:
            console.print("[red]❌ celery 未安装。pip install celery redis[/red]")
            sys.exit(1)

        console.print(f"\n[bold cyan]🔧 Celery Worker 启动中 (并发: {concurrency})[/bold cyan]\n")
        from infra.config import REPO_LOGS_DIR
        log_file = str(REPO_LOGS_DIR / "worker.log")
        REPO_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        os.execvp(celery, [
            celery, "-A", "pipeline.app", "worker",
            "--loglevel=info", f"--concurrency={concurrency}",
            "-Q", "drama",
            "--pool=threads",
            f"--logfile={log_file}",
        ])

    @cli.command()
    def status() -> None:
        """检查所有服务状态"""
        from cli import _load_env
        _load_env()

        table = Table(title="🎬 服务状态", show_lines=True)
        table.add_column("服务", style="cyan")
        table.add_column("状态", justify="center")
        table.add_column("端口/地址", justify="center")
        table.add_column("说明")

        from infra.network import port_ok, redis_port
        redis = port_ok(redis_port())
        table.add_row("Redis", "[green]✅[/green]" if redis else "[red]❌ 必选[/red]",
                       str(redis_port()), "任务队列（必选）")

        pg_ok, pg_addr, pg_reason = _check_postgres()
        table.add_row("PostgreSQL", "[green]✅[/green]" if pg_ok else "[red]❌ 必选[/red]",
                       pg_addr, "数据库（必选）" if pg_ok else pg_reason)

        celery_ok = _check_celery(redis)
        table.add_row("Celery Worker", "[green]✅[/green]" if celery_ok else "[red]❌ 未启动[/red]",
                       "-", "异步任务处理（必选）")

        from infra.config import Config as _Config
        from cli import _resolve_config
        cfg_path = _resolve_config()
        try:
            cfg = _Config(cfg_path).data
        except Exception:
            cfg = {}

        comfyui_ok, comfyui_url = _check_comfyui(cfg)
        table.add_row("ComfyUI", "[green]✅[/green]" if comfyui_ok else "[yellow]⚠[/yellow]",
                       comfyui_url, "图片/视频生成")

        from infra.config.registry import ModelRegistry as _MR
        try:
            _reg = _MR()
        except Exception:
            _reg = None
        _check_tts(cfg, _reg, table)

        llm_ok, llm_backend, llm_base_url, llm_enabled = _check_llm(cfg)
        if not llm_enabled:
            table.add_row(f"LLM ({llm_backend})", "[yellow]⚠ 未启用[/yellow]",
                           llm_base_url or "-", "AI 生成（在 project.yaml 中设置 llm.enabled: true）")
        else:
            table.add_row(f"LLM ({llm_backend})", "[green]✅[/green]" if llm_ok else "[red]❌ 连接失败[/red]",
                           llm_base_url, "AI 内容生成")

        console.print(table)
        _print_status_warnings(redis, celery_ok, llm_enabled, llm_ok, llm_base_url)

    @cli.command()
    def env() -> None:
        """显示环境信息"""
        import platform
        from infra.compute.gpu import get_generation_config
        gen = get_generation_config()
        from cli import _load_env
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
        from infra.network import port_ok, redis_port
        console.print(f"[cyan]Redis:[/cyan]  {'✅ 运行中' if port_ok(redis_port()) else '❌ 未运行'}")
        pg_dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
        if pg_dsn:
            try:
                import psycopg2
                conn = psycopg2.connect(pg_dsn, connect_timeout=3)
                conn.close()
                console.print(f"[cyan]PG:[/cyan]     ✅ {pg_dsn.split('@')[-1]}")
            except Exception:
                console.print("[cyan]PG:[/cyan]     ❌ 连接失败")
        else:
            console.print("[cyan]PG:[/cyan]     ❌ 未配置 AI_DRAMA_DB_DSN")
        try:
            from infra.config import get_active_project_dir, ProjectPaths
            from cli import ROOT
            active = get_active_project_dir(ROOT)
            cfg_file = ProjectPaths(active).project_yaml
            if cfg_file.exists():
                from infra.config import load_yaml_full
                data = load_yaml_full(cfg_file)
                proj_name = data.get("project", {}).get("name", active.name)
            else:
                proj_name = active.name
            console.print(f"[cyan]项目:[/cyan]   {proj_name} ({active})")
        except Exception:
            console.print("[cyan]项目:[/cyan]   未设置")

    @cli.command()
    @click.option("--index-only", is_flag=True, help="跳过克隆/复制，直接扫描已有 WAV 生成索引")
    def voices(index_only) -> None:
        """🎤 声线库同步（克隆仓库 + 生成索引）"""
        from scripts.voice_sync import sync_voices
        from infra.config import get_voices_dir
        target_dir = get_voices_dir()
        if index_only:
            console.print(f"\n[cyan]🎤 扫描已有 WAV 生成索引...[/cyan]\n")
        else:
            console.print(f"\n[cyan]🎤 同步声线库到 {target_dir}...[/cyan]\n")
        try:
            result = sync_voices(target_dir, index_only=index_only)
            console.print(f"[green]✅ 完成: {result['count']} 个声线 → {result['index_path']}[/green]")
        except Exception as e:
            console.print(f"[red]❌ 失败: {e}[/red]")
            sys.exit(1)

    @cli.command()
    @click.option("--insightface", "insightface_", is_flag=True, help="预下载 InsightFace buffalo_l 人脸检测模型")
    def setup(insightface_) -> None:
        """⚙️  一次性环境预配置（预下载模型等）"""
        if not insightface_:
            console.print("[yellow]请指定选项，例如: drama setup --insightface[/yellow]")
            return

        if insightface_:
            _setup_insightface()

    @cli.command()
    @click.option("--logs", is_flag=True)
    @click.option("--cache", is_flag=True)
    @click.option("--yes", "-y", is_flag=True, help="跳过确认")
    def clean(logs, cache, yes):
        """清理日志和缓存"""
        from infra.config import REPO_LOGS_DIR
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
            from cli import ROOT
            for d in [ROOT / ".pytest_cache", ROOT / "__pycache__"]:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            console.print("[green]✅ 缓存已清理[/green]")
        if not logs and not cache:
            console.print("[yellow]请指定: --logs 或 --cache[/yellow]")


# ── 内部辅助函数 ──────────────────────────────────

def _check_postgres() -> tuple[bool, str, str]:
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        return False, "未配置", "未配置"
    try:
        import psycopg2
    except ImportError:
        return False, "未配置", "psycopg2 未安装"
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        # 脱敏显示：只保留 @ 后面的部分
        addr = dsn.split("@")[-1] if "@" in dsn else "已配置"
        return True, addr, ""
    except psycopg2.OperationalError as e:
        msg = str(e).strip()
        addr = dsn.split("@")[-1] if "@" in dsn else "已配置"
        return False, addr, msg[:80]
    except Exception as e:
        addr = dsn.split("@")[-1] if "@" in dsn else "已配置"
        return False, addr, f"{type(e).__name__}: {str(e)[:60]}"


def _check_celery(redis_ok: bool) -> bool:
    if not redis_ok:
        return False
    try:
        from pipeline.app import app
        insp = app.control.inspect(timeout=2)
        return bool(insp.active())
    except Exception:
        return False


def _check_comfyui(cfg: dict) -> tuple[bool, str]:
    url = cfg.get("comfyui", {}).get("url", "")
    if not url:
        return False, ""
    try:
        from infra.http_pool import get_fast_client, auth_headers
        api_key = cfg.get("comfyui", {}).get("api_key", "")
        headers = auth_headers(api_key, content_type="") if api_key else {}
        r = get_fast_client().get(f"{url}/system_stats", headers=headers)
        return r.status_code == 200, url
    except Exception:
        return False, url


def _check_llm(cfg: dict) -> tuple[bool, str, str, bool]:
    llm_cfg = cfg.get("llm", {})
    enabled = llm_cfg.get("enabled", False)
    backend = llm_cfg.get("backend", "openai")
    base_url = llm_cfg.get("base_url", "")
    if not enabled:
        return False, backend, base_url, False
    if not base_url:
        return False, backend, base_url, True
    from infra.toolcheck import ping_openai_chat
    ok, _ = ping_openai_chat(base_url, api_key=llm_cfg.get("api_key", ""),
                             model=llm_cfg.get("model", ""), env_key="LLM_API_KEY")
    return ok, backend, base_url, True


def _check_tts(cfg: dict, reg, table: Table):
    from infra.config import cfg_get
    tts = cfg.get("models", {}).get("tts_backend")
    if not tts:
        table.add_row("TTS", "[yellow]⚠ 未配置后端[/yellow]", "-", "语音合成")
        return
    if not reg:
        table.add_row(f"TTS ({tts})", "[yellow]⚠ 注册表不可用[/yellow]", "-", "语音合成")
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
        api_url = cfg_get(cfg, hc.get("config_key", ""), "")
        table.add_row(f"TTS ({tts})", "[green]✅[/green]" if api_url else "[yellow]⚠ 未配置[/yellow]",
                       api_url or "-", "语音合成")


def _print_status_warnings(redis, celery_ok, llm_enabled, llm_ok, llm_base_url):
    if not redis or not celery_ok:
        console.print("\n[red]⚠ Redis 和 Celery Worker 是必选依赖[/red]")
    if llm_enabled and not llm_ok:
        console.print("\n[yellow]⚠ LLM 已启用但连接失败[/yellow]")
        console.print(f"  检查地址: {llm_base_url}")


# ── setup 子功能 ──────────────────────────────────

def _setup_insightface():
    """预下载 InsightFace buffalo_l 人脸检测模型（避免 worker 任务中极慢下载）"""
    from pathlib import Path

    model_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    if model_dir.exists() and any(model_dir.iterdir()):
        console.print(f"[green]✅ InsightFace buffalo_l 模型已存在: {model_dir}[/green]")
        return

    console.print("[cyan]⬇  正在下载 InsightFace buffalo_l 人脸检测模型...[/cyan]")
    console.print("[dim]（注意：从 GitHub 下载约 275MB，速度可能较慢，请耐心等待）[/dim]")

    try:
        from insightface.app import FaceAnalysis
    except ImportError:
        console.print("[red]❌ insightface 未安装。pip install insightface[/red]")
        sys.exit(1)

    try:
        # 触发 insightface 自动下载（下载+解压到 ~/.insightface/models/buffalo_l）
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        console.print(f"[green]✅ InsightFace buffalo_l 预下载完成: {model_dir}[/green]")
        for f in sorted(model_dir.iterdir()):
            console.print(f"     {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception as e:
        console.print(f"[red]❌ 下载失败: {e}[/red]")
        console.print("[dim]可手动下载: https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip[/dim]")
        console.print(f"[dim]解压到: {model_dir}[/dim]")
        sys.exit(1)