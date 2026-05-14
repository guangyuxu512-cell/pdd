from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import (
    Product,
    ProductPxi,
    ProductSku,
    Shop,
    ShunshouActivity,
    ShunshouActivityItem,
    ShunshouActivityItemRead,
    ShunshouActivityItemSyncRequest,
    ShunshouActivityRead,
    ShunshouActivitySyncRequest,
    ShunshouSignupRequest,
    ShunshouSignupPriceChangeRequest,
    ShunshouSignupVerifyRequest,
    ShunshouSignupCheckResult,
    ShunshouSignupPreviewResult,
    ShunshouSignupResult,
    ShunshouSyncResult,
)
from app.services.shunshou_service import ShunshouService


router = APIRouter(prefix="/shunshou", tags=["shunshou"])


@router.get("/activities", response_model=list[ShunshouActivityRead])
def list_activities(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    status: str | None = None,
) -> list[ShunshouActivity]:
    statement = select(ShunshouActivity).order_by(ShunshouActivity.updated_at.desc())
    if platform:
        statement = statement.where(ShunshouActivity.platform == platform)
    if shop_id:
        statement = statement.where(ShunshouActivity.shop_id == shop_id)
    if status and status != "all":
        statement = statement.where(ShunshouActivity.sync_status == status)
    elif not status:
        statement = statement.where(ShunshouActivity.sync_status == "active")
    return list(session.exec(statement).all())


@router.post("/activities/sync", response_model=ShunshouSyncResult)
def sync_activities(data: ShunshouActivitySyncRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).sync_activities(shop=shop, activity_status=data.activity_status)


@router.delete("/activities/{activity_pk}", response_model=ShunshouActivityRead)
def delete_activity(activity_pk: int, session: SessionDep) -> ShunshouActivity:
    activity = session.get(ShunshouActivity, activity_pk)
    if not activity:
        raise HTTPException(status_code=404, detail="activity not found")
    activity.sync_status = "deleted"
    session.add(activity)
    session.commit()
    session.refresh(activity)
    return activity


@router.get("/activity-items", response_model=list[ShunshouActivityItemRead])
def list_activity_items(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    activity_id: str | None = None,
    product_id: str | None = None,
    status: str | None = None,
) -> list[ShunshouActivityItemRead]:
    statement = select(ShunshouActivityItem, Product).join(
        Product,
        (Product.platform == ShunshouActivityItem.platform)
        & (Product.shop_id == ShunshouActivityItem.shop_id)
        & (Product.product_id == ShunshouActivityItem.product_id),
    )
    if platform:
        statement = statement.where(ShunshouActivityItem.platform == platform)
    if shop_id:
        statement = statement.where(ShunshouActivityItem.shop_id == shop_id)
    if activity_id:
        statement = statement.where(ShunshouActivityItem.activity_id == activity_id)
    if product_id:
        statement = statement.where(ShunshouActivityItem.product_id == product_id)
    statement = statement.where(Product.status != "deleted")
    if status and status != "all":
        statement = statement.where(ShunshouActivityItem.sync_status == status)
    elif not status:
        statement = statement.where(ShunshouActivityItem.sync_status == "active")
    statement = statement.order_by(ShunshouActivityItem.updated_at.desc())

    result: list[ShunshouActivityItemRead] = []
    for item, product in session.exec(statement).all():
        data = ShunshouActivityItemRead.model_validate(item)
        data.product_title = product.title if product else None
        data.product_image_url = product.main_image_url if product else None
        data.product_status = product.status if product else None
        result.append(data)
    return result


@router.post("/activity-items/sync", response_model=ShunshouSyncResult)
def sync_activity_items(data: ShunshouActivityItemSyncRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).sync_activity_items(
        shop=shop,
        activity_id=data.activity_id,
        cross_shop=data.cross_shop,
        auction_status=data.auction_status,
    )


@router.post("/signup", response_model=ShunshouSignupResult)
def one_click_signup(data: ShunshouSignupRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).one_click_signup(
        shop=shop,
        pxi_min=data.pxi_min,
        sold_total_min=data.sold_total_min,
        target_activity_count=data.target_activity_count,
        custom_capacity_limit=data.custom_capacity_limit,
        reserve_item_count=data.reserve_item_count,
        real_capacity_fallback=data.real_capacity_fallback,
        cross_shop=data.cross_shop,
        batch_size=data.batch_size,
        min_wait_seconds=data.min_wait_seconds,
        max_wait_seconds=data.max_wait_seconds,
        dry_run=data.dry_run,
        assignments_by_activity=data.assignments_by_activity,
        remove_assignments_by_activity=data.remove_assignments_by_activity,
    )


@router.post("/signup/preview", response_model=ShunshouSignupPreviewResult)
def preview_signup(data: ShunshouSignupRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).preview_signup_candidates(
        shop=shop,
        pxi_min=data.pxi_min,
        sold_total_min=data.sold_total_min,
        product_id=data.product_id,
        joined_count_min=data.joined_count_min,
        joined_count_max=data.joined_count_max,
        target_activity_count=data.target_activity_count,
        custom_capacity_limit=data.custom_capacity_limit,
        reserve_item_count=data.reserve_item_count,
        real_capacity_fallback=data.real_capacity_fallback,
    )


@router.post("/signup/check", response_model=ShunshouSignupCheckResult)
def check_signup(data: ShunshouSignupRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).check_signup_assignments(
        shop=shop,
        assignments_by_activity=data.assignments_by_activity,
        remove_assignments_by_activity=data.remove_assignments_by_activity,
        pxi_min=data.pxi_min,
        sold_total_min=data.sold_total_min,
    )


@router.post("/signup/price-changes/detect")
def detect_signup_price_changes(data: ShunshouSignupPriceChangeRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).detect_signup_price_changes(
        shop=shop,
        product_ids=data.product_ids,
        cross_shop=data.cross_shop,
        batch_size=data.batch_size,
        min_wait_seconds=data.min_wait_seconds,
        max_wait_seconds=data.max_wait_seconds,
    )


@router.post("/signup/price-changes/update")
def update_joined_signup_prices(data: ShunshouSignupPriceChangeRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).update_joined_signup_prices(
        shop=shop,
        product_ids=data.product_ids,
        assignments_by_activity=data.assignments_by_activity,
        cross_shop=data.cross_shop,
        batch_size=data.batch_size,
        min_wait_seconds=data.min_wait_seconds,
        max_wait_seconds=data.max_wait_seconds,
        dry_run=data.dry_run,
    )


@router.post("/signup/verify")
def verify_signup(data: ShunshouSignupVerifyRequest, session: SessionDep) -> dict:
    shop = resolve_taobao_shop(session, data.platform, data.shop_id)
    return ShunshouService(session).verify_signup_assignments(
        shop=shop,
        assignments_by_activity=data.assignments_by_activity,
        remove_assignments_by_activity=data.remove_assignments_by_activity,
        cross_shop=data.cross_shop,
        batch_size=data.batch_size,
        min_wait_seconds=data.min_wait_seconds,
        max_wait_seconds=data.max_wait_seconds,
    )


@router.get("/readiness")
def get_readiness(session: SessionDep, platform: str, shop_id: str) -> dict:
    shop = resolve_taobao_shop(session, platform, shop_id)
    product_count = scalar_count(
        session,
        select(func.count(Product.id)).where(
            Product.platform == shop.platform,
            Product.shop_id == shop.shop_id,
            Product.status != "deleted",
        ),
    )
    onsale_count = scalar_count(
        session,
        select(func.count(Product.id)).where(
            Product.platform == shop.platform,
            Product.shop_id == shop.shop_id,
            Product.status == "onsale",
        ),
    )
    sku_count = scalar_count(
        session,
        select(func.count(ProductSku.id)).where(
            ProductSku.platform == shop.platform,
            ProductSku.shop_id == shop.shop_id,
            ProductSku.status == "active",
        ),
    )
    signup_price_sku_count = scalar_count(
        session,
        select(func.count(ProductSku.id)).where(
            ProductSku.platform == shop.platform,
            ProductSku.shop_id == shop.shop_id,
            ProductSku.status == "active",
            ProductSku.shunshou_signup_price != None,
        ),
    )
    normal_price_sku_count = scalar_count(
        session,
        select(func.count(ProductSku.id)).where(
            ProductSku.platform == shop.platform,
            ProductSku.shop_id == shop.shop_id,
            ProductSku.status == "active",
            ProductSku.normal_sale_price != None,
        ),
    )
    pxi_count = scalar_count(
        session,
        select(func.count(ProductPxi.id)).where(
            ProductPxi.platform == shop.platform,
            ProductPxi.shop_id == shop.shop_id,
            ProductPxi.status == "active",
        ),
    )
    activity_count = scalar_count(
        session,
        select(func.count(ShunshouActivity.id)).where(
            ShunshouActivity.platform == shop.platform,
            ShunshouActivity.shop_id == shop.shop_id,
            ShunshouActivity.sync_status == "active",
        ),
    )
    activity_item_count = scalar_count(
        session,
        select(func.count(ShunshouActivityItem.id)).where(
            ShunshouActivityItem.platform == shop.platform,
            ShunshouActivityItem.shop_id == shop.shop_id,
            ShunshouActivityItem.sync_status == "active",
        ),
    )
    missing_normal_price_sku_count = scalar_count(
        session,
        select(func.count(ProductSku.id)).where(
            ProductSku.platform == shop.platform,
            ProductSku.shop_id == shop.shop_id,
            ProductSku.status == "active",
            ProductSku.shunshou_signup_price != None,
            ProductSku.normal_sale_price == None,
        ),
    )
    checks = [
        readiness_item("商品列表", product_count > 0, product_count, "1 商品列表"),
        readiness_item("出售中商品", onsale_count > 0, onsale_count, "需要有出售中的商品才可报名"),
        readiness_item("SKU", sku_count > 0, sku_count, "2 SKU价/库存"),
        readiness_item("飞书价格", normal_price_sku_count > 0, normal_price_sku_count, "3 飞书匹配价格；无顺手报名价的SKU报名时自动忽略"),
        readiness_item("PXI分", pxi_count > 0, pxi_count, "4 PXI分"),
        readiness_item("活动ID", activity_count > 0, activity_count, "5 活动ID"),
        readiness_item("活动商品", activity_item_count > 0, activity_item_count, "6 活动商品"),
    ]
    return {
        "platform": shop.platform,
        "shop_id": shop.shop_id,
        "ready": all(item["ok"] for item in checks),
        "checks": checks,
        "counts": {
            "product_count": product_count,
            "onsale_count": onsale_count,
            "sku_count": sku_count,
            "signup_price_sku_count": signup_price_sku_count,
            "normal_price_sku_count": normal_price_sku_count,
            "pxi_count": pxi_count,
            "activity_count": activity_count,
            "activity_item_count": activity_item_count,
            "missing_normal_price_sku_count": missing_normal_price_sku_count,
        },
    }


def scalar_count(session: SessionDep, statement) -> int:
    return int(session.exec(statement).one() or 0)


def readiness_item(name: str, ok: bool, count: int, action: str) -> dict:
    return {"name": name, "ok": bool(ok), "count": int(count), "action": action}


def resolve_taobao_shop(session: SessionDep, platform: str, shop_id: str) -> Shop:
    shop = session.exec(select(Shop).where(Shop.platform == platform, Shop.shop_id == shop_id)).first()
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    if shop.platform != "taobao":
        raise HTTPException(status_code=400, detail="当前顺手买一件只支持淘宝店铺")
    return shop
