from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session, select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.cookies import cookies_to_dict
from app.models import CookieSnapshot, RequestLog, Shop, Task, TaskStatus


SENSITIVE_KEYS = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key", "token"}
AUTH_EXPIRED_STATUS_CODES = {401, 403}
AUTH_EXPIRED_KEYWORDS = (
    "login",
    "登录",
    "未登录",
    "重新登录",
    "登录态",
    "过期",
    "unauthorized",
    "forbidden",
)


class RequestAuthExpiredError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def redact_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return headers
    return {
        key: "***" if key.lower() in SENSITIVE_KEYS else value
        for key, value in headers.items()
    }


class RequestClient:
    def __init__(
        self,
        platform: str,
        shop_id: str,
        base_url: str,
        session: Session,
        task_id: int | None = None,
        shop_name: str | None = None,
        account_id: str | None = None,
        profile_id: str | None = None,
        worker_id: str | None = None,
        cookie_type: str = "main",
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        shop: Shop | None = None,
        cookie_snapshot: CookieSnapshot | None = None,
    ) -> None:
        self.platform = platform
        self.shop_id = shop_id
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.task_id = task_id
        self.shop_name = shop_name
        self.account_id = account_id
        self.profile_id = profile_id
        self.worker_id = worker_id
        self.cookie_type = cookie_type
        self.shop = shop
        self.cookie_snapshot = cookie_snapshot
        self.cookies = cookies if cookies is not None else self._load_cookies()
        self.headers = self._build_headers(headers or {})
        self.settings = get_settings()

    @classmethod
    def from_shop(
        cls,
        *,
        session: Session,
        shop: Shop,
        base_url: str,
        task_id: int | None = None,
        cookie_type: str = "main",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> RequestClient:
        return cls(
            platform=shop.platform,
            shop_id=shop.shop_id,
            base_url=base_url,
            session=session,
            task_id=task_id,
            shop_name=shop.shop_name,
            account_id=shop.account_id,
            profile_id=shop.profile_id,
            worker_id=shop.worker_id,
            cookie_type=cookie_type,
            cookies=cookies,
            headers=headers,
            shop=shop,
        )

    def _load_cookies(self) -> dict[str, str]:
        snapshot = self.session.exec(
            select(CookieSnapshot)
            .where(CookieSnapshot.platform == self.platform, CookieSnapshot.shop_id == self.shop_id)
            .where(CookieSnapshot.cookie_type == self.cookie_type)
            .order_by(CookieSnapshot.created_at.desc())
        ).first()
        self.cookie_snapshot = snapshot
        if not snapshot:
            return {}
        return cookies_to_dict(snapshot.cookies_json)

    def _build_headers(self, headers: dict[str, str]) -> dict[str, str]:
        resolved = dict(headers)
        browser_env = self.shop.browser_env_json if self.shop else None
        user_agent = browser_env.get("user_agent") if isinstance(browser_env, dict) else None
        has_user_agent = any(key.lower() == "user-agent" for key in resolved)
        if user_agent and not has_user_agent:
            resolved["user-agent"] = str(user_agent)
        return resolved

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {**self.headers, **(extra_headers or {})}
        started = time.perf_counter()
        status_code: int | None = None
        response_headers: dict[str, str] | None = None
        response_json: dict[str, Any] | None = None
        error_message: str | None = None

        try:
            with httpx.Client(timeout=self.settings.request_timeout_seconds, cookies=self.cookies) as client:
                response = client.request(method, url, json=json, headers=headers)
                status_code = response.status_code
                response_headers = dict(response.headers)
                response_json = parse_response_json(response)
                if self._is_auth_expired(response, response_json):
                    self._mark_auth_expired(status_code, response_json)
                    raise RequestAuthExpiredError("cookie expired or login required", status_code)
                response.raise_for_status()
                return response_json
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.session.add(
                RequestLog(
                    platform=self.platform,
                    shop_id=self.shop_id,
                    shop_name=self.shop_name,
                    account_id=self.account_id,
                    profile_id=self.profile_id,
                    worker_id=self.worker_id,
                    task_id=self.task_id,
                    method=method.upper(),
                    url=url,
                    status_code=status_code,
                    request_headers_json=redact_headers(headers),
                    request_body_json=json,
                    response_headers_json=redact_headers(response_headers),
                    response_body_json=response_json,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            )
            self.session.commit()

    def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request_json("GET", path, **kwargs)

    def post_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request_json("POST", path, **kwargs)

    def _is_auth_expired(
        self,
        response: httpx.Response,
        response_json: dict[str, Any] | None,
    ) -> bool:
        if response.status_code in AUTH_EXPIRED_STATUS_CODES:
            return True
        if not response_json:
            return False
        text = str(response_json).lower()
        return any(keyword.lower() in text for keyword in AUTH_EXPIRED_KEYWORDS)

    def _mark_auth_expired(
        self,
        status_code: int | None,
        response_json: dict[str, Any] | None,
    ) -> None:
        now = datetime.now()
        if self.cookie_snapshot:
            self.cookie_snapshot.status = "invalid"
            self.session.add(self.cookie_snapshot)
        shop = self.shop or self.session.exec(
            select(Shop).where(Shop.platform == self.platform, Shop.shop_id == self.shop_id)
        ).first()
        if shop and self.cookie_type == "main":
            shop.cookie_status = "invalid"
            shop.last_cookie_check_at = now
            shop.updated_at = now
            self.session.add(shop)
        if self.task_id:
            task = self.session.get(Task, self.task_id)
            if task:
                task.status = TaskStatus.WAITING_LOGIN
                task.error_message = "cookie expired or login required"
                task.updated_at = now
                self.session.add(task)
        self.session.commit()


def parse_response_json(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {"text": response.text[:2000]}
    return data if isinstance(data, dict) else {"data": data}
