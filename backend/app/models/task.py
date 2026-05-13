from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    WAITING_LOGIN = "waiting_login"
    WAITING_CAPTCHA = "waiting_captcha"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TaskBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    shop_name: str | None = Field(default=None, max_length=255)
    account_id: str | None = Field(default=None, index=True, max_length=128)
    profile_id: str | None = Field(default=None, index=True, max_length=128)
    worker_id: str | None = Field(default=None, index=True, max_length=128)
    task_type: str = Field(index=True, max_length=64)
    status: str = Field(default=TaskStatus.PENDING, index=True, max_length=32)
    priority: int = Field(default=100, index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    next_run_at: datetime | None = Field(default=None, index=True)
    locked_at: datetime | None = None
    lock_expired_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Task(TaskBase, TimestampMixin, table=True):
    __tablename__ = "task"

    id: int | None = Field(default=None, primary_key=True)


class TaskCreate(TaskBase):
    status: str = TaskStatus.PENDING


class TaskUpdate(SQLModel):
    status: str | None = None
    priority: int | None = None
    payload_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    retry_count: int | None = None
    max_retries: int | None = None
    next_run_at: datetime | None = None


class TaskRead(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
