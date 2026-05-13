from datetime import datetime
from pathlib import Path
import shutil

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.browser_profile import BrowserProfileService
from app.models import CookieSnapshot, RequestLog, Shop, ShopBatchRequest, ShopCreate, ShopRead, ShopUpdate, Task, TaskLog
from app.platforms import platform_registry

router = APIRouter(prefix="/shops", tags=["shops"])


@router.get("", response_model=list[ShopRead])
def list_shops(session: SessionDep, platform: str | None = None) -> list[Shop]:
    statement = select(Shop).order_by(Shop.created_at.desc())
    if platform:
        statement = statement.where(Shop.platform == platform)
    return list(session.exec(statement).all())


@router.post("", response_model=ShopRead)
def create_shop(data: ShopCreate, session: SessionDep) -> Shop:
    exists = session.exec(
        select(Shop).where(Shop.platform == data.platform, Shop.shop_id == data.shop_id)
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="shop already exists")

    profile_path = data.profile_path
    if not profile_path:
        profile_path = str(BrowserProfileService().get_profile_path(data.platform, data.shop_id))
    shop = Shop.model_validate(data, update={"profile_path": profile_path})
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


@router.get("/{shop_id}", response_model=ShopRead)
def get_shop(shop_id: int, session: SessionDep) -> Shop:
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    return shop


@router.patch("/{shop_id}", response_model=ShopRead)
def update_shop(shop_id: int, data: ShopUpdate, session: SessionDep) -> Shop:
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(shop, key, value)
    shop.updated_at = datetime.now()
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


@router.delete("/{shop_id}", status_code=204)
def delete_shop(shop_id: int, session: SessionDep) -> None:
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    purge_shop_data(shop, session)
    session.commit()


@router.post("/batch-delete")
def batch_delete_shops(data: ShopBatchRequest, session: SessionDep) -> dict[str, int]:
    deleted = 0
    for shop_id in data.ids:
        shop = session.get(Shop, shop_id)
        if not shop:
            continue
        purge_shop_data(shop, session)
        deleted += 1
    session.commit()
    return {"deleted": deleted}


@router.post("/batch-refresh-cookie")
def batch_refresh_cookie_status(data: ShopBatchRequest, session: SessionDep) -> dict[str, list[ShopRead]]:
    refreshed: list[Shop] = []
    for shop_pk in data.ids:
        shop = session.get(Shop, shop_pk)
        if not shop:
            continue
        refresh_shop_cookie_status(shop, session)
        refreshed.append(shop)
    session.commit()
    return {"shops": [ShopRead.model_validate(shop) for shop in refreshed]}


@router.post("/{shop_id}/refresh-cookie", response_model=ShopRead)
def refresh_cookie_status(shop_id: int, session: SessionDep) -> Shop:
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    refresh_shop_cookie_status(shop, session)
    session.commit()
    session.refresh(shop)
    return shop


@router.post("/{shop_id}/cookie-check", response_model=ShopRead)
def mark_cookie_checked(shop_id: int, session: SessionDep, valid: bool = True) -> Shop:
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    shop.cookie_status = "valid" if valid else "invalid"
    shop.last_cookie_check_at = datetime.now()
    shop.updated_at = datetime.now()
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


def refresh_shop_cookie_status(shop: Shop, session: SessionDep) -> None:
    latest = session.exec(
        select(CookieSnapshot)
        .where(CookieSnapshot.platform == shop.platform, CookieSnapshot.shop_id == shop.shop_id)
        .where(CookieSnapshot.cookie_type == "main")
        .order_by(CookieSnapshot.created_at.desc())
    ).first()
    if latest and latest.cookie_count > 0:
        adapter = platform_registry.get(shop.platform)
        try:
            result = adapter.check_cookie(latest.cookies_json, latest.storage_state_json, latest.cookie_type)
            if result.valid and result.shop_identity:
                shop.shop_name = result.shop_identity.shop_name
                metadata = result.shop_identity.raw if isinstance(result.shop_identity.raw, dict) else {}
                shop.wangwang = metadata.get("wangwang") or shop.wangwang
                shop.shop_type = metadata.get("shop_type") or shop.shop_type
            shop.cookie_status = "valid" if result.valid else "invalid"
            latest.status = "valid" if result.valid else "invalid"
            session.add(latest)
        except Exception:
            shop.cookie_status = "invalid"
            latest.status = "invalid"
            session.add(latest)
    else:
        shop.cookie_status = "valid" if latest and latest.cookie_count > 0 else "invalid"
    shop.last_cookie_check_at = datetime.now()
    shop.updated_at = datetime.now()
    session.add(shop)


def purge_shop_data(shop: Shop, session: SessionDep) -> None:
    platform = shop.platform
    shop_id = shop.shop_id
    profile_path = shop.profile_path

    task_ids = [
        task.id
        for task in session.exec(select(Task).where(Task.platform == platform, Task.shop_id == shop_id)).all()
        if task.id is not None
    ]
    if task_ids:
        for task_log in session.exec(select(TaskLog).where(TaskLog.task_id.in_(task_ids))).all():
            session.delete(task_log)

    for model in (RequestLog, CookieSnapshot, Task):
        for row in session.exec(select(model).where(model.platform == platform, model.shop_id == shop_id)).all():
            session.delete(row)

    session.delete(shop)
    remove_profile_dir(profile_path)


def remove_profile_dir(profile_path: str | None) -> None:
    if not profile_path:
        return
    settings = get_settings()
    profiles_root = (settings.data_dir / "profiles").resolve()
    target = Path(profile_path).resolve()
    try:
        target.relative_to(profiles_root)
    except ValueError:
        return
    if target.exists() and target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
