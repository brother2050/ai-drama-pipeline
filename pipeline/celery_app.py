"""Celery 应用配置 — 异步任务队列核心"""
from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import task_failure

logger = logging.getLogger(__name__)

broker = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
backend = os.environ.get("REDIS_BACKEND_URL", broker.replace("/0", "/1"))

app = Celery("drama", broker=broker, backend=backend,
             include=["pipeline.tasks"])

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
