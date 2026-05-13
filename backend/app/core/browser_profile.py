from pathlib import Path

from app.core.config import get_settings
from app.platforms import platform_registry


class BrowserProfileService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_profile_path(self, platform: str, shop_id: str) -> Path:
        safe_platform = platform.strip().lower()
        safe_shop_id = shop_id.strip().replace("/", "_").replace("\\", "_")
        path = self.settings.data_dir / "profiles" / safe_platform / safe_shop_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_login_url(self, platform: str) -> str | None:
        return platform_registry.get(platform).login_url()
