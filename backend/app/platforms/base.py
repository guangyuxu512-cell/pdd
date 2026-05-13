from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ShopIdentity:
    shop_id: str
    shop_name: str
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class CookieCheckResult:
    valid: bool
    shop_identity: ShopIdentity | None = None
    message: str | None = None


class PlatformAdapter(Protocol):
    platform: str

    def login_url(self, cookie_type: str = "main") -> str:
        ...

    def identify_shop(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> ShopIdentity:
        ...

    def check_cookie(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> CookieCheckResult:
        ...
