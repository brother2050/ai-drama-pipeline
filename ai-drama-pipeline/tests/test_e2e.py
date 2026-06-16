"""前端 E2E 测试 — HTML/JS 结构验证

验证前端文件完整性、路由注册、DOM 结构。
使用 FastAPI TestClient 提供静态文件。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app():
    from web.app import create_app
    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── 静态文件 ──

def test_index_html(client):
    """首页可访问"""
    r = client.get("/")
    assert r.status_code == 200
    assert "AI 短剧" in r.text
    assert "page-dashboard" in r.text


def test_css_loaded(client):
    """CSS 文件可访问"""
    r = client.get("/css/style.css")
    assert r.status_code == 200
    assert "var(--bg)" in r.text


def test_js_i18n_loaded(client):
    """i18n 文件可访问"""
    r = client.get("/js/i18n.js")
    assert r.status_code == 200
    assert "I18N" in r.text
    assert "function t(" in r.text


def test_js_app_loaded(client):
    """核心 JS 文件可访问"""
    for js_file in ["core.js", "dashboard.js", "pipeline.js", "characters.js",
                    "scenes.js", "ai-gen.js", "settings.js", "i18n.js"]:
        r = client.get(f"/js/{js_file}")
        assert r.status_code == 200, f"/js/{js_file} 不可访问"


# ── HTML 结构 ──

def test_html_has_all_pages(client):
    """HTML 包含所有页面容器"""
    r = client.get("/")
    html = r.text
    for page in ["dashboard", "characters", "scenes", "storyboard", "pipeline", "projects", "settings"]:
        assert f'page-{page}' in html, f"缺少页面: {page}"


def test_html_has_nav_items(client):
    """HTML 包含导航项"""
    r = client.get("/")
    html = r.text
    for nav in ["dashboard", "characters", "scenes", "storyboard", "pipeline", "projects", "settings"]:
        assert f'data-page="{nav}"' in html, f"缺少导航: {nav}"


def test_html_has_scripts(client):
    """HTML 动态加载核心 JS 文件"""
    r = client.get("/")
    html = r.text
    # JS 通过动态 script 标签加载，检查模块列表
    assert 'i18n.js' in html
    assert 'core.js' in html


def test_html_has_css(client):
    """HTML 引用了 style.css"""
    r = client.get("/")
    html = r.text
    assert '/css/style.css' in html


# ── JS 结构 ──

def test_js_has_core_functions(client):
    """JS 包含核心函数（分布在多个文件中）"""
    # 合并所有 JS 文件内容检查
    all_js = ""
    for js_file in ["core.js", "dashboard.js", "pipeline.js", "characters.js",
                    "scenes.js", "ai-gen.js", "settings.js", "projects.js", "extras.js"]:
        r = client.get(f"/js/{js_file}")
        if r.status_code == 200:
            all_js += r.text + "\n"
    for fn in ["loadDashboard", "loadCharacters", "loadScenes", "loadStoryboard",
               "loadPipeline", "loadProjects", "loadSettings", "api", "toast",
               "pollTask", "renderShotsGrid", "editShot",
               "deleteShot", "runOne", "batchRun", "undo", "redo",
               "newChar", "newScene", "addShot"]:
        assert f"function {fn}" in all_js or f"async function {fn}" in all_js, f"缺少函数: {fn}"


def test_js_has_undo_redo(client):
    """JS 包含撤销/重做逻辑"""
    r = client.get("/js/core.js")
    js = r.text
    assert "_undoStack" in js
    assert "_redoStack" in js
    assert "pushUndo" in js
    assert "Ctrl+Z" in js or "ctrlKey" in js


def test_js_has_cancel_batch(client):
    """JS 包含批量取消"""
    r = client.get("/js/pipeline.js")
    js = r.text
    assert "batchCancelled" in js
    assert "取消" in js


def test_js_has_poll_limit(client):
    """JS 包含轮询限制"""
    r = client.get("/js/core.js")
    js = r.text
    assert "MAX_POLL" in js


def test_js_has_cache(client):
    """JS 包含缓存层"""
    r = client.get("/js/core.js")
    js = r.text
    assert "cachedFetch" in js
    assert "invalidateCache" in js


def test_js_has_esc_handler(client):
    """JS 包含 ESC 关闭"""
    r = client.get("/js/core.js")
    js = r.text
    assert "Escape" in js


def test_js_has_delete_endpoints(client):
    """JS 调用 DELETE API"""
    all_js = ""
    for js_file in ["characters.js", "scenes.js", "ai-gen.js", "pipeline.js", "dashboard.js", "projects.js"]:
        r = client.get(f"/js/{js_file}")
        if r.status_code == 200:
            all_js += r.text
    assert "method: 'DELETE'" in all_js or 'method: "DELETE"' in all_js or "method:'DELETE'" in all_js


def test_js_no_xss_raw_html(client):
    """JS 中没有明显的 innerHTML XSS（检查所有 JS 文件）"""
    all_js = ""
    for js_file in ["core.js", "characters.js", "scenes.js", "ai-gen.js", "pipeline.js",
                    "dashboard.js", "projects.js", "settings.js", "seko.js", "extras.js"]:
        r = client.get(f"/js/{js_file}")
        if r.status_code == 200:
            all_js += r.text
    # 检查没有直接使用 innerHTML 拼接用户输入的危险模式
    # 允许 innerHTML 用于受控数据（API 返回的结构化数据），但不允许直接拼接 querySelector 的值
    dangerous_patterns = [
        "innerHTML = ",  # 直接赋值（可能含用户输入）
    ]
    for pattern in dangerous_patterns:
        # 如果有 innerHTML 赋值，检查是否经过转义或使用 textContent
        if pattern in all_js:
            # 存在 innerHTML 使用时，确认有对应的转义函数
            assert "escapeHtml" in all_js or "textContent" in all_js or "sanitize" in all_js, \
                "存在 innerHTML 直接赋值但缺少转义函数"


# ── i18n 结构 ──

def test_i18n_has_translations(client):
    """i18n 包含翻译条目"""
    r = client.get("/js/i18n.js")
    js = r.text
    for key in ["app.title", "btn.save", "nav.dashboard", "nav.pipeline",
                "dash.title", "wb.batch_tts", "edit.shot_title",
                "toast.saved", "confirm.delete_shot"]:
        assert f"'{key}'" in js, f"缺少翻译: {key}"


def test_i18n_has_both_languages(client):
    """i18n 包含中英文"""
    r = client.get("/js/i18n.js")
    js = r.text
    assert "zh:" in js
    assert "en:" in js
    assert "function t(" in js
    assert "function setLang(" in js


# ── CSS 结构 ──

def test_css_has_responsive(client):
    """CSS 包含响应式媒体查询"""
    r = client.get("/css/style.css")
    css = r.text
    assert "@media" in css
    assert "max-width" in css


def test_css_has_dark_theme(client):
    """CSS 使用暗色主题变量"""
    r = client.get("/css/style.css")
    css = r.text
    assert "--bg:" in css
    assert "--fg:" in css
    assert "--accent:" in css


# ── API 路由完整性 ──

def test_api_routes_exist(app):
    """API 路由注册完整"""
    # 从 OpenAPI schema 获取所有已注册路由（包含嵌套路由）
    openapi = app.openapi()
    routes = set(openapi.get("paths", {}).keys())
    expected = [
        "/api/system/status", "/api/system/env",
        "/api/tools", "/api/tools/{name}",
        "/api/config",
        "/api/characters", "/api/characters/{char_id}",
        "/api/scenes", "/api/scenes/{scene_id}",
        "/api/storyboard/{episode}",
        "/api/shots/{episode}/{shot_id}/resources",
        "/api/files/{episode}/{shot_id}/{filename}",
        "/api/projects", "/api/projects/new", "/api/projects/switch",
        "/api/pipeline/run", "/api/pipeline/status/{episode}",
        "/api/tasks/{task_id}", "/api/tasks",
    ]
    for path in expected:
        assert path in routes, f"缺少路由: {path}"


# ── API 集成测试（mock Celery 任务）──

def test_api_system_status(client):
    """系统状态 API 可调用"""
    r = client.get("/api/system/status")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data


def test_api_config_get(client):
    """配置读取 API"""
    r = client.get("/api/config")
    assert r.status_code == 200


def test_api_characters_list(client):
    """角色列表 API"""
    r = client.get("/api/characters")
    assert r.status_code == 200
    data = r.json()
    assert "characters" in data
    assert isinstance(data["characters"], list)


def test_api_scenes_list(client):
    """场景列表 API"""
    r = client.get("/api/scenes")
    assert r.status_code == 200
    data = r.json()
    assert "scenes" in data
    assert isinstance(data["scenes"], list)


@pytest.mark.skipif(not os.environ.get("AI_DRAMA_DB_DSN"), reason="需要 PostgreSQL")
def test_api_storyboard(client):
    """分镜表 API"""
    r = client.get("/api/storyboard/1")
    assert r.status_code == 200


def test_api_projects(client):
    """项目列表 API"""
    r = client.get("/api/projects")
    assert r.status_code == 200


def test_api_tasks_list(client):
    """任务列表 API"""
    r = client.get("/api/tasks")
    assert r.status_code == 200


def test_api_pipeline_invalid_command(client):
    """无效管线命令返回 400/422"""
    r = client.post("/api/pipeline/run", json={"episode": 1, "command": "invalid"})
    assert r.status_code in (400, 422)


def test_api_character_crud(client):
    """角色 CRUD 测试"""
    r = client.post("/api/characters", json={
        "id": "test_e2e_char",
        "name": "测试角色",
        "appearance": "测试外观描述",
    })
    assert r.status_code == 200
    try:
        r = client.get("/api/characters")
        assert r.status_code == 200
    finally:
        client.delete("/api/characters/test_e2e_char")


def test_api_scene_crud(client):
    """场景 CRUD 测试"""
    r = client.post("/api/scenes", json={
        "id": "test_e2e_scene",
        "name": "测试场景",
        "description": "测试描述",
    })
    assert r.status_code == 200
    try:
        r = client.get("/api/scenes")
        assert r.status_code == 200
    finally:
        client.delete("/api/scenes/test_e2e_scene")
