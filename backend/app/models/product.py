from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class ProductBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    product_id: str = Field(index=True, max_length=128)
    title: str = Field(max_length=255)
    main_image_url: str | None = Field(default=None, max_length=1000)
    price: float = 0
    stock: int = 0
    status: str = Field(default="draft", index=True, max_length=32)
    total_sales: int = 0
    sales_30d: int = 0
    last_platform_updated_at: datetime | None = None


class Product(ProductBase, TimestampMixin, table=True):
    __tablename__ = "product"

    id: int | None = Field(default=None, primary_key=True)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(SQLModel):
    title: str | None = None
    main_image_url: str | None = None
    price: float | None = None
    stock: int | None = None
    status: str | None = None
    total_sales: int | None = None
    sales_30d: int | None = None
    last_platform_updated_at: datetime | None = None


class ProductRead(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime
    pxi_score: float | None = 0


class ProductSyncRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    sync_id: str | None = None


class ProductSyncResult(SQLModel):
    platform: str
    shop_id: str
    shop_name: str
    page_size: int
    count: int
    inserted: int
    updated: int
    upserted: int
    deleted: int = 0
    cancelled: bool = False
    tabs: dict[str, dict[str, Any]]


class ProductSkuBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    product_id: str = Field(index=True, max_length=128)
    sku_id: str = Field(index=True, max_length=128)
    sku_code: str | None = Field(default=None, index=True, max_length=255)
    sku_name: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=1000)
    taobao_price: float = 0
    stock: int = 0
    normal_sale_price: float | None = None
    shunshou_signup_price: float | None = None
    status: str = Field(default="active", index=True, max_length=32)
    props_json: Any | None = Field(default=None, sa_column=Column(JSON))
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    last_platform_updated_at: datetime | None = None


class ProductSku(ProductSkuBase, TimestampMixin, table=True):
    __tablename__ = "product_sku"

    id: int | None = Field(default=None, primary_key=True)


class ProductSkuRead(ProductSkuBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ProductSkuSyncRequest(SQLModel):
    shop_id: str
    product_ids: list[str]
    platform: str = "taobao"
    max_workers: int = 5
    wait_min_seconds: float = 2.0
    wait_max_seconds: float = 4.0


class ProductSkuSyncResult(SQLModel):
    platform: str
    shop_id: str
    requested_products: int
    inserted: int
    updated: int
    inactive: int
    count: int
    failed: list[dict[str, str]]


class ProductRelistRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    product_ids: list[str]
    unified_stock: int = 3
    stock_mode: str = "per_sku"
    edit_price: bool = True
    update_inventory: bool = True
    upshelf: bool = True
    dry_run: bool = False
    wait_min_seconds: float = 1.0
    wait_max_seconds: float = 2.0


class ProductRelistResult(SQLModel):
    platform: str
    shop_id: str
    requested_products: int
    success_count: int
    failed_count: int
    skipped_count: int
    dry_run: bool = False
    success_items: list[dict[str, Any]]
    failed_items: list[dict[str, Any]]
    skipped_items: list[dict[str, Any]]


class FeishuSkuPriceMap(SQLModel, table=True):
    __tablename__ = "feishu_sku_price_map"

    id: int | None = Field(default=None, primary_key=True)
    shop_id: str = Field(index=True, max_length=128)
    shop_name: str | None = Field(default=None, max_length=255)
    sku_code: str = Field(index=True, max_length=255)
    normal_sale_price: float | None = None
    shunshou_signup_price: float | None = None
    record_status: str = Field(default="active", index=True, max_length=32)
    feishu_record_id: str | None = Field(default=None, index=True, max_length=128)
    activity_id: str | None = Field(default=None, max_length=128)
    activity_name: str | None = Field(default=None, max_length=255)
    remark: str | None = None
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    last_sync_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class FeishuPriceSyncResult(SQLModel):
    success: bool
    source_rows: int
    valid_rows: int
    skipped_rows: int
    global_rows: int
    shop_rows: int
    mapping_upserted: int
    updated_global_skus: int
    updated_shop_skus: int
    warnings: list[str] = []


class ProductPxiBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    product_id: str = Field(index=True, max_length=128)
    pxi_score: str | None = Field(default=None, max_length=64)
    update_date: str = Field(index=True, max_length=8)
    range_day: str = Field(default="30d", max_length=32)
    status: str = Field(default="active", index=True, max_length=32)
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    last_platform_updated_at: datetime | None = None


class ProductPxi(ProductPxiBase, TimestampMixin, table=True):
    __tablename__ = "product_pxi"

    id: int | None = Field(default=None, primary_key=True)


class ProductPxiRead(ProductPxiBase):
    id: int
    created_at: datetime
    updated_at: datetime
    product_title: str | None = None
    product_image_url: str | None = None
    product_status: str | None = None


class ProductPxiSyncRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    update_date: str | None = None
    range_day: str = "30d"
    filter_type: str = "all"
    category: str = ""
    item_title: str = ""
    item_id: str = ""


class ProductPxiSyncResult(SQLModel):
    platform: str
    shop_id: str
    shop_name: str
    update_date: str
    range_day: str
    page_size: int
    total: int
    total_pages: int
    count: int
    inserted: int
    updated: int
    inactive: int


class ShunshouActivityBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    activity_id: str = Field(index=True, max_length=128)
    activity_name: str | None = Field(default=None, max_length=255)
    activity_status: int | None = None
    activity_status_text: str | None = Field(default=None, max_length=64)
    signed_item_count: int | None = None
    max_item_limit: int | None = None
    start_time: str | None = Field(default=None, max_length=64)
    end_time: str | None = Field(default=None, max_length=64)
    sync_status: str = Field(default="active", index=True, max_length=32)
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    last_platform_updated_at: datetime | None = None


class ShunshouActivity(ShunshouActivityBase, TimestampMixin, table=True):
    __tablename__ = "shunshou_activity"

    id: int | None = Field(default=None, primary_key=True)


class ShunshouActivityRead(ShunshouActivityBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ShunshouActivityItemBase(SQLModel):
    platform: str = Field(index=True, max_length=32)
    shop_id: str = Field(index=True, max_length=128)
    activity_id: str = Field(index=True, max_length=128)
    product_id: str = Field(index=True, max_length=128)
    item_title: str | None = Field(default=None, max_length=255)
    warn_message: str | None = Field(default=None, max_length=1000)
    warn_status: str | None = Field(default=None, max_length=64)
    activity_item_status: str | None = Field(default=None, max_length=64)
    is_joined: int = 0
    auction_status: int = 0
    sync_status: str = Field(default="active", index=True, max_length=32)
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    last_platform_updated_at: datetime | None = None


class ShunshouActivityItem(ShunshouActivityItemBase, TimestampMixin, table=True):
    __tablename__ = "shunshou_activity_item"

    id: int | None = Field(default=None, primary_key=True)


class ShunshouActivityItemRead(ShunshouActivityItemBase):
    id: int
    created_at: datetime
    updated_at: datetime
    product_title: str | None = None
    product_image_url: str | None = None
    product_status: str | None = None


class ShunshouActivitySyncRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    activity_status: str = "null"


class ShunshouActivityItemSyncRequest(SQLModel):
    shop_id: str
    activity_id: str
    platform: str = "taobao"
    cross_shop: bool = False
    auction_status: int = 0


class ShunshouSignupRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    pxi_min: float = 70
    sold_total_min: int = 3
    product_id: str | None = None
    joined_count_min: int | None = None
    joined_count_max: int | None = None
    target_activity_count: int = 2
    custom_capacity_limit: int = 160
    reserve_item_count: int = 3
    real_capacity_fallback: int = 171
    cross_shop: bool = False
    batch_size: int = 25
    min_wait_seconds: float = 0.6
    max_wait_seconds: float = 1.8
    dry_run: bool = False
    assignments_by_activity: dict[str, list[str]] | None = None
    remove_assignments_by_activity: dict[str, list[str]] | None = None


class ShunshouSignupPriceChangeRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    product_ids: list[str] = []
    assignments_by_activity: dict[str, list[str]] | None = None
    cross_shop: bool = False
    batch_size: int = 25
    min_wait_seconds: float = 0.6
    max_wait_seconds: float = 1.8
    dry_run: bool = False


class ShunshouSignupVerifyRequest(SQLModel):
    shop_id: str
    platform: str = "taobao"
    assignments_by_activity: dict[str, list[str]] = {}
    remove_assignments_by_activity: dict[str, list[str]] = {}
    cross_shop: bool = False
    batch_size: int = 25
    min_wait_seconds: float = 0.3
    max_wait_seconds: float = 0.6


class ShunshouSyncResult(SQLModel):
    platform: str
    shop_id: str
    count: int
    inserted: int
    updated: int
    inactive: int


class ShunshouSignupResult(SQLModel):
    platform: str
    shop_id: str
    candidate_count: int
    assignment_count: int
    submitted_activity_count: int
    submitted_sku_count: int
    skipped_count: int
    dry_run: bool = False
    assignments_by_activity: dict[str, list[str]]
    execution_results: list[dict[str, Any]]
    skipped_items: list[dict[str, Any]]


class ShunshouSignupPreviewResult(SQLModel):
    platform: str
    shop_id: str
    candidate_count: int
    assignment_count: int
    assignments_by_activity: dict[str, list[str]]
    rows: list[dict[str, Any]]
    skipped_items: list[dict[str, Any]]


class ShunshouSignupCheckResult(SQLModel):
    platform: str
    shop_id: str
    checked_count: int
    passed_count: int
    failed_count: int
    ok: bool
    rows: list[dict[str, Any]]
    failed_rows: list[dict[str, Any]]
