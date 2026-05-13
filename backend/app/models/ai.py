from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class AIPromptTemplate(SQLModel, table=True):
    __tablename__ = "ai_prompt_template"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=128)
    scene: str = Field(index=True, max_length=64)
    version: str = Field(max_length=32)
    prompt_text: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AIModelConfig(SQLModel, table=True):
    __tablename__ = "ai_model_config"

    id: int | None = Field(default=None, primary_key=True)
    provider: str = Field(index=True, max_length=64)
    model_name: str = Field(max_length=128)
    base_url: str | None = Field(default=None, max_length=500)
    api_key_name: str | None = Field(default=None, max_length=128)
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AITask(SQLModel, table=True):
    __tablename__ = "ai_task"

    id: int | None = Field(default=None, primary_key=True)
    scene: str = Field(index=True, max_length=64)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True, max_length=32)
    model_name: str | None = Field(default=None, max_length=128)
    prompt_version: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None


class AIResult(SQLModel, table=True):
    __tablename__ = "ai_result"

    id: int | None = Field(default=None, primary_key=True)
    ai_task_id: int = Field(index=True)
    result_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    summary: str | None = None
    confidence: float | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class AIAnalyzeGoodsRequest(SQLModel):
    payload: dict[str, Any]


class AIExplainErrorRequest(SQLModel):
    request_log: dict[str, Any]
    response_log: dict[str, Any]


class AISuggestCleanupRequest(SQLModel):
    goods_stats: list[dict[str, Any]]
