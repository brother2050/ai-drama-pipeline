"""声线库同步脚本 — 克隆 voices 仓库 + 生成索引

用法:
    python scripts/voice_sync.py [--dir /path/to/voices]

流程:
    1. 克隆/更新 voices 仓库（Git LFS）
    2. 复制 WAV 文件到 shared_assets/voices/
    3. 生成 voices.json 索引
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/brother2050/voices.git"
# 统一使用集中式路径工具
_DEFAULT_DIR = get_voices_dir()


def _get_repo_url() -> str:
    """从 system.yaml 读取 voices.repo_url，回退到环境变量或默认值"""
    try:
        from infra.config import load_config
        from infra.config.core import SYSTEM_CONFIG_PATH
        system = load_config(SYSTEM_CONFIG_PATH, safe=True) or {}
        return system.get("voices", {}).get("repo_url", "")
    except Exception:
        return ""


# 文件名模式: {序号}_{场景}_{声线}.wav
_NAME_RE = re.compile(r"^(\d+)_(.+?)_(.+?)\.wav$")


def sync_voices(target_dir: Path | None = None, repo_url: str = "", index_only: bool = False) -> dict:
    """同步声线库

    Args:
        target_dir: 目标目录（默认 shared_assets/voices/）
        repo_url: 仓库 URL（默认 brother2050/voices）
        index_only: True 时跳过克隆/复制，只生成索引

    Returns:
        {"status": "ok", "count": N, "index_path": "..."}
    """
    target_dir = target_dir or _DEFAULT_DIR
    repo_url = repo_url or _get_repo_url() or _REPO_URL
    target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    if not index_only:
        # 1. 克隆/更新仓库
        repo_dir = target_dir / ".repo"
        if (repo_dir / ".git").exists():
            logger.info(f"更新 voices 仓库...")
            _run_git(["-C", str(repo_dir), "pull", "--ff-only"])
        else:
            logger.info(f"克隆 voices 仓库...")
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            _run_git(["clone", repo_url, str(repo_dir)])

        # 2. 复制 WAV 文件
        logger.info(f"复制 WAV 文件到 {target_dir}...")
        for src in repo_dir.glob("*.wav"):
            dst = target_dir / src.name
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(str(src), str(dst))
                count += 1
        logger.info(f"复制了 {count} 个文件")

    # 3. 生成索引
    index_path = _build_index(target_dir)
    voice_count = len(json.loads(index_path.read_text(encoding="utf-8")).get("voices", []))

    return {"status": "ok", "count": voice_count, "index_path": str(index_path)}


def _build_index(voices_dir: Path) -> Path:
    """扫描 WAV 文件，生成 voices.json 索引（按序号数字排序）"""
    voices = []
    for wav in voices_dir.glob("*.wav"):
        m = _NAME_RE.match(wav.name)
        if m:
            voice_id, scene, style = m.group(1), m.group(2), m.group(3)
        else:
            voice_id = wav.stem
            scene, style = "", ""

        # 推断性别
        gender = _infer_gender(style)

        # 关键词
        keywords = []
        if scene:
            keywords.append(scene)
        if style:
            keywords.extend(_split_keywords(style))

        voices.append({
            "id": voice_id,
            "filename": wav.name,
            "scene": scene,
            "style": style,
            "gender": gender,
            "keywords": keywords,
        })

    # 按序号数字排序（001, 002, ..., 099, 100, ..., 1000）
    # 统一用 (0, int) 排数字, (1, str) 排非数字，避免 int/str 比较报错
    voices.sort(key=lambda v: (0, int(v["id"])) if v["id"].isdigit() else (1, v["id"]))

    index = {"version": 1, "voices": voices}
    index_path = voices_dir / "voices.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"索引已生成: {index_path} ({len(voices)} 条)")
    return index_path


def _infer_gender(style: str) -> str:
    """从声线描述推断性别"""
    male_keywords = {"男声", "男", "male", "boy", "man", "叔", "少年"}
    female_keywords = {"女声", "女", "female", "girl", "woman", "姐", "萝莉"}
    for kw in male_keywords:
        if kw in style:
            return "male"
    for kw in female_keywords:
        if kw in style:
            return "female"
    return ""


def _split_keywords(text: str) -> list[str]:
    """拆分关键词（按常见分隔符）"""
    parts = re.split(r"[_\s,，、/]+", text)
    return [p.strip() for p in parts if p.strip()]


def _run_git(args: list[str]) -> None:
    """执行 git 命令"""
    try:
        subprocess.run(["git"] + args, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("git 未安装，请先安装 git")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git 命令失败: {e.stderr.strip()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = sync_voices()
    print(f"✅ 同步完成: {result['count']} 个声线 → {result['index_path']}")
