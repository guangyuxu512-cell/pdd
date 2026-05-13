from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import cookies_to_dict
from app.models import CookieSnapshot, Product, ProductSku, Shop


PUBLISH_URL = "https://item.upload.taobao.com/sell/v2/publish.htm"


class TaobaoSkuSyncService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def sync_product_skus(
        self,
        *,
        shop: Shop,
        product_ids: list[str],
        max_workers: int = 5,
        wait_min_seconds: float = 0.5,
        wait_max_seconds: float = 2.0,
    ) -> dict[str, Any]:
        normalized_ids = [str(item).strip() for item in product_ids if str(item).strip()]
        if not normalized_ids:
            raise HTTPException(status_code=400, detail="请先勾选要获取 SKU 的商品")

        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        user_agent = self._user_agent(shop, snapshot) or default_user_agent()
        workers = max(1, min(5, int(max_workers or 1)))
        wait_min, wait_max = normalize_wait(wait_min_seconds, wait_max_seconds)
        products = self._products_by_id(shop, normalized_ids)

        rows: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    self._fetch_product_skus,
                    product_id=product_id,
                    cookie_dict=cookie_dict,
                    user_agent=user_agent,
                    fallback_image=products.get(product_id).main_image_url if products.get(product_id) else None,
                    wait_min=wait_min,
                    wait_max=wait_max,
                ): product_id
                for product_id in normalized_ids
            }
            for future in as_completed(future_map):
                product_id = future_map[future]
                try:
                    rows.extend(future.result())
                except Exception as exc:
                    failed.append({"product_id": product_id, "error": str(exc)})

        if failed and any(is_auth_error(item["error"]) for item in failed):
            self._mark_cookie_invalid(shop, snapshot)

        db_result = self._upsert_skus(shop=shop, requested_ids=normalized_ids, rows=rows)
        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "requested_products": len(normalized_ids),
            "count": len(rows),
            "failed": failed,
            **db_result,
        }

    def _mark_cookie_invalid(self, shop: Shop, snapshot: CookieSnapshot) -> None:
        now = datetime.now()
        shop.cookie_status = "invalid"
        shop.last_cookie_check_at = now
        shop.updated_at = now
        snapshot.status = "invalid"
        self.session.add(shop)
        self.session.add(snapshot)
        self.session.commit()

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

    def _products_by_id(self, shop: Shop, product_ids: list[str]) -> dict[str, Product]:
        products = self.session.exec(
            select(Product).where(
                Product.platform == shop.platform,
                Product.shop_id == shop.shop_id,
                Product.product_id.in_(product_ids),
            )
        ).all()
        return {product.product_id: product for product in products}

    def _fetch_product_skus(
        self,
        *,
        product_id: str,
        cookie_dict: dict[str, str],
        user_agent: str,
        fallback_image: str | None,
        wait_min: float,
        wait_max: float,
    ) -> list[dict[str, Any]]:
        if wait_max > 0:
            time.sleep(random.uniform(wait_min, wait_max))

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-site",
            "upgrade-insecure-requests": "1",
            "user-agent": user_agent,
        }
        try:
            with httpx.Client(
                timeout=max(self.settings.request_timeout_seconds, 30),
                cookies=cookie_dict,
                headers=headers,
                follow_redirects=True,
            ) as client:
                response = client.get(PUBLISH_URL, params={"itemId": product_id, "fromAIPublish": "true"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"请求 SKU 页面失败：{exc}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"SKU 页面返回异常：HTTP {response.status_code}")
        if "login.taobao.com" in str(response.url):
            raise RuntimeError("已跳转登录，cookie 可能失效")

        sku_objects = extract_sku_objects(response.text)
        return [normalize_sku(product_id, obj, fallback_image=fallback_image) for obj in sku_objects]

    def _upsert_skus(self, *, shop: Shop, requested_ids: list[str], rows: list[dict[str, Any]]) -> dict[str, int]:
        now = datetime.now()
        inserted = 0
        updated = 0
        active_keys = {(row["product_id"], row["sku_id"]) for row in rows if row.get("sku_id")}

        for row in rows:
            sku = self.session.exec(
                select(ProductSku).where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == row["product_id"],
                    ProductSku.sku_id == row["sku_id"],
                )
            ).first()
            values = {
                "sku_code": truncate(row["sku_code"], 255) or None,
                "sku_name": truncate(row["sku_name"], 500) or None,
                "image_url": truncate(row["image_url"], 1000) or None,
                "taobao_price": row["taobao_price"],
                "stock": row["stock"],
                "status": "active",
                "props_json": row["props"],
                "raw_json": row["raw"],
                "last_platform_updated_at": now,
                "updated_at": now,
            }
            if sku:
                for key, value in values.items():
                    setattr(sku, key, value)
                updated += 1
            else:
                sku = ProductSku(
                    platform=shop.platform,
                    shop_id=shop.shop_id,
                    product_id=truncate(row["product_id"], 128),
                    sku_id=truncate(row["sku_id"], 128),
                    **values,
                )
                inserted += 1
            self.session.add(sku)

        inactive = 0
        existing = self.session.exec(
            select(ProductSku).where(
                ProductSku.platform == shop.platform,
                ProductSku.shop_id == shop.shop_id,
                ProductSku.product_id.in_(requested_ids),
                ProductSku.status == "active",
            )
        ).all()
        for sku in existing:
            if (sku.product_id, sku.sku_id) in active_keys:
                continue
            sku.status = "inactive"
            sku.updated_at = now
            self.session.add(sku)
            inactive += 1

        self._update_product_price_stock_from_skus(shop=shop, product_ids=requested_ids, now=now)
        self.session.commit()
        return {"inserted": inserted, "updated": updated, "inactive": inactive}

    def _update_product_price_stock_from_skus(self, *, shop: Shop, product_ids: list[str], now: datetime) -> None:
        for product_id in product_ids:
            product = self.session.exec(
                select(Product).where(
                    Product.platform == shop.platform,
                    Product.shop_id == shop.shop_id,
                    Product.product_id == product_id,
                )
            ).first()
            if not product:
                continue
            skus = list(
                self.session.exec(
                    select(ProductSku).where(
                        ProductSku.platform == shop.platform,
                        ProductSku.shop_id == shop.shop_id,
                        ProductSku.product_id == product_id,
                        ProductSku.status == "active",
                    )
                ).all()
            )
            if not skus:
                continue
            stocked_prices = [float(sku.taobao_price or 0) for sku in skus if int(sku.stock or 0) > 0]
            all_prices = [float(sku.taobao_price or 0) for sku in skus]
            product.price = max(stocked_prices or all_prices or [product.price or 0])
            product.stock = sum(int(sku.stock or 0) for sku in skus)
            product.last_platform_updated_at = now
            product.updated_at = now
            self.session.add(product)

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


def extract_sku_objects(html: str) -> list[dict[str, Any]]:
    sku_objects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'"skuId"\s*:\s*(\d+)', html):
        sku_id = match.group(1)
        if sku_id in seen:
            continue
        start = find_json_object_start(html, match.start())
        if start < 0:
            continue
        end = find_json_object_end(html, start)
        if end < 0:
            continue
        try:
            obj = json.loads(html[start:end])
        except json.JSONDecodeError:
            continue
        if "skuOuterId" not in obj:
            continue
        seen.add(sku_id)
        sku_objects.append(obj)
    return sku_objects


def find_json_object_start(html: str, pos: int) -> int:
    depth = 0
    for index in range(pos, max(pos - 5000, 0), -1):
        char = html[index]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth == 0:
                return index
            depth -= 1
    return -1


def find_json_object_end(html: str, start: int) -> int:
    depth = 0
    in_str = False
    escape = False
    for index in range(start, min(start + 10000, len(html))):
        char = html[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def normalize_sku(product_id: str, obj: dict[str, Any], *, fallback_image: str | None) -> dict[str, Any]:
    props = [str(prop.get("text")).strip() for prop in obj.get("props", []) or [] if isinstance(prop, dict) and prop.get("text")]
    pictures = []
    for pic in obj.get("skuPicture", []) or []:
        if isinstance(pic, dict):
            url_value = pic.get("url") or pic.get("picUrl") or pic.get("src")
            if url_value:
                pictures.append(normalize_url(url_value))
        elif isinstance(pic, str):
            pictures.append(normalize_url(pic))

    return {
        "product_id": str(product_id),
        "sku_id": text(obj.get("skuId")),
        "sku_code": text(obj.get("skuOuterId")),
        "sku_name": " / ".join(props),
        "image_url": pictures[0] if pictures else (fallback_image or ""),
        "taobao_price": first_float(obj, ("skuPrice", "price", "salePrice", "sellPrice", "discountPrice")),
        "stock": first_int(obj, ("skuStock", "stock", "quantity", "sellableQuantity", "totalQuantity")),
        "props": props,
        "raw": obj,
    }


def normalize_url(value: Any) -> str:
    url = text(value)
    if url.startswith("//"):
        return "https:" + url
    return url


def normalize_wait(min_seconds: float, max_seconds: float) -> tuple[float, float]:
    wait_min = max(0.0, float(min_seconds or 0))
    wait_max = max(0.0, float(max_seconds or 0))
    if wait_max < wait_min:
        wait_max = wait_min
    return wait_min, wait_max


def default_user_agent() -> str:
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


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


def first_int(obj: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in obj and obj.get(key) not in (None, ""):
            return to_int(obj.get(key))
    return 0


def first_float(obj: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in obj and obj.get(key) not in (None, ""):
            return to_float(obj.get(key))
    return 0.0


def truncate(value: str, length: int) -> str:
    return value[:length] if len(value) > length else value


def is_auth_error(message: str) -> bool:
    text_value = str(message).lower()
    return "login.taobao.com" in text_value or "cookie" in text_value or "登录" in text_value or "token" in text_value
