from sqlmodel import Field, SQLModel


class BrowserLoginStart(SQLModel):
    login_url: str | None = None
    platform: str | None = None
    shop_pk: int | None = None
    cookie_type: str = "main"


class BrowserLoginStarted(SQLModel):
    session_id: str
    platform: str
    profile_id: str
    profile_path: str
    login_url: str
    status: str


class BrowserLoginCheck(SQLModel):
    close_browser: bool = True
    cookie_type: str = "main"
    cookie_header_text: str | None = None


class BrowserLoginCheckResult(SQLModel):
    session_id: str
    platform: str
    shop_id: str
    shop_name: str
    wangwang: str | None = None
    shop_type: str | None = None
    cookie_count: int
    cookie_type: str
    cookie_status: str
    profile_id: str
    profile_path: str
    shop_pk: int
    cookie_missing: list[str] = Field(default_factory=list)
    cookie_missing_recommended: list[str] = Field(default_factory=list)
