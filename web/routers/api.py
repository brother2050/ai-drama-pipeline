"""API 路由 — 聚合入口（按领域拆分为子模块）

子模块:
- system_tools.py — 系统状态 / 工具管理 / 配置 / 单步执行 / 任务查询
- characters.py   — 角色 CRUD + 定妆照生成
- scenes.py       — 场景 CRUD + 场景图生成
- storyboard.py   — 分镜表 / 集数 / 管线 / LLM 生成 / 文件预览
- assets.py       — 资产上传/下载/共享库
- imports.py      — 项目管理 / 导入 / Seko / 训练
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# 按领域注册子路由（prefix 为空，各子模块的路由已包含完整路径）
from web.routers.system_tools import router as system_tools_router  # noqa: E402
from web.routers.characters import router as characters_router  # noqa: E402
from web.routers.scenes import router as scenes_router  # noqa: E402
from web.routers.storyboard import router as storyboard_router  # noqa: E402
from web.routers.assets import router as assets_router  # noqa: E402
from web.routers.imports import router as imports_router  # noqa: E402
from web.routers.voices import router as voices_router  # noqa: E402

router.include_router(system_tools_router)
router.include_router(characters_router)
router.include_router(scenes_router)
router.include_router(storyboard_router)
router.include_router(assets_router)
router.include_router(imports_router)
router.include_router(voices_router)
