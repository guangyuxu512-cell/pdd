from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class CaptchaStatus:
    CREATED = "created"
    WAITING = "waiting"
    SOLVING = "solving"
    SOLVED = "solved"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class CaptchaChallengeBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    task_id: int | None = Field(default=None, index=True)
    scene: str = Field(max_length=64)
    captcha_type: str = Field(default="manual", max_length=64)
    provider: str = Field(default="manual", index=True, max_length=64)
    status: str = Field(default=CaptchaStatus.WAITING, index=True, max_length=32)
    page_url: str | None = Field(default=None, max_length=1000)
    screenshot_path: str | None = Field(default=None, max_length=500)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = None
    expired_at: datetime | None = None


class CaptchaChallenge(CaptchaChallengeBase, TimestampMixin, table=True):
    __tablename__ = "captcha_challenge"

    id: int | None = Field(default=None, primary_key=True)


class CaptchaChallengeCreate(CaptchaChallengeBase):
    pass


class CaptchaChallengeSubmit(SQLModel):
    status: str = CaptchaStatus.SOLVED
    result: dict[str, Any] = Field(default_factory=dict)


class CaptchaChallengeRead(CaptchaChallengeBase):
    id: int
    created_at: datetime
    updated_at: datetime
