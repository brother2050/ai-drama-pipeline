"""测试共享配置 — fixtures + 环境检测"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 环境检测 ──

_has_dsn = bool(os.environ.get("AI_DRAMA_DB_DSN", ""))


def has_postgres() -> bool:
    """检测 PostgreSQL 是否可用"""
    if not _has_dsn:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["AI_DRAMA_DB_DSN"], connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


# ── pytest markers ──

def pytest_configure(config):
    config.addinivalue_line("markers", "db: 需要 PostgreSQL 数据库")
    config.addinivalue_line("markers", "slow: 慢速测试")


# ── 共享 fixtures ──

@pytest.fixture
def test_project_dir(tmp_path):
    """创建临时项目目录（含最小配置）"""
    import yaml
    proj = tmp_path / "projects" / "default"
    proj.mkdir(parents=True)
    config_dir = proj / "config"
    config_dir.mkdir()
    (config_dir / "characters").mkdir()
    (config_dir / "scenes").mkdir()
    (proj / "assets").mkdir()
    (proj / "output").mkdir()

    cfg = {
        "project": {"name": "测试项目", "episodes": 1, "fps": 24, "style": "cinematic", "genre": "urban"},
        "models": {"tts_backend": "mimo-voicedesign", "image_backend": "cosmos", "video_backend": "cosmos-video"},
        "comfyui": {"url": "http://127.0.0.1:8188"},
    }
    (config_dir / "project.yaml").write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return proj


@pytest.fixture
def db_pool():
    """PostgreSQL 连接池（未配置 DSN 时跳过）"""
    if not has_postgres():
        pytest.skip("AI_DRAMA_DB_DSN 未配置或不可达")
    from infra.database.pool import get_pool
    return get_pool()
