"""CLI AI 生成命令 — generate 组（storyboard / characters / scenes / bible / all）"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from cli import config_option

console = Console()


def _read_outline(outline: str | None, text: str | None) -> str:
    """读取大纲文本（--outline 文件 或 --text 直接输入）"""
    if text and outline:
        console.print("[red]❌ --outline 和 --text 不能同时使用[/red]")
        sys.exit(1)
    if text:
        return text
    if outline:
        p = Path(outline)
        if not p.exists():
            console.print(f"[red]❌ 文件不存在: {outline}[/red]")
            sys.exit(1)
        return p.read_text(encoding="utf-8")
    console.print("[yellow]请提供大纲: --outline <文件> 或 --text <文本>[/yellow]")
    sys.exit(1)


def _load_characters_and_scenes(cfg_file: str):
    """加载角色和场景数据"""
    from infra.config import ProjectPaths, load_yaml_entities
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    characters = load_yaml_entities(paths.characters_dir, "character")
    scenes = load_yaml_entities(paths.scenes_dir, "scene")
    return paths, characters, scenes


def _save_entities(entities: list[dict], entity_key: str, entity_dir: Path) -> int:
    """保存生成的实体到 YAML 文件，返回成功数"""
    from infra.config import save_yaml
    entity_dir.mkdir(parents=True, exist_ok=True)
    seen_ids = set()
    saved = 0
    for entity in entities:
        eid = entity.get("id", "unknown")
        if eid in seen_ids:
            console.print(f"[yellow]⚠ 跳过重复 id: {eid}[/yellow]")
            continue
        seen_ids.add(eid)
        path = entity_dir / f"{eid}.yaml"
        save_yaml(path, {entity_key: entity})
        console.print(f"  ✅ {entity.get('name', '?')} ({eid}) → {path.name}")
        saved += 1
    return saved


def _cmd_storyboard(episode, outline, text, duration, config_path, append):
    """📝 从剧情大纲生成分镜表"""
    from cli import _get_llm, _print_shots_preview
    outline_text = _read_outline(outline, text)
    if not outline_text.strip():
        console.print("[red]❌ 大纲为空[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.llm_generator import generate_storyboard, StoryboardGenParams
    paths, characters, scenes = _load_characters_and_scenes(cfg_file)

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

    from engines.storyboard import save_storyboard, append_storyboard
    if append:
        append_storyboard(shots, episode)
    else:
        save_storyboard(shots, episode)

    total_sec = sum(int(s.get("duration", 4)) for s in shots)
    console.print(f"\n[bold green]✅ 生成完成！[/bold green]")
    console.print(f"  镜头数: {len(shots)}")
    console.print(f"  总时长: {total_sec} 秒 ({total_sec/60:.1f} 分钟)")
    _print_shots_preview(shots)


def _cmd_characters(desc, config_path):
    """👤 从描述生成角色配置"""
    from cli import _get_llm
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

    from infra.config import ProjectPaths
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    saved = _save_entities(chars, "character", paths.characters_dir)
    console.print(f"\n[bold green]✅ 生成 {saved} 个角色[/bold green]")


def _cmd_scenes(desc, config_path):
    """🏔️ 从描述生成场景配置"""
    from cli import _get_llm
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

    from infra.config import ProjectPaths
    paths = ProjectPaths(Path(cfg_file).parent.parent)
    saved = _save_entities(scene_list, "scene", paths.scenes_dir)
    console.print(f"\n[bold green]✅ 生成 {saved} 个场景[/bold green]")


def _cmd_bible(config_path, outline):
    """📖 为所有角色生成角色圣经（Character Bible）"""
    from cli import _get_llm
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


def _cmd_all(episode, outline, duration, config_path):
    """🚀 一键生成：大纲 → 角色 + 场景 + 分镜"""
    from cli import _get_llm, _print_shots_preview
    p = Path(outline)
    if not p.exists():
        console.print(f"[red]❌ 文件不存在: {outline}[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)
    outline_text = p.read_text(encoding="utf-8")

    console.print(f"\n[bold cyan]━━━ AI 全量生成 第{episode}集 ━━━[/bold cyan]\n")

    from engines.llm_generator import generate_storyboard, StoryboardGenParams
    paths, characters, scenes = _load_characters_and_scenes(cfg_file)

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


def register_generate_commands(cli):
    """注册 generate 命令组到主 CLI 组"""

    @cli.group()
    def generate():
        """🤖 AI 内容生成（需要 LLM 服务）"""
        pass

    @generate.command("storyboard")
    @click.argument("episode", type=int, default=1)
    @click.option("-o", "--outline", default=None, help="大纲文件路径（txt/md）")
    @click.option("--text", default=None, help="直接输入大纲文本")
    @click.option("-d", "--duration", type=int, default=90, help="目标时长（秒，默认 90）")
    @config_option
    @click.option("--append", is_flag=True, help="追加到现有分镜表（不覆盖）")
    def gen_storyboard(episode, outline, text, duration, config_path, append):
        """📝 从剧情大纲生成分镜表"""
        _cmd_storyboard(episode, outline, text, duration, config_path, append)

    @generate.command("characters")
    @click.option("-d", "--desc", multiple=True, required=True, help="角色描述（可多次指定）")
    @config_option
    def gen_characters(desc, config_path):
        """👤 从描述生成角色配置"""
        _cmd_characters(desc, config_path)

    @generate.command("scenes")
    @click.option("-d", "--desc", multiple=True, required=True, help="场景描述（可多次指定）")
    @config_option
    def gen_scenes(desc, config_path):
        """🏔️ 从描述生成场景配置"""
        _cmd_scenes(desc, config_path)

    @generate.command("bible")
    @config_option
    @click.option("--outline", default=None, help="剧情大纲文件（用于推断人际关系）")
    def gen_bible(config_path, outline):
        """📖 为所有角色生成角色圣经（Character Bible）"""
        _cmd_bible(config_path, outline)

    @generate.command("all")
    @click.argument("episode", type=int, default=1)
    @click.option("-o", "--outline", required=True, help="大纲文件路径")
    @click.option("-d", "--duration", type=int, default=90, help="目标时长（秒）")
    @config_option
    def gen_all(episode, outline, duration, config_path):
        """🚀 一键生成：大纲 → 角色 + 场景 + 分镜"""
        _cmd_all(episode, outline, duration, config_path)
