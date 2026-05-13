from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import Product, ProductPxi, ProductPxiRead, ProductPxiSyncRequest, ProductPxiSyncResult, Shop
from app.services.taobao_pxi_service import TaobaoPxiSyncService


router = APIRouter(prefix="/pxi", tags=["pxi"])


@router.get("", response_model=list[ProductPxiRead])
def list_pxi(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    product_id: str | None = None,
    update_date: str | None = None,
    status: str | None = None,
) -> list[ProductPxiRead]:
    statement = select(ProductPxi, Product).join(
        Product,
        (Product.platform == ProductPxi.platform)
        & (Product.shop_id == ProductPxi.shop_id)
        & (Product.product_id == ProductPxi.product_id),
    )
    if platform:
        statement = statement.where(ProductPxi.platform == platform)
    if shop_id:
        statement = statement.where(ProductPxi.shop_id == shop_id)
    if product_id:
        statement = statement.where(ProductPxi.product_id == product_id)
    if update_date:
        statement = statement.where(ProductPxi.update_date == update_date)

    statement = statement.where(Product.status != "deleted")
    if status == "all":
        pass
    elif status == "product_deleted":
        statement = statement.where(Product.id == None)
    elif status:
        statement = statement.where(ProductPxi.status == status)
    else:
        statement = statement.where(ProductPxi.status == "active")

    statement = statement.order_by(ProductPxi.updated_at.desc())
    rows = session.exec(statement).all()
    result: list[ProductPxiRead] = []
    for pxi, product in rows:
        data = ProductPxiRead.model_validate(pxi)
        data.product_title = product.title if product else None
        data.product_image_url = product.main_image_url if product else None
        data.product_status = product.status if product else None
        result.append(data)
    return result


@router.post("/sync", response_model=ProductPxiSyncResult)
def sync_pxi(data: ProductPxiSyncRequest, session: SessionDep) -> dict:
    shop = session.exec(
        select(Shop).where(Shop.platform == data.platform, Shop.shop_id == data.shop_id)
    ).first()
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    if shop.platform != "taobao":
        raise HTTPException(status_code=400, detail="当前 PXI 抓取只支持淘宝店铺")
    return TaobaoPxiSyncService(session).sync_shop_pxi(
        shop=shop,
        update_date=data.update_date,
        range_day=data.range_day,
        filter_type=data.filter_type,
        category=data.category,
        item_title=data.item_title,
        item_id=data.item_id,
    )
