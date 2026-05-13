from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import build_cookie_header, cookies_to_dict, extract_cookie_value_from_header
from app.models import CookieSnapshot, Product, ProductSku, Shop


APP_KEY = "12574478"
MTOP_API = "mtop.taobao.sell.pc.manage.async"
MTOP_VERSION = "1.0"
MTOP_URL = "https://h5api.m.taobao.com/h5/mtop.taobao.sell.pc.manage.async/1.0/"
INVENTORY_URL = "https://inventorymanage.taobao.com/seller/inventory/editormanager/v2/unify/unifyCommit"


class TaobaoRelistService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def relist_products(
        self,
        *,
        shop: Shop,
        product_ids: list[str],
        unified_stock: int = 3,
        stock_mode: str = "per_sku",
        edit_price: bool = True,
        update_inventory: bool = True,
        upshelf: bool = True,
        dry_run: bool = False,
        wait_min_seconds: float = 1.0,
        wait_max_seconds: float = 2.5,
    ) -> dict[str, Any]:
        product_ids = list(dict.fromkeys([str(product_id).strip() for product_id in product_ids if str(product_id).strip()]))
        if not product_ids:
            raise HTTPException(status_code=400, detail="请先勾选商品")
        if stock_mode not in ("per_sku", "total_split"):
            raise HTTPException(status_code=400, detail="库存模式只支持 per_sku 或 total_split")

        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        full_cookie_header = snapshot.cookie_header_text or build_cookie_header(snapshot.cookies_json)
        mtop_cookie_header = build_cookie_header(snapshot.cookies_json, target_host="h5api.m.taobao.com")
        seller_cookie_header = build_cookie_header(snapshot.cookies_json, target_host="myseller.taobao.com")
        inventory_cookie_header = build_cookie_header(snapshot.cookies_json, target_host="inventorymanage.taobao.com")
        mtop_token = (
            extract_cookie_value_from_header(mtop_cookie_header, "_m_h5_tk")
            or extract_cookie_value_from_header(full_cookie_header, "_m_h5_tk")
            or cookie_dict.get("_m_h5_tk")
            or ""
        ).split("_", 1)[0]
        xsrf_token = (
            extract_cookie_value_from_header(inventory_cookie_header, "XSRF-TOKEN")
            or extract_cookie_value_from_header(full_cookie_header, "XSRF-TOKEN")
            or cookie_dict.get("XSRF-TOKEN")
            or ""
        )
        if not mtop_token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 _m_h5_tk，请重新登录店铺")
        if update_inventory and not xsrf_token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 XSRF-TOKEN，请重新登录店铺")

        user_agent = self._user_agent(shop, snapshot)
        wait_min, wait_max = normalize_wait(wait_min_seconds, wait_max_seconds)
        success_items: list[dict[str, Any]] = []
        failed_items: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []

        with httpx.Client(timeout=max(self.settings.request_timeout_seconds, 30)) as client:
            for index, product_id in enumerate(product_ids):
                product = self._product(shop, product_id)
                if not product:
                    skipped_items.append({"product_id": product_id, "reason": "本地商品不存在"})
                    continue
                skus = self._active_skus(shop, product_id)
                if not skus:
                    skipped_items.append({"product_id": product_id, "title": product.title, "reason": "没有可用 SKU"})
                    continue
                missing_prices = [sku.sku_id for sku in skus if sku.normal_sale_price is None]
                if missing_prices:
                    skipped_items.append(
                        {
                            "product_id": product_id,
                            "title": product.title,
                            "reason": f"存在 {len(missing_prices)} 个 SKU 缺正常售价",
                            "sku_ids": missing_prices[:20],
                        }
                    )
                    continue

                stock_summary = build_stock_summary(skus, unified_stock=unified_stock, stock_mode=stock_mode)
                planned_item_price = select_item_price_from_stocked_skus(skus, stock_summary=stock_summary if update_inventory else None)
                row = {
                    "product_id": product_id,
                    "title": product.title,
                    "sku_count": len(skus),
                    "total_stock": stock_summary["total_stock"],
                    "normal_price_min": min(float(sku.normal_sale_price or 0) for sku in skus),
                    "normal_price_max": max(float(sku.normal_sale_price or 0) for sku in skus),
                    "planned_item_price": planned_item_price,
                    "planned_sku_prices": [
                        {
                            "sku_id": sku.sku_id,
                            "sku_name": sku.sku_name,
                            "stock": int((stock_summary["stock_by_sku"] if update_inventory else {}).get(sku.sku_id, sku.stock or 0)),
                            "price": float(sku.normal_sale_price or 0),
                        }
                        for sku in skus
                    ],
                }
                if dry_run:
                    success_items.append({**row, "dry_run": True, "message": "只模拟不提交"})
                    continue

                try:
                    sleep_random(wait_min, wait_max)
                    if edit_price:
                        edit_result = self._edit_price(
                            client=client,
                            product=product,
                            skus=skus,
                            mtop_token=mtop_token,
                            cookie_header=full_cookie_header or mtop_cookie_header or seller_cookie_header,
                            user_agent=user_agent,
                        )
                        row["edit_price_result"] = edit_result
                        if not edit_result["success"]:
                            failed_items.append({**row, "failed_stage": "editSku", "error_message": edit_result["message"]})
                            continue
                        sleep_random(wait_min, wait_max)

                    if update_inventory:
                        inventory_result = self._edit_inventory(
                            client=client,
                            product=product,
                            skus=skus,
                            stock_summary=stock_summary,
                            keep_onsale=bool(upshelf or product.status in ("onsale", "active")),
                            xsrf_token=xsrf_token,
                            cookie_header=full_cookie_header or inventory_cookie_header,
                            user_agent=user_agent,
                        )
                        row["inventory_result"] = inventory_result
                        if not inventory_result["success"]:
                            failed_items.append({**row, "failed_stage": "unifyCommit", "error_message": inventory_result["message"]})
                            continue
                        sleep_random(wait_min, wait_max)

                    if upshelf:
                        upshelf_result = self._upshelf_item(
                            client=client,
                            product_id=product_id,
                            mtop_token=mtop_token,
                            cookie_header=full_cookie_header or mtop_cookie_header or seller_cookie_header,
                            user_agent=user_agent,
                        )
                        row["upshelf_result"] = upshelf_result
                        if not upshelf_result["success"]:
                            failed_items.append({**row, "failed_stage": "upShelf", "error_message": upshelf_result["message"]})
                            continue

                    self._mark_relisted(
                        product=product,
                        skus=skus,
                        stock_summary=stock_summary,
                        edit_price=edit_price,
                        update_inventory=update_inventory,
                        upshelf=upshelf,
                    )
                    success_items.append(row)
                except Exception as exc:
                    failed_items.append({**row, "failed_stage": "exception", "error_message": str(exc)})

                if index < len(product_ids) - 1:
                    sleep_random(wait_min, wait_max)

        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "requested_products": len(product_ids),
            "success_count": len(success_items),
            "failed_count": len(failed_items),
            "skipped_count": len(skipped_items),
            "dry_run": bool(dry_run),
            "success_items": success_items,
            "failed_items": failed_items,
            "skipped_items": skipped_items,
        }

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

    def _product(self, shop: Shop, product_id: str) -> Product | None:
        return self.session.exec(
            select(Product).where(
                Product.platform == shop.platform,
                Product.shop_id == shop.shop_id,
                Product.product_id == product_id,
                Product.status != "deleted",
            )
        ).first()

    def _active_skus(self, shop: Shop, product_id: str) -> list[ProductSku]:
        return list(
            self.session.exec(
                select(ProductSku)
                .where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == product_id,
                    ProductSku.status == "active",
                )
                .order_by(ProductSku.id)
            ).all()
        )

    def _edit_price(
        self,
        *,
        client: httpx.Client,
        product: Product,
        skus: list[ProductSku],
        mtop_token: str,
        cookie_header: str,
        user_agent: str,
        stock_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sku_rows = [
            {
                "skuId": int(sku.sku_id),
                "prop": sku.sku_name or sku.sku_code or "",
                "skuPrice": price_text(float(sku.normal_sale_price or 0)),
                "skuOuterId": sku.sku_code or "",
            }
            for sku in skus
        ]
        planned_item_price = select_item_price_from_stocked_skus(skus, stock_summary=stock_summary)
        data_str = json_dumps(
            {
                "url": "/taobao/manager/fastEdit.htm?optType=editSku&action=submit",
                "jsonBody": json_dumps(
                    {
                        "textTitle": product.title,
                        "price": price_text(planned_item_price),
                        "skuTable": {"dataSource": sku_rows, "selectedRowKeys": []},
                        "quantityType": "all",
                        "itemId": product.product_id,
                    }
                ),
            }
        )
        last_result: dict[str, Any] | None = None
        for attempt in range(1, 2):
            payload = self._post_mtop(client, mtop_token, cookie_header, user_agent, data_str)
            success, message, result_payload = parse_mtop_result(payload)
            last_result = {
                "success": success,
                "message": message,
                "payload": payload,
                "result_payload": result_payload,
                "attempts": attempt,
                "planned_item_price": planned_item_price,
                "planned_sku_prices": sku_rows,
            }
            return last_result
        return last_result or {"success": False, "message": "改价失败", "attempts": 0}

    def _edit_inventory(
        self,
        *,
        client: httpx.Client,
        product: Product,
        skus: list[ProductSku],
        stock_summary: dict[str, Any],
        keep_onsale: bool,
        xsrf_token: str,
        cookie_header: str,
        user_agent: str,
    ) -> dict[str, Any]:
        payload = build_inventory_payload(product, skus, stock_summary, keep_onsale=keep_onsale)
        last_result: dict[str, Any] | None = None
        for attempt in range(1, 4):
            response = client.post(
                f"{INVENTORY_URL}?displayTab=single&itemId={product.product_id}&from=taobao-sellManage-edit",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json",
                    "origin": "https://inventorymanage.taobao.com",
                    "referer": (
                        "https://inventorymanage.taobao.com/qn/inventory/editInventory"
                        f"?hideHeader=5&hasDrawerHeader=true&title=%E7%BC%96%E8%BE%91%E5%BA%93%E5%AD%98"
                        f"&from=taobao-sellManage-edit&showChangeInvMode=false&itemId={product.product_id}"
                    ),
                    "user-agent": user_agent,
                    "x-requested-with": "XMLHttpRequest",
                    "x-xsrf-token": xsrf_token,
                    "cookie": cookie_header,
                },
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            response.raise_for_status()
            result = response.json()
            success = bool(result.get("success") is True or result.get("code") in (0, "0"))
            if not success and result.get("data") is not None and result.get("code") in (None, 0, "0"):
                success = True
            message = str(result.get("message") or result.get("msg") or result.get("errorMsg") or result.get("resultMsg") or "")
            last_result = {"success": success, "message": message or ("success" if success else "unknown"), "payload": result, "attempts": attempt}
            if success or not is_transient_platform_error(message, result):
                return last_result
            sleep_random(10.0, 20.0)
        return last_result or {"success": False, "message": "改库存失败", "attempts": 0}

    def _upshelf_item(
        self,
        *,
        client: httpx.Client,
        product_id: str,
        mtop_token: str,
        cookie_header: str,
        user_agent: str,
    ) -> dict[str, Any]:
        data_str = json_dumps(
            {
                "url": "/taobao/manager/fastEdit.htm?optType=upShelf&action=submit",
                "jsonBody": json_dumps({"itemId": product_id}),
            }
        )
        last_result: dict[str, Any] | None = None
        for attempt in range(1, 4):
            payload = self._post_mtop(client, mtop_token, cookie_header, user_agent, data_str)
            success, message, result_payload = parse_mtop_result(payload)
            last_result = {
                "success": success,
                "message": message,
                "payload": payload,
                "result_payload": result_payload,
                "attempts": attempt,
            }
            if success or not is_transient_platform_error(message, result_payload):
                return last_result
            sleep_random(10.0, 20.0)
        return last_result or {"success": False, "message": "上架失败", "attempts": 0}

    def _post_mtop(
        self,
        client: httpx.Client,
        mtop_token: str,
        cookie_header: str,
        user_agent: str,
        data_str: str,
    ) -> dict[str, Any]:
        ts_ms = str(int(time.time() * 1000))
        sign = hashlib.md5(f"{mtop_token}&{ts_ms}&{APP_KEY}&{data_str}".encode("utf-8")).hexdigest()
        response = client.post(
            MTOP_URL,
            params={
                "jsv": "2.6.1",
                "appKey": APP_KEY,
                "t": ts_ms,
                "sign": sign,
                "api": MTOP_API,
                "v": MTOP_VERSION,
                "ttid": "11320@taobao_WEB_9.9.99",
                "type": "originaljson",
                "dataType": "json",
            },
            headers={
                "accept": "application/json",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://myseller.taobao.com",
                "pragma": "no-cache",
                "referer": "https://myseller.taobao.com/home.htm/SellManage/in_stock?current=1&pageSize=60",
                "user-agent": user_agent,
                "cookie": cookie_header,
            },
            data={"data": data_str},
        )
        response.raise_for_status()
        return response.json()

    def _mark_relisted(
        self,
        *,
        product: Product,
        skus: list[ProductSku],
        stock_summary: dict[str, Any],
        edit_price: bool,
        update_inventory: bool,
        upshelf: bool,
    ) -> None:
        now = datetime.now()
        if upshelf:
            product.status = "onsale"
        if update_inventory:
            product.stock = int(stock_summary["total_stock"])
        if edit_price:
            product.price = select_item_price_from_stocked_skus(skus, stock_summary=stock_summary if update_inventory else None)
        product.updated_at = now
        self.session.add(product)
        stock_by_sku = stock_summary["stock_by_sku"]
        for sku in skus:
            if update_inventory:
                sku.stock = int(stock_by_sku.get(sku.sku_id, 0))
            if edit_price and sku.normal_sale_price is not None:
                sku.taobao_price = float(sku.normal_sale_price)
            sku.updated_at = now
            self.session.add(sku)
        self.session.commit()

    @staticmethod
    def _user_agent(shop: Shop, snapshot: CookieSnapshot) -> str:
        for source in (shop.browser_env_json, snapshot.storage_state_json):
            if not isinstance(source, dict):
                continue
            browser = source.get("browser")
            if isinstance(browser, dict) and browser.get("user_agent"):
                return str(browser["user_agent"])
            if source.get("user_agent"):
                return str(source["user_agent"])
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


def build_stock_summary(skus: list[ProductSku], *, unified_stock: int, stock_mode: str) -> dict[str, Any]:
    stock = max(0, int(unified_stock or 0))
    if stock_mode == "total_split":
        base = stock // len(skus)
        remainder = stock % len(skus)
        values = [base + (1 if index < remainder else 0) for index in range(len(skus))]
    else:
        values = [stock for _sku in skus]
    return {
        "total_stock": sum(values),
        "stock_by_sku": {sku.sku_id: values[index] for index, sku in enumerate(skus)},
    }


def build_inventory_payload(
    product: Product,
    skus: list[ProductSku],
    stock_summary: dict[str, Any],
    *,
    keep_onsale: bool,
) -> dict[str, Any]:
    value_rows = []
    shelf_status = 1 if keep_onsale else 0
    shelf_tag = "上架" if keep_onsale else "仓库中"
    for sku in skus:
        operate_quantity = int(stock_summary["stock_by_sku"].get(sku.sku_id, 0))
        value_rows.append(
            {
                "skuInfo": {
                    "itemId": int(product.product_id),
                    "skuId": int(sku.sku_id),
                    "prop": sku.sku_name or sku.sku_code or "",
                    "skuName": sku.sku_name or sku.sku_code or "",
                    "image": sku.image_url or product.main_image_url or "",
                    "serialNumber": sku.sku_code or "",
                    "totalQuantity": operate_quantity,
                    "deltaQuantity": 0,
                    "tags": [shelf_tag],
                    "detailQuantity": None,
                },
                "deleteQuantityList": None,
                "quantityList": [
                    {
                        "deliveryTime": "48小时内发货",
                        "deliveryType": None,
                        "invType": "spot",
                        "adjustQuantity": {"adjustType": {"value": "add"}, "operateQuantity": operate_quantity},
                        "hasAdjustDeliveryTime": False,
                        "planInstanceId": None,
                        "sellableQuantity": operate_quantity,
                        "withholdingQuantity": 0,
                        "bizOrderId": None,
                        "batchId": None,
                    }
                ],
            }
        )
    return {
        "shelfStatus": shelf_status,
        "itemInfo": {
            "itemId": product.product_id,
            "invMode": "普通商品库存",
            "totalQuantity": 0,
            "itemTitle": product.title,
            "subItems": [
                {"label": "商品ID", "valueKey": "itemId"},
                {"label": "库存模式", "valueKey": "invMode"},
                {"label": "总可售库存", "valueKey": "totalQuantity"},
            ],
            "uiType": "itemInfo",
            "pictUrl": product.main_image_url or "",
            "templateId": "",
            "actions": [],
        },
        "currentDeliveryTimeType": None,
        "planTemplateInfo": {"saleTimeRange": None},
        "needCleanOldPlan": False,
        "value": value_rows,
        "UUID": str(uuid.uuid4()),
    }


def select_item_price_from_stocked_skus(skus: list[ProductSku], *, stock_summary: dict[str, Any] | None = None) -> float:
    candidates: list[float] = []
    stock_by_sku = (stock_summary or {}).get("stock_by_sku") or {}
    for sku in skus:
        if sku.normal_sale_price is None:
            continue
        if stock_summary is not None:
            has_stock = int(stock_by_sku.get(sku.sku_id, 0) or 0) > 0
        else:
            has_stock = int(sku.stock or 0) > 0
        if has_stock:
            candidates.append(float(sku.normal_sale_price))
    if candidates:
        return max(candidates)
    fallback = [float(sku.normal_sale_price) for sku in skus if sku.normal_sale_price is not None]
    if not fallback:
        raise ValueError("没有可用正常售价")
    return max(fallback)


def extract_cookie_value(cookie_dict: dict[str, str], key: str) -> str:
    return str(cookie_dict.get(key) or "").strip()


def parse_mtop_result(response_payload: dict[str, Any]) -> tuple[bool, str, Any]:
    ret = response_payload.get("ret", [])
    ret_text = ",".join(ret) if isinstance(ret, list) else str(ret)
    success = "SUCCESS" in ret_text.upper() or "调用成功" in ret_text
    result_payload = None
    data = response_payload.get("data") or {}
    if isinstance(data, dict) and "result" in data:
        result_payload = data.get("result")
        if isinstance(result_payload, str):
            try:
                result_payload = json.loads(result_payload)
            except ValueError:
                pass
        if isinstance(result_payload, dict) and result_payload.get("success") is True:
            success = True
    return success, ret_text, result_payload


def is_transient_platform_error(message: Any, payload: Any = None) -> bool:
    text_value = f"{message} {payload}".upper()
    transient_markers = (
        "FAIL_SYS_USER_VALIDATE",
        "RGV587",
        "被挤爆",
        "稍后重试",
        "请稍后",
        "系统繁忙",
        "限流",
        "BUSY",
    )
    return any(marker.upper() in text_value for marker in transient_markers)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def price_text(value: float) -> str:
    return f"{float(value):.2f}"


def normalize_wait(min_seconds: float, max_seconds: float) -> tuple[float, float]:
    try:
        wait_min = float(min_seconds)
    except (TypeError, ValueError):
        wait_min = 0.0
    try:
        wait_max = float(max_seconds)
    except (TypeError, ValueError):
        wait_max = wait_min
    wait_min = max(0.0, wait_min)
    wait_max = max(wait_min, wait_max)
    return wait_min, wait_max


def sleep_random(wait_min: float, wait_max: float) -> None:
    if wait_max <= 0:
        return
    time.sleep(random.uniform(wait_min, wait_max))
