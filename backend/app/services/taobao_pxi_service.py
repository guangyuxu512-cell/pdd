from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import cookies_to_dict
from app.core.mtop import current_millis, extract_h5_token, generate_mtop_sign, parse_jsonp
from app.models import CookieSnapshot, Product, ProductPxi, Shop


TAOBAO_PXI_APP_KEY = "12574478"
TAOBAO_PXI_API = "mtop.alibaba.pxi.item.query"
TAOBAO_PXI_URL = "https://h5api.m.taobao.com/h5/mtop.alibaba.pxi.item.query/1.0/"
TAOBAO_PXI_PAGE_SIZE = 60
TAOBAO_PXI_CALLBACK = "mtopjsonp1"


class TaobaoPxiSyncService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def sync_shop_pxi(
        self,
        *,
        shop: Shop,
        update_date: str | None = None,
        range_day: str = "30d",
        filter_type: str = "all",
        category: str = "",
        item_title: str = "",
        item_id: str = "",
    ) -> dict[str, Any]:
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        token = extract_h5_token(cookie_dict)
        if not token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 _m_h5_tk，请重新登录店铺后再获取 PXI")

        formatted_date = format_update_date(update_date)
        user_agent = self._user_agent(shop, snapshot)
        try:
            fetched = self._fetch_all_pages(
                cookie_dict=cookie_dict,
                token=token,
                user_agent=user_agent,
                update_date=formatted_date,
                range_day=range_day,
                filter_type=filter_type,
                category=category,
                item_title=item_title,
                item_id=item_id,
            )
        except HTTPException as exc:
            if is_auth_error(exc.detail):
                self._mark_cookie_invalid(shop, snapshot)
            raise

        db_result = self._upsert_pxi(
            shop=shop,
            update_date=formatted_date,
            range_day=range_day,
            rows=fetched["items"],
            single_item=bool(str(item_id or "").strip()),
        )
        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "shop_name": shop.shop_name,
            "update_date": formatted_date,
            "range_day": range_day,
            "page_size": TAOBAO_PXI_PAGE_SIZE,
            "total": fetched["total"],
            "total_pages": fetched["total_pages"],
            "count": len(fetched["items"]),
            **db_result,
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

    def _fetch_all_pages(
        self,
        *,
        cookie_dict: dict[str, str],
        token: str,
        user_agent: str | None,
        update_date: str,
        range_day: str,
        filter_type: str,
        category: str,
        item_title: str,
        item_id: str,
    ) -> dict[str, Any]:
        current = 1
        collected: list[dict[str, Any]] = []
        total = 0
        total_pages = 0
        headers = self._headers(user_agent=user_agent)
        with httpx.Client(
            timeout=max(self.settings.request_timeout_seconds, 30),
            cookies=cookie_dict,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while True:
                data = self._request_page(
                    client=client,
                    token=token,
                    page_no=current,
                    update_date=update_date,
                    range_day=range_day,
                    filter_type=filter_type,
                    category=category,
                    item_title=item_title,
                    item_id=item_id,
                )
                items = data.get("items", []) or []
                if not isinstance(items, list):
                    items = []
                collected.extend(normalize_pxi_item(item) for item in items if isinstance(item, dict))

                total = to_int(data.get("total")) or len(collected)
                total_pages = to_int(data.get("pageCount")) or (
                    math.ceil(total / TAOBAO_PXI_PAGE_SIZE) if TAOBAO_PXI_PAGE_SIZE else 0
                )
                if total_pages <= 0 or current >= total_pages:
                    break
                current += 1
        return {"total": total, "total_pages": total_pages, "items": collected}

    def _request_page(
        self,
        *,
        client: httpx.Client,
        token: str,
        page_no: int,
        update_date: str,
        range_day: str,
        filter_type: str,
        category: str,
        item_title: str,
        item_id: str,
    ) -> dict[str, Any]:
        timestamp = current_millis()
        data_value = {
            "updateDate": update_date,
            "range": range_day,
            "filter": filter_type,
            "category": category,
            "itemTitle": item_title,
            "itemId": item_id,
            "pageNo": int(page_no),
            "pageSize": TAOBAO_PXI_PAGE_SIZE,
            "pxiVersion": "v2",
        }
        data_str = json.dumps(data_value, separators=(",", ":"), ensure_ascii=False)
        params = {
            "jsv": "2.6.1",
            "appKey": TAOBAO_PXI_APP_KEY,
            "t": timestamp,
            "sign": generate_mtop_sign(token, timestamp, TAOBAO_PXI_APP_KEY, data_str),
            "api": TAOBAO_PXI_API,
            "v": "1.0",
            "dataType": "originaljsonp",
            "type": "originaljsonp",
            "callback": TAOBAO_PXI_CALLBACK,
            "data": data_str,
        }
        try:
            response = client.get(TAOBAO_PXI_URL, params=params)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"请求淘宝 PXI 接口失败：{exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"淘宝 PXI 接口返回异常：{response.text[:500]}")
        try:
            payload = parse_jsonp(response.text, TAOBAO_PXI_CALLBACK)
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail=f"淘宝 PXI 接口返回不是有效 JSONP：{response.text[:500]}") from exc
        return parse_pxi_result(payload)

    def _headers(self, *, user_agent: str | None) -> dict[str, str]:
        headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": "https://myseller.taobao.com/home.htm/voc/pxi/",
        }
        if user_agent:
            headers["user-agent"] = user_agent
        return headers

    def _upsert_pxi(
        self,
        *,
        shop: Shop,
        update_date: str,
        range_day: str,
        rows: list[dict[str, Any]],
        single_item: bool,
    ) -> dict[str, int]:
        now = datetime.now()
        inserted = 0
        updated = 0
        active_ids = {row["product_id"] for row in rows if row.get("product_id")}

        for row in rows:
            pxi = self.session.exec(
                select(ProductPxi).where(
                    ProductPxi.platform == shop.platform,
                    ProductPxi.shop_id == shop.shop_id,
                    ProductPxi.product_id == row["product_id"],
                    ProductPxi.range_day == range_day,
                )
            ).first()
            values = {
                "pxi_score": row["pxi_score"],
                "status": "active",
                "raw_json": row["raw"],
                "last_platform_updated_at": now,
                "updated_at": now,
            }
            if pxi:
                for key, value in values.items():
                    setattr(pxi, key, value)
                updated += 1
            else:
                pxi = ProductPxi(
                    platform=shop.platform,
                    shop_id=shop.shop_id,
                    product_id=row["product_id"],
                    update_date=update_date,
                    range_day=range_day,
                    **values,
                )
                inserted += 1
            self.session.add(pxi)

        inactive = 0
        if not single_item:
            existing = self.session.exec(
                select(ProductPxi).where(
                    ProductPxi.platform == shop.platform,
                    ProductPxi.shop_id == shop.shop_id,
                    ProductPxi.range_day == range_day,
                    ProductPxi.status == "active",
                )
            ).all()
            for pxi in existing:
                if pxi.product_id in active_ids:
                    continue
                pxi.status = "inactive"
                pxi.updated_at = now
                self.session.add(pxi)
                inactive += 1

        self.session.commit()
        return {"inserted": inserted, "updated": updated, "inactive": inactive}

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
        return default_user_agent()


def parse_pxi_result(payload: dict[str, Any]) -> dict[str, Any]:
    ret = payload.get("ret", [])
    ret_text = ", ".join(str(item) for item in ret) if isinstance(ret, list) else str(ret)
    if "SUCCESS" not in ret_text.upper() and "调用成功" not in ret_text:
        raise HTTPException(status_code=400, detail=f"淘宝 PXI 接口请求失败：{ret_text}")
    data = payload.get("data", {})
    inner = data.get("data", {}) if isinstance(data, dict) else {}
    if not isinstance(inner, dict):
        raise HTTPException(status_code=502, detail="淘宝 PXI 接口返回结构未识别")
    return inner


def normalize_pxi_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": text(item.get("id")),
        "pxi_score": text(item.get("pxi")),
        "raw": item,
    }


def format_update_date(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        now = datetime.now()
        days_back = 2 if now.hour < 9 else 1
        return (now - timedelta(days=days_back)).strftime("%Y%m%d")
    digits = re.sub(r"\D", "", str(value).strip())
    if len(digits) != 8:
        raise HTTPException(status_code=400, detail="更新日期格式错误，请传 20260429 或 2026-04-29")
    return digits


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


def is_auth_error(message: Any) -> bool:
    value = str(message).upper()
    return "TOKEN_EXPIRED" in value or "登录" in value or "COOKIE" in value or "TOKEN" in value
