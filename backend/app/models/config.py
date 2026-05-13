from datetime import datetime

from sqlmodel import Field, SQLModel


class AppConfig(SQLModel, table=True):
    __tablename__ = "app_config"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True, max_length=128)
    value: str
    value_type: str = Field(default="string", max_length=32)
    sensitive: bool = False
    description: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AppConfigRead(SQLModel):
    key: str
    value: str
    value_type: str
    sensitive: bool
    description: str | None


class AppConfigWrite(SQLModel):
    value: str
    value_type: str = "string"
    sensitive: bool = False
    description: str | None = None
