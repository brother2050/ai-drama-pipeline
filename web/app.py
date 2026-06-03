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
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logger.info("🎬 AI 短剧工作台 v2 已启动")
    yield
    try:
        from infra.database.pool import get_pool
        get_pool().close()
    except Exception:
        logger.debug("数据库连接池关闭")
    logger.info("🎬 工作台已关闭")


def _add_cors(app: FastAPI) -> None:
    allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["*"], allow_headers=["*"])


def _add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理异常: {request.method} {request.url.path} — {exc}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"detail": f"服务器内部错误: {type(exc).__name__}: {str(exc)}"})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "校验失败").split("(")[0].strip() if "should" in err.get("msg", "").lower() else err.get("msg", "校验失败")
            errors.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse(status_code=422, content={"detail": "; ".join(errors)})
