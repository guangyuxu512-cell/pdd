from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class ShopBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    shop_name: str = Field(max_length=255)
    wangwang: str | None = Field(default=None, index=True, max_length=255)
    shop_type: str | None = Field(default=None, index=True, max_length=64)
    account_id: str | None = Field(default=None, index=True, max_length=128)
    profile_id: str | None = Field(default=None, index=True, max_length=128)
    profile_path: str | None = Field(default=None, max_length=500)
    browser_env_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    worker_id: str | None = Field(default=None, index=True, max_length=128)
    cookie_status: str = Field(default="unknown", index=True, max_length=32)
    enabled: bool = True
    last_cookie_check_at: datetime | None = None


class Shop(ShopBase, TimestampMixin, table=True):
    __tablename__ = "shop"

    id: int | None = Field(default=None, primary_key=True)


class ShopCreate(ShopBase):
    pass


class ShopUpdate(SQLModel):
    shop_name: str | None = None
    wangwang: str | None = None
    shop_type: str | None = None
    account_id: str | None = None
    profile_id: str | None = None
    profile_path: str | None = None
    browser_env_json: dict[str, Any] | None = None
    worker_id: str | None = None
    cookie_status: str | None = None
    enabled: bool | None = None


class ShopRead(ShopBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ShopBatchRequest(SQLModel):
    ids: list[int]
