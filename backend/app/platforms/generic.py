from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.platforms.base import CookieCheckResult, ShopIdentity


class GenericPlatformAdapter:
    def __init__(self, platform: str, default_login_url: str = "about:blank") -> None:
        self.platform = platform
        self.default_login_url = default_login_url

    def login_url(self, cookie_type: str = "main") -> str:
        return self.default_login_url

    def identify_shop(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> ShopIdentity:
        raise HTTPException(status_code=400, detail="当前平台没有自动识别店铺适配器，请手动填写店铺 ID 和店铺名")

    def check_cookie(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> CookieCheckResult:
        return CookieCheckResult(valid=bool(cookies), message="按 cookie 数量做基础检测")
