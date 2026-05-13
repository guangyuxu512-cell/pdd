from __future__ import annotations

from app.core.config import get_settings
from app.platforms.base import PlatformAdapter
from app.platforms.generic import GenericPlatformAdapter
from app.platforms.taobao import TaobaoPlatformAdapter


class PlatformRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self.adapters[adapter.platform.lower()] = adapter

    def get(self, platform: str | None) -> PlatformAdapter:
        resolved_platform = (platform or self.settings.default_platform).strip().lower() or "default"
        adapter = self.adapters.get(resolved_platform)
        if adapter:
            return adapter
        return GenericPlatformAdapter(resolved_platform, self.settings.default_login_url)


platform_registry = PlatformRegistry()
platform_registry.register(TaobaoPlatformAdapter())
