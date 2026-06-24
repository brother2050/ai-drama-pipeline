"""FastAPI 应用工厂"""
from __future__ import annotations

import logging
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    from web.services import setup_logging
    from infra.config import REPO_LOGS_DIR
    log_dir = REPO_LOGS_DIR
    log_dir.mkdir(exist_ok=True)
    setup_logging(level="INFO", log_file=str(log_dir / "app.log"))

    app = FastAPI(title="AI 短剧工作台 v2", version="2.0", lifespan=_lifespan)
    _add_cors(app)
    _add_exception_handlers(app)

    from web.routers import api
    app.include_router(api.router, prefix="/api")

    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        # SPA 入口：根路径返回 index.html
        @app.get("/")
        async def serve_index():
            return FileResponse(str(static_dir / "index.html"))
        # 静态资源：/css, /js, /favicon.svg 等
        app.mount("/", StaticFiles(directory=str(static_dir)), name="static")
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logger.info("🎬 AI 短剧工作台 v2 已启动")
    # 启动时检查 emotion 映射同步
    from infra.constants import check_emotion_sync
    for w in check_emotion_sync():
        logger.warning(f"⚠ emotion 映射漂移: {w}")
    yield
    _shutdown()
    logger.info("🎬 工作台已关闭")


def _shutdown():
    """统一清理资源（按依赖顺序）"""
    cleanup_handlers = [
        ("线程池", lambda: __import__("web.routers.system_tools", fromlist=["_tool_executor"])._tool_executor.shutdown(wait=False)),
        ("数据库连接池", lambda: __import__("infra.database.pool", fromlist=["get_pool"]).get_pool().close()),
        ("全局资源", lambda: __import__("infra.globals", fromlist=["shutdown_globals"]).shutdown_globals()),
    ]
    for name, handler in cleanup_handlers:
        try:
            handler()
        except Exception as e:
            logger.debug(f"{name}关闭: {e}")


def _add_cors(app: FastAPI) -> None:
    default_origins = "http://localhost:8888,http://127.0.0.1:8888"
    allowed_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", default_origins).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=True,
    )


def _add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理异常: {request.method} {request.url.path} — {exc}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(loc_part) for loc_part in err.get("loc", []))
            msg = err.get("msg", "校验失败").split("(")[0].strip() if "should" in err.get("msg", "").lower() else err.get("msg", "校验失败")
            errors.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse(status_code=422, content={"detail": "; ".join(errors)})
