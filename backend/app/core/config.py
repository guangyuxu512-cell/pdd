from functools import lru_cache
from pathlib import Path
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parents[3]
    return base_dir / "data"


class Settings(BaseSettings):
    app_name: str = "淘宝工具箱"
    app_version: str = "0.1.0"
    api_prefix: str = "/api"
    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None
    default_platform: str = "taobao"
    default_login_url: str = "https://loginmyseller.taobao.com/"
    browser_channel: str | None = None
    node_path: str | None = None
    max_task_workers: int = 5
    request_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SHELL_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'app.db'}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "profiles", "screenshots", "captcha", "exports", "backups"):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
    return settings
