"""Celery 应用配置 — 异步任务队列核心"""
from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import task_failure
from celery import Task as _CeleryTask

logger = logging.getLogger(__name__)


class _SuppressDefaultSuccess(logging.Filter):
    """过滤 Celery 默认的成功日志（含高精度 runtime），由 DramaTask 替代

    Celery 格式: "Task <name>[<uuid>] succeeded in <float>s: <result>"
    DramaTask 格式: "Task <uuid> succeeded in <float>s: <result>"
    匹配关键词 '[…] succeeded in' 即可精确区分。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Celery 默认日志含 [uuid] 方括号，DramaTask 不含
        return "] succeeded in" not in msg


class DramaTask(_CeleryTask):
    """自定义 Task 基类 — 统一成功日志格式（耗时 3 位小数）"""

    def on_success(self, retval, task_id, args, kwargs):
        super().on_success(retval, task_id, args, kwargs)
        runtime = getattr(self.request, "runtime", None)
        if runtime is not None:
            logger.info(f"Task {task_id} succeeded in {runtime:.3f}s: {retval}")
        else:
            logger.info(f"Task {task_id} succeeded: {retval}")


# 抑制 Celery 默认的成功日志（DramaTask 已替代，避免重复输出）
logging.getLogger("celery.worker.request").addFilter(_SuppressDefaultSuccess())

def _redis_url() -> str:
    """读取 Redis URL：环境变量 > system.yaml > 默认值"""
    url = os.environ.get("REDIS_URL", "")
    if url:
        return url
    try:
        from infra.config import load_config
        from infra.config.core import SYSTEM_CONFIG_PATH
        system = load_config(SYSTEM_CONFIG_PATH, safe=True) or {}
        url = system.get("redis", {}).get("url", "")
        if url:
            return url
    except Exception:
        pass
    return "redis://localhost:6379/0"


broker = _redis_url()
backend = os.environ.get("REDIS_BACKEND_URL", _redis_url().replace("/0", "/1"))

app = Celery("drama", broker=broker, backend=backend,
             include=["pipeline.tasks"],
             task_cls=DramaTask)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # 完成后才 ack，worker 崩溃时任务自动重入队
    task_reject_on_worker_lost=True,  # 配合 acks_late，崩溃时 reject 而非 ack
    # 幂等性保证：DB 操作全部用 upsert；分镜按集覆盖；文件生成前检查已有文件；
    # _prepare 用 advisory lock 防并发。因此重试安全。
    worker_prefetch_multiplier=1,
    task_soft_time_limit=3600,
    task_time_limit=3900,
    result_expires=86400,
    task_default_queue="drama",
    # 所有 pipeline 任务统一分发到 drama 队列（由 task_default_queue 控制），
    # 无需逐个声明 task_routes。新增任务只需 include 到上方 include 列表。
)


# 全局失败回调 — 所有任务失败时自动记录日志
@task_failure.connect
def _on_task_failure(sender, task_id, exception, traceback, einfo, **kwargs):
    logger.error(f"任务失败: {task_id} ({sender.name}): {exception} ({type(exception).__name__})", exc_info=True)


# 注册 Celery 健康检查钩子：infra/toolcheck 通过 hooks 系统检查 Worker 状态
try:
    from infra.hooks import on_health_check

    @on_health_check(service_type="celery")
    def _check_celery_worker(name: str = "", cfg: dict = None) -> dict:
        try:
            insp = app.control.inspect(timeout=2)
            ok = bool(insp.active())
            return {"available": ok, "reason": "" if ok else "Celery Worker 未启动"}
        except Exception as e:
            return {"available": False, "reason": f"Celery 连接失败: {e}"}
except ImportError:
    pass
