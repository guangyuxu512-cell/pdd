from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class RequestLog(SQLModel, table=True):
    __tablename__ = "request_log"

    id: int | None = Field(default=None, primary_key=True)
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    shop_name: str | None = Field(default=None, max_length=255)
    account_id: str | None = Field(default=None, index=True, max_length=128)
    profile_id: str | None = Field(default=None, index=True, max_length=128)
    worker_id: str | None = Field(default=None, index=True, max_length=128)
    task_id: int | None = Field(default=None, index=True)
    method: str = Field(max_length=16)
    url: str = Field(max_length=1000)
    status_code: int | None = Field(default=None, index=True)
    request_headers_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    request_body_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    response_headers_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    response_body_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)


class TaskLog(SQLModel, table=True):
    __tablename__ = "task_log"

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(index=True)
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    level: str = Field(default="info", max_length=32)
    message: str
    context_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now, index=True)
