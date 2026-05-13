from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import cookies_to_dict
from app.core.mtop import current_millis, extract_h5_token, generate_mtop_sign
from app.models import CookieSnapshot, Product, ProductSku, Shop


TAOBAO_PRODUCT_APP_KEY = "12574478"
TAOBAO_PRODUCT_API = "mtop.taobao.sell.pc.manage.async"
TAOBAO_PRODUCT_URL = "https://h5api.m.taobao.com/h5/mtop.taobao.sell.pc.manage.async/1.0/"
TAOBAO_PRODUCT_TTID = "11320@taobao_WEB_9.9.99"
TAOBAO_PRODUCT_PAGE_SIZE = 60
TAOBAO_PRODUCT_TABS = {
    "in_stock": {"label": "仓库中", "status": "warehouse"},
    "on_sale": {"label": "出售中", "status": "onsale"},
}


class ProductSyncCancellation:
    _lock = Lock()
    _cancelled: set[str] = set()

    @classmethod
    def start(cls, sync_id: str | None) -> None:
        if not sync_id:
            return
        with cls._lock:
            cls._cancelled.discard(sync_id)

    @classmethod
    def cancel(cls, sync_id: str) -> None:
        with cls._lock:
            cls._cancelled.add(sync_id)

    @classmethod
    def is_cancelled(cls, sync_id: str | None) -> bool:
        if not sync_id:
            return False
        with cls._lock:
            return sync_id in cls._cancelled

    @classmethod
    def finish(cls, sync_id: str | None) -> None:
        if not sync_id:
            return
        with cls._lock:
            cls._cancelled.discard(sync_id)


class TaobaoProductSyncService:
    def __init__(self, session: Session, sync_id: str | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.sync_id = sync_id

    def sync_shop_products(self, shop: Shop) -> dict[str, Any]:
        ProductSyncCancellation.start(self.sync_id)
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        token = extract_h5_token(cookie_dict)
        if not token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 _m_h5_tk，请重新登录店铺后再获取商品")

        user_agent = self._user_agent(shop, snapshot)
        try:
            tab_results = self._fetch_tabs(cookie_dict=cookie_dict, token=token, user_agent=user_agent)
            items = self._dedupe_items(tab_results)
            db_result = self._upsert_products(shop, items)
            cancelled = ProductSyncCancellation.is_cancelled(self.sync_id)
            deleted = 0 if cancelled else self._mark_missing_deleted(shop, items)

            return {
                "platform": shop.platform,
                "shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "page_size": TAOBAO_PRODUCT_PAGE_SIZE,
                "count": len(items),
                "cancelled": cancelled,
                "deleted": deleted,
                **db_result,
                "tabs": {
                    tab: {
                        key: value
                        for key, value in result.items()
                        if key != "items"
                    }
                    for tab, result in tab_results.items()
                },
            }
        except HTTPException as exc:
            if is_token_expired_error(exc.detail):
                self._mark_cookie_invalid(shop, snapshot)
            raise
        finally:
            ProductSyncCancellation.finish(self.sync_id)

    def _latest_main_cookie(self, shop: Shop) -> CookieSnapshot:
        snapshot = self.session.exec(
            select(CookieSnapshot)
            .where(CookieSnapshot.platform == shop.platform, CookieSnapshot.shop_id == shop.shop_id)
            .where(CookieSnapshot.cookie_type == "main")
            .order_by(CookieSnapshot.created_at.desc())
        ).first()
        if not snapshot or not snapshot.cookies_json:
            raise HTTPException(status_code=400, detail="没有可用的淘宝主 cookie，请先网页登录并保存登录态")
        return snapshot

    def _fetch_tabs(
        self,
        *,
        cookie_dict: dict[str, str],
        token: str,
        user_agent: str | None,
    ) -> dict[str, dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=len(TAOBAO_PRODUCT_TABS)) as executor:
            futures = {
                tab: executor.submit(
                    self._fetch_tab,
                    tab=tab,
                    cookie_dict=cookie_dict,
                    token=token,
                    user_agent=user_agent,
                )
                for tab in TAOBAO_PRODUCT_TABS
            }
            return {tab: future.result() for tab, future in futures.items()}

    def _fetch_tab(
        self,
        *,
        tab: str,
        cookie_dict: dict[str, str],
        token: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        current = 1
        collected: list[dict[str, Any]] = []
        total = 0
        total_pages = 0
        pages = 0
        tab_info = TAOBAO_PRODUCT_TABS[tab]
        headers = self._headers(cookie_dict={}, tab=tab, current=current, user_agent=user_agent)

        with httpx.Client(
            timeout=self.settings.request_timeout_seconds,
            cookies=cookie_dict,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while True:
                if ProductSyncCancellation.is_cancelled(self.sync_id):
                    break
                payload = self._request_page(
                    client=client,
                    token=token,
                    tab=tab,
                    current=current,
                    page_size=TAOBAO_PRODUCT_PAGE_SIZE,
                    user_agent=user_agent,
                )
                data = payload.get("data", {})
                table = data.get("table", {}) if isinstance(data, dict) else {}
                pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
                data_source = table.get("dataSource", []) if isinstance(table, dict) else []
                if not isinstance(data_source, list):
                    data_source = []

                page_items = [
                    self._normalize_item(item, tab=tab, status=str(tab_info["status"]))
                    for item in data_source
                    if isinstance(item, dict)
                ]
                collected.extend(page_items)
                pages += 1

                total = to_int(pagination.get("total")) or len(collected)
                current_page = to_int(pagination.get("current")) or current
                real_page_size = to_int(pagination.get("pageSize")) or TAOBAO_PRODUCT_PAGE_SIZE
                total_pages = math.ceil(total / real_page_size) if real_page_size else 0

                if total_pages <= 0 or current_page >= total_pages:
                    break
                if ProductSyncCancellation.is_cancelled(self.sync_id):
                    break
                current = current_page + 1

        return {
            "label": tab_info["label"],
            "tab": tab,
            "status": tab_info["status"],
            "total": total,
            "total_pages": total_pages,
            "pages": pages,
            "count": len(collected),
            "items": collected,
        }

    def _request_page(
        self,
        *,
        client: httpx.Client,
        token: str,
        tab: str,
        current: int,
        page_size: int,
        user_agent: str | None,
    ) -> dict[str, Any]:
        timestamp = current_millis()
        data_str = build_product_data(tab=tab, current=current, page_size=page_size)
        sign = generate_mtop_sign(token, timestamp, TAOBAO_PRODUCT_APP_KEY, data_str)
        params = {
            "jsv": "2.6.1",
            "appKey": TAOBAO_PRODUCT_APP_KEY,
            "t": timestamp,
            "sign": sign,
            "api": TAOBAO_PRODUCT_API,
            "v": "1.0",
            "ttid": TAOBAO_PRODUCT_TTID,
            "type": "originaljson",
            "dataType": "json",
        }
        headers = self._headers(cookie_dict={}, tab=tab, current=current, user_agent=user_agent)
        try:
            response = client.post(
                TAOBAO_PRODUCT_URL,
                params=params,
                headers=headers,
                content="data=" + quote(data_str),
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"请求淘宝商品接口失败：{exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"淘宝商品接口返回异常：{response.text[:500]}")
        try:
            resp_json = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"淘宝商品接口返回不是 JSON：{response.text[:500]}") from exc
        return parse_mtop_result(resp_json)

    def _headers(
        self,
        *,
        cookie_dict: dict[str, str],
        tab: str,
        current: int,
        user_agent: str | None,
    ) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://myseller.taobao.com",
            "pragma": "no-cache",
            "referer": (
                "https://myseller.taobao.com/home.htm/"
                f"SellManage/{tab}?current={current}&pageSize={TAOBAO_PRODUCT_PAGE_SIZE}"
            ),
        }
        if user_agent:
            headers["user-agent"] = user_agent
        if cookie_dict:
            headers["cookie"] = "; ".join(f"{key}={value}" for key, value in cookie_dict.items())
        return headers

    def _normalize_item(self, item: dict[str, Any], *, tab: str, status: str) -> dict[str, Any]:
        manager_price = item.get("managerPrice", {})
        manager_quantity = item.get("managerQuantityNew", {})
        sold_quantity = item.get("soldQuantityPromotion", {})
        monthly_sold = item.get("monthlySoldQuantity", {})

        return {
            "tab": tab,
            "product_id": text(item.get("itemId")),
            "title": title_from_item(item),
            "main_image_url": image_from_item(item),
            "price": to_float(value_from(manager_price, "currentPrice")),
            "stock": to_int(value_from(manager_quantity, "text")),
            "status": status,
            "status_text": status_text_from_item(item),
            "total_sales": to_int(value_from(sold_quantity, "soldQuantity")),
            "sales_30d": to_int(value_from(monthly_sold, "value")),
        }

    def _dedupe_items(self, tab_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for result in tab_results.values():
            for item in result["items"]:
                product_id = item.get("product_id")
                if product_id:
                    indexed[str(product_id)] = item
        return list(indexed.values())

    def _upsert_products(self, shop: Shop, items: list[dict[str, Any]]) -> dict[str, int]:
        now = datetime.now()
        inserted = 0
        updated = 0
        for item in items:
            product = self.session.exec(
                select(Product).where(
                    Product.platform == shop.platform,
                    Product.shop_id == shop.shop_id,
                    Product.product_id == item["product_id"],
                )
            ).first()
            values = {
                "title": truncate(item["title"], 255),
                "main_image_url": truncate(item["main_image_url"], 1000) or None,
                "price": item["price"],
                "stock": item["stock"],
                "status": item["status"],
                "total_sales": item["total_sales"],
                "sales_30d": item["sales_30d"],
                "last_platform_updated_at": now,
                "updated_at": now,
            }
            if product:
                for key, value in values.items():
                    setattr(product, key, value)
                updated += 1
            else:
                product = Product(
                    platform=shop.platform,
                    shop_id=shop.shop_id,
                    product_id=truncate(item["product_id"], 128),
                    **values,
                )
                inserted += 1
            self.session.add(product)
        self.session.commit()
        return {"inserted": inserted, "updated": updated, "upserted": inserted + updated}

    def _mark_missing_deleted(self, shop: Shop, items: list[dict[str, Any]]) -> int:
        now = datetime.now()
        active_ids = {str(item["product_id"]) for item in items if item.get("product_id")}
        deleted = 0
        products = self.session.exec(
            select(Product).where(
                Product.platform == shop.platform,
                Product.shop_id == shop.shop_id,
                Product.status != "deleted",
            )
        ).all()
        for product in products:
            if product.product_id in active_ids:
                continue
            product.status = "deleted"
            product.updated_at = now
            self.session.add(product)
            deleted += 1
            skus = self.session.exec(
                select(ProductSku).where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == product.product_id,
                    ProductSku.status != "product_deleted",
                )
            ).all()
            for sku in skus:
                sku.status = "product_deleted"
                sku.updated_at = now
                self.session.add(sku)
        self.session.commit()
        return deleted

    def _mark_cookie_invalid(self, shop: Shop, snapshot: CookieSnapshot) -> None:
        now = datetime.now()
        shop.cookie_status = "invalid"
        shop.last_cookie_check_at = now
        shop.updated_at = now
        snapshot.status = "invalid"
        self.session.add(shop)
        self.session.add(snapshot)
        self.session.commit()

    @staticmethod
    def _user_agent(shop: Shop, snapshot: CookieSnapshot) -> str | None:
        for source in (shop.browser_env_json, snapshot.storage_state_json):
            if not isinstance(source, dict):
                continue
            browser = source.get("browser")
            if isinstance(browser, dict) and browser.get("user_agent"):
                return str(browser["user_agent"])
            if source.get("user_agent"):
                return str(source["user_agent"])
        return None


def build_product_data(*, tab: str, current: int, page_size: int) -> str:
    json_body = {
        "tab": tab,
        "pagination": {"current": int(current), "pageSize": int(page_size)},
        "filtertab": "",
        "filter": {},
        "table": {},
    }
    data_value = {
        "url": "/taobao/manager/table.htm",
        "jsonBody": json.dumps(json_body, separators=(",", ":"), ensure_ascii=False),
    }
    return json.dumps(data_value, separators=(",", ":"), ensure_ascii=False)


def parse_mtop_result(resp_json: dict[str, Any]) -> dict[str, Any]:
    ret = resp_json.get("ret", [])
    ret_text = ", ".join(str(item) for item in ret) if isinstance(ret, list) else str(ret)
    if "SUCCESS" not in ret_text.upper() and "调用成功" not in ret_text:
        raise HTTPException(status_code=400, detail=f"淘宝商品接口请求失败：{ret_text}")

    data = resp_json.get("data", {})
    payload = data.get("result") if isinstance(data, dict) else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="淘宝商品接口 result 不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="淘宝商品接口返回结构未识别")
    if not payload.get("success"):
        raise HTTPException(status_code=400, detail=f"淘宝商品接口业务失败：{payload}")
    return payload


def title_from_item(item: dict[str, Any]) -> str:
    item_desc = item.get("itemDesc", {})
    desc_list = item_desc.get("desc", []) if isinstance(item_desc, dict) else []
    if not isinstance(desc_list, list):
        return ""
    for row in desc_list:
        if not isinstance(row, dict):
            continue
        copy_text = text(row.get("copyText"))
        row_text = text(row.get("text"))
        if copy_text:
            return copy_text
        if row_text and not row_text.startswith("ID:"):
            return row_text
    return ""


def image_from_item(item: dict[str, Any]) -> str:
    item_desc = item.get("itemDesc", {})
    if not isinstance(item_desc, dict):
        return ""
    return normalize_url(item_desc.get("img"))


def status_text_from_item(item: dict[str, Any]) -> str:
    up_shelf = item.get("upShelfDate_m", {})
    status = up_shelf.get("status", {}) if isinstance(up_shelf, dict) else {}
    if isinstance(status, dict):
        return text(status.get("text"))
    return ""


def value_from(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else value


def normalize_url(value: Any) -> str:
    url = text(value)
    if url.startswith("//"):
        return "https:" + url
    return url


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"-?\d+", text(value).replace(",", ""))
    return int(match.group(0)) if match else 0


def to_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text(value).replace(",", ""))
    return float(match.group(0)) if match else 0.0


def truncate(value: str, length: int) -> str:
    return value[:length] if len(value) > length else value


def is_token_expired_error(detail: Any) -> bool:
    text_value = str(detail).upper()
    return "TOKEN_EXPIRED" in text_value or "令牌过期" in text_value or "登录" in text_value
