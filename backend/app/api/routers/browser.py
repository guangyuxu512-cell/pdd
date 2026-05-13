from fastapi import APIRouter

from app.api.deps import SessionDep
from app.models import (
    BrowserLoginCheck,
    BrowserLoginCheckResult,
    BrowserLoginStart,
    BrowserLoginStarted,
    Shop,
)
from app.services.browser_login_service import browser_login_service

router = APIRouter(prefix="/browser", tags=["browser"])


@router.post("/login-sessions", response_model=BrowserLoginStarted)
def start_login(data: BrowserLoginStart, db: SessionDep) -> BrowserLoginStarted:
    shop = db.get(Shop, data.shop_pk) if data.shop_pk else None
    session = browser_login_service.start(
        platform=shop.platform if shop else data.platform,
        login_url=data.login_url,
        cookie_type=data.cookie_type,
        profile_id=shop.profile_id if shop else None,
        profile_path=shop.profile_path if shop else None,
        target_shop_pk=shop.id if shop else None,
    )
    return BrowserLoginStarted(
        session_id=session.session_id,
        platform=session.platform,
        profile_id=session.profile_id,
        profile_path=str(session.profile_path),
        login_url=session.login_url,
        status="opened",
    )


@router.post("/login-sessions/{session_id}/check", response_model=BrowserLoginCheckResult)
def check_login(
    session_id: str,
    data: BrowserLoginCheck,
    session: SessionDep,
) -> BrowserLoginCheckResult:
    shop, snapshot = browser_login_service.capture_and_save(
        db=session,
        session_id=session_id,
        shop_id=None,
        shop_name=None,
        close_browser=data.close_browser,
        cookie_type=data.cookie_type,
        cookie_header_text=data.cookie_header_text,
    )
    cookie_health = browser_login_service.taobao_cookie_health(snapshot.cookies_json) if shop.platform == "taobao" and snapshot.cookie_type == "main" else {}
    return BrowserLoginCheckResult(
        session_id=session_id,
        platform=shop.platform,
        shop_id=shop.shop_id,
        shop_name=shop.shop_name,
        wangwang=shop.wangwang,
        shop_type=shop.shop_type,
        cookie_count=snapshot.cookie_count,
        cookie_type=snapshot.cookie_type,
        cookie_status=shop.cookie_status,
        profile_id=shop.profile_id or "",
        profile_path=shop.profile_path or "",
        shop_pk=shop.id or 0,
        cookie_missing=cookie_health.get("missing", []),
        cookie_missing_recommended=cookie_health.get("missing_recommended", []),
    )


@router.post("/login-sessions/{session_id}/close")
def close_login(session_id: str) -> dict[str, str]:
    browser_login_service.close(session_id)
    return {"status": "closed"}
