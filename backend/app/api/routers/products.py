from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import (
    Product,
    ProductCreate,
    ProductRead,
    ProductSkuRead,
    ProductRelistRequest,
    ProductRelistResult,
    ProductSkuSyncRequest,
    ProductSkuSyncResult,
    FeishuPriceSyncResult,
    ProductPxi,
    ProductSyncRequest,
    ProductSyncResult,
    ProductUpdate,
    ProductSku,
    Shop,
)
from app.services.taobao_product_service import ProductSyncCancellation, TaobaoProductSyncService
from app.services.taobao_relist_service import TaobaoRelistService
from app.services.taobao_sku_service import TaobaoSkuSyncService
from app.services.feishu_price_service import FeishuPriceSyncService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead])
def list_products(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    product_id: str | None = None,
    status: str | None = None,
) -> list[ProductRead]:
    statement = select(Product).order_by(Product.created_at.desc())
    if platform:
        statement = statement.where(Product.platform == platform)
    if shop_id:
        statement = statement.where(Product.shop_id == shop_id)
    if product_id:
        statement = statement.where(Product.product_id == product_id)
    if status and status != "all":
        statement = statement.where(Product.status == status)
    elif not status:
        statement = statement.where(Product.status != "deleted")
    products = list(session.exec(statement).all())
    pxi_map: dict[str, float] = {}
    product_ids = [product.product_id for product in products]
    if product_ids:
        pxi_rows = session.exec(
            select(ProductPxi).where(
                ProductPxi.platform == platform,
                ProductPxi.shop_id == shop_id,
                ProductPxi.product_id.in_(product_ids),
                ProductPxi.status == "active",
            )
        ).all()
        for row in pxi_rows:
            try:
                pxi_map[row.product_id] = float(str(row.pxi_score or "0").replace(",", ""))
            except ValueError:
                pxi_map[row.product_id] = 0
    result: list[ProductRead] = []
    for product in products:
        data = ProductRead.model_validate(product)
        data.pxi_score = pxi_map.get(product.product_id, 0)
        result.append(data)
    return result


@router.post("", response_model=ProductRead)
def create_product(data: ProductCreate, session: SessionDep) -> Product:
    exists = session.exec(
        select(Product).where(
            Product.platform == data.platform,
            Product.shop_id == data.shop_id,
            Product.product_id == data.product_id,
        )
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="product already exists")

    product = Product.model_validate(data)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.post("/sync", response_model=ProductSyncResult)
def sync_products(data: ProductSyncRequest, session: SessionDep) -> dict:
    shop = session.exec(
        select(Shop).where(Shop.platform == data.platform, Shop.shop_id == data.shop_id)
    ).first()
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    if shop.platform != "taobao":
        raise HTTPException(status_code=400, detail="当前商品列表抓取只支持淘宝店铺")
    return TaobaoProductSyncService(session, sync_id=data.sync_id).sync_shop_products(shop)


@router.post("/sync/{sync_id}/cancel")
def cancel_product_sync(sync_id: str) -> dict[str, str | bool]:
    ProductSyncCancellation.cancel(sync_id)
    return {"sync_id": sync_id, "cancelled": True}


@router.get("/skus", response_model=list[ProductSkuRead])
def list_product_skus(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    product_id: str | None = None,
    sku_code: str | None = None,
    status: str | None = None,
) -> list[ProductSku]:
    statement = select(ProductSku).order_by(ProductSku.updated_at.desc())
    if platform:
        statement = statement.where(ProductSku.platform == platform)
    if shop_id:
        statement = statement.where(ProductSku.shop_id == shop_id)
    if product_id:
        statement = statement.where(ProductSku.product_id == product_id)
    if sku_code:
        statement = statement.where(ProductSku.sku_code == sku_code)
    if status and status != "all":
        statement = statement.where(ProductSku.status == status)
    elif not status:
        statement = statement.where(ProductSku.status == "active")
    return list(session.exec(statement).all())


@router.post("/skus/sync", response_model=ProductSkuSyncResult)
def sync_product_skus(data: ProductSkuSyncRequest, session: SessionDep) -> dict:
    shop = session.exec(
        select(Shop).where(Shop.platform == data.platform, Shop.shop_id == data.shop_id)
    ).first()
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    if shop.platform != "taobao":
        raise HTTPException(status_code=400, detail="当前 SKU 抓取只支持淘宝店铺")
    return TaobaoSkuSyncService(session).sync_product_skus(
        shop=shop,
        product_ids=data.product_ids,
        max_workers=data.max_workers,
        wait_min_seconds=data.wait_min_seconds,
        wait_max_seconds=data.wait_max_seconds,
    )


@router.post("/skus/prices/sync", response_model=FeishuPriceSyncResult)
def sync_sku_prices(session: SessionDep) -> FeishuPriceSyncResult:
    return FeishuPriceSyncService(session).sync_from_feishu()


@router.post("/relist", response_model=ProductRelistResult)
def relist_products(data: ProductRelistRequest, session: SessionDep) -> dict:
    shop = session.exec(
        select(Shop).where(Shop.platform == data.platform, Shop.shop_id == data.shop_id)
    ).first()
    if not shop:
        raise HTTPException(status_code=404, detail="shop not found")
    if shop.platform != "taobao":
        raise HTTPException(status_code=400, detail="当前恢复正常价并上架只支持淘宝店铺")
    return TaobaoRelistService(session).relist_products(
        shop=shop,
        product_ids=data.product_ids,
        unified_stock=data.unified_stock,
        stock_mode=data.stock_mode,
        edit_price=data.edit_price,
        update_inventory=data.update_inventory,
        upshelf=data.upshelf,
        dry_run=data.dry_run,
        wait_min_seconds=data.wait_min_seconds,
        wait_max_seconds=data.wait_max_seconds,
    )


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, session: SessionDep) -> Product:
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="product not found")
    return product


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(product_id: int, data: ProductUpdate, session: SessionDep) -> Product:
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="product not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    product.updated_at = datetime.now()
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, session: SessionDep) -> None:
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="product not found")
    session.delete(product)
    session.commit()
