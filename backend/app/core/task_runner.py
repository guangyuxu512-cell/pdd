from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Callable

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import engine
from app.models import Shop, Task, TaskLog, TaskStatus

TaskHandler = Callable[[Session, Task], dict[str, Any]]


class TaskRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.executor = ThreadPoolExecutor(max_workers=self.settings.max_task_workers)
        self.futures: dict[int, Future[None]] = {}
        self.shop_locks: set[str] = set()
        self.lock = Lock()
        self.handlers: dict[str, TaskHandler] = {}

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self.handlers[task_type] = handler

    def dispatch_pending(self, limit: int | None = None) -> list[int]:
        dispatched: list[int] = []
        requested_slots = limit or self.settings.max_task_workers
        with self.lock:
            active_count = len(self.futures)
        slots = min(requested_slots, max(self.settings.max_task_workers - active_count, 0))
        if slots <= 0:
            return dispatched

        with Session(engine) as session:
            statement = (
                select(Task)
                .where(Task.status == TaskStatus.PENDING)
                .order_by(Task.priority, Task.next_run_at, Task.created_at)
                .limit(slots * 4)
            )
            tasks = session.exec(statement).all()
            for task in tasks:
                if len(dispatched) >= slots:
                    break
                if not self._can_dispatch(session, task):
                    continue
                self._mark_running(session, task)
                future = self.executor.submit(self._run_task, task.id)
                with self.lock:
                    self.futures[task.id or 0] = future
                    self.shop_locks.add(self._shop_lock_key(task.platform, task.shop_id))
                dispatched.append(task.id or 0)
        return dispatched

    def _can_dispatch(self, session: Session, task: Task) -> bool:
        if task.next_run_at and task.next_run_at > datetime.now():
            return False
        shop = session.exec(
            select(Shop).where(Shop.platform == task.platform, Shop.shop_id == task.shop_id)
        ).first()
        if not shop or not shop.enabled:
            return False
        if shop.cookie_status == "invalid":
            task.status = TaskStatus.WAITING_LOGIN
            task.error_message = "cookie invalid"
            session.add(task)
            session.commit()
            return False
        with self.lock:
            return self._shop_lock_key(task.platform, task.shop_id) not in self.shop_locks

    def _mark_running(self, session: Session, task: Task) -> None:
        now = datetime.now()
        task.status = TaskStatus.RUNNING
        task.started_at = now
        task.locked_at = now
        task.lock_expired_at = now + timedelta(minutes=30)
        task.updated_at = now
        session.add(task)
        session.add(
            TaskLog(
                task_id=task.id or 0,
                platform=task.platform,
                shop_id=task.shop_id,
                message="任务开始执行",
            )
        )
        session.commit()

    def _run_task(self, task_id: int | None) -> None:
        if not task_id:
            return
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            try:
                handler = self.handlers.get(task.task_type, self._default_handler)
                result = handler(session, task)
                task.status = result.get("status", TaskStatus.SUCCESS)
                task.result_json = result
                task.error_message = None
                session.add(
                    TaskLog(
                        task_id=task.id or 0,
                        platform=task.platform,
                        shop_id=task.shop_id,
                        message="任务执行完成",
                        context_json=result,
                    )
                )
            except Exception as exc:
                task.retry_count += 1
                task.error_message = str(exc)
                task.status = TaskStatus.FAILED
                if task.retry_count <= task.max_retries:
                    task.status = TaskStatus.PENDING
                    task.next_run_at = datetime.now() + timedelta(minutes=task.retry_count * 2)
                session.add(
                    TaskLog(
                        task_id=task.id or 0,
                        platform=task.platform,
                        shop_id=task.shop_id,
                        level="error",
                        message="任务执行失败",
                        context_json={"error": str(exc), "retry_count": task.retry_count},
                    )
                )
            finally:
                task.finished_at = datetime.now()
                task.locked_at = None
                task.lock_expired_at = None
                task.updated_at = datetime.now()
                session.add(task)
                session.commit()
                with self.lock:
                    self.futures.pop(task_id, None)
                    self.shop_locks.discard(self._shop_lock_key(task.platform, task.shop_id))

    def _default_handler(self, session: Session, task: Task) -> dict[str, Any]:
        return {
            "status": TaskStatus.SUCCESS,
            "message": "任务已由淘宝工具箱默认处理器完成",
            "task_type": task.task_type,
            "payload": task.payload_json,
        }

    @staticmethod
    def _shop_lock_key(platform: str, shop_id: str) -> str:
        return f"{platform}:{shop_id}"


task_runner = TaskRunner()
