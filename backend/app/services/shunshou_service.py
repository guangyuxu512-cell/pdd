from __future__ import annotations

import re
import json
import random
import time
import urllib.parse
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import build_cookie_header, cookies_to_dict, extract_cookie_value_from_header
from app.models import (
    CookieSnapshot,
    Product,
    ProductPxi,
    ProductSku,
    ShunshouActivity,
    ShunshouActivityItem,
    Shop,
)


LIST_URL = "https://shell.mkt.taobao.com/taobaoTied/getList"
LIST_REFERER = "https://shell.mkt.taobao.com/taobaoTied/index"
ITEM_URL = "https://shell.mkt.taobao.com/taobaoTied/getItemList"
DETAIL_URL = "https://shell.mkt.taobao.com/taobaoTied/getDetailList"
SUBMIT_URL = "https://shell.mkt.taobao.com/taobaoTied/addOrUpdateDetails"
PAGE_SIZE = 20
STATUS_MAP = {
    0: "未知",
    1: "未开始",
    2: "进行中",
    3: "已结束",
    4: "已暂停",
}


class ShunshouService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def sync_activities(self, *, shop: Shop, activity_status: str = "null") -> dict[str, Any]:
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        cookie_header = snapshot.cookie_header_text or build_cookie_header(snapshot.cookies_json)
        cookie_dict["__cookie_header"] = cookie_header
        xsrf_token = extract_cookie_value_from_header(cookie_header, "XSRF-TOKEN") or cookie_dict.get("XSRF-TOKEN")
        if not xsrf_token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 XSRF-TOKEN，请重新登录店铺后再获取顺手活动")
        user_agent = self._user_agent(shop, snapshot)
        try:
            rows = self._fetch_activity_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_status=activity_status,
            )
        except HTTPException as exc:
            if is_auth_error(exc.detail):
                self._mark_cookie_invalid(shop, snapshot)
            raise
        result = self._upsert_activities(shop=shop, rows=rows)
        return {"platform": shop.platform, "shop_id": shop.shop_id, "count": len(rows), **result}

    def sync_activity_items(
        self,
        *,
        shop: Shop,
        activity_id: str,
        cross_shop: bool = False,
        auction_status: int = 0,
    ) -> dict[str, Any]:
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        cookie_header = snapshot.cookie_header_text or build_cookie_header(snapshot.cookies_json)
        cookie_dict["__cookie_header"] = cookie_header
        xsrf_token = extract_cookie_value_from_header(cookie_header, "XSRF-TOKEN") or cookie_dict.get("XSRF-TOKEN")
        if not xsrf_token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 XSRF-TOKEN，请重新登录店铺后再获取活动商品")
        user_agent = self._user_agent(shop, snapshot)
        try:
            rows = self._fetch_activity_item_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=str(activity_id).strip(),
                cross_shop=cross_shop,
                auction_status=int(auction_status),
            )
        except HTTPException as exc:
            if is_auth_error(exc.detail):
                self._mark_cookie_invalid(shop, snapshot)
            raise
        result = self._upsert_activity_items(
            shop=shop,
            activity_id=str(activity_id).strip(),
            auction_status=int(auction_status),
            rows=rows,
        )
        return {"platform": shop.platform, "shop_id": shop.shop_id, "count": len(rows), **result}

    def one_click_signup(
        self,
        *,
        shop: Shop,
        pxi_min: float = 70,
        sold_total_min: int = 3,
        target_activity_count: int = 2,
        custom_capacity_limit: int = 160,
        reserve_item_count: int = 3,
        real_capacity_fallback: int = 171,
        cross_shop: bool = False,
        batch_size: int = 25,
        min_wait_seconds: float = 0.6,
        max_wait_seconds: float = 1.8,
        dry_run: bool = False,
        assignments_by_activity: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        cookie_header = snapshot.cookie_header_text or build_cookie_header(snapshot.cookies_json)
        cookie_dict["__cookie_header"] = cookie_header
        xsrf_token = extract_cookie_value_from_header(cookie_header, "XSRF-TOKEN") or cookie_dict.get("XSRF-TOKEN")
        if not xsrf_token:
            raise HTTPException(status_code=400, detail="cookie 中未找到 XSRF-TOKEN，请重新登录店铺后再报名")
        user_agent = self._user_agent(shop, snapshot)

        target_activity_count = max(1, int(target_activity_count or 1))
        custom_capacity_limit = max(1, min(171, int(custom_capacity_limit or 160)))
        reserve_item_count = max(0, int(reserve_item_count or 0))
        real_capacity_fallback = max(1, int(real_capacity_fallback or 171))
        batch_size = max(1, int(batch_size or 25))
        wait_min, wait_max = normalize_wait(min_wait_seconds, max_wait_seconds)

        base_items = self._eligible_signup_items(shop=shop, pxi_min=float(pxi_min), sold_total_min=int(sold_total_min))
        skipped_items: list[dict[str, Any]] = []
        if assignments_by_activity is None:
            activity_map, item_activity_map = self._eligible_activity_map(shop=shop, base_items=base_items)
            assignments_by_activity, skipped_items = assign_items_to_activities(
                base_items=base_items,
                activity_map=activity_map,
                item_activity_map=item_activity_map,
                target_activity_count=target_activity_count,
                custom_capacity_limit=custom_capacity_limit,
                reserve_item_count=reserve_item_count,
                real_capacity_fallback=real_capacity_fallback,
            )
        else:
            assignments_by_activity = normalize_assignments(assignments_by_activity)

        execution_results: list[dict[str, Any]] = []
        submitted_sku_count = 0
        for activity_id, product_ids in assignments_by_activity.items():
            new_product_ids = list(dict.fromkeys(text(product_id) for product_id in product_ids if text(product_id)))
            existing_product_ids = self._existing_signed_product_ids(shop=shop, activity_id=activity_id)
            submit_product_ids = list(dict.fromkeys(existing_product_ids + new_product_ids))
            sleep_random(wait_min, wait_max)
            detail_rows = self._fetch_sku_detail_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                product_ids=submit_product_ids,
                cross_shop=cross_shop,
                batch_size=batch_size,
                wait_min=wait_min,
                wait_max=wait_max,
            )
            params, skipped, param_stats = self._build_submit_params(
                shop=shop,
                detail_rows=detail_rows,
                new_product_ids=set(new_product_ids),
                preserve_product_ids=set(existing_product_ids),
            )
            skipped_items.extend(skipped)
            result_row: dict[str, Any] = {
                "activity_id": activity_id,
                "item_count": len(new_product_ids),
                "new_item_count": len(new_product_ids),
                "preserved_item_count": len(existing_product_ids),
                "submit_item_count": len(submit_product_ids),
                "detail_count": len(detail_rows),
                "params_count": len(params),
                "new_params_count": param_stats["new_params_count"],
                "preserved_params_count": param_stats["preserved_params_count"],
                "ignored_sku_count": param_stats["ignored_sku_count"],
                "ignored_product_ids": param_stats["ignored_product_ids"],
                "submitted": False,
            }
            if dry_run:
                result_row["dry_run"] = True
                execution_results.append(result_row)
                continue
            if not params:
                result_row["error"] = "params_count=0"
                execution_results.append(result_row)
                continue
            sleep_random(wait_min, wait_max)
            submit_result = self._submit_signup(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                params=params,
                cross_shop=cross_shop,
            )
            result_row["submitted"] = True
            result_row["result"] = submit_result
            if is_submit_success(submit_result):
                submitted_sku_count += param_stats["new_params_count"]
                self._mark_signup_success(
                    shop=shop,
                    activity_id=activity_id,
                    params=params,
                    submit_result=submit_result,
                    product_ids=new_product_ids,
                )
            execution_results.append(result_row)

        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "candidate_count": len(base_items),
            "assignment_count": sum(len(values) for values in assignments_by_activity.values()),
            "submitted_activity_count": sum(1 for row in execution_results if row.get("submitted")),
            "submitted_sku_count": submitted_sku_count,
            "skipped_count": len(skipped_items),
            "dry_run": bool(dry_run),
            "assignments_by_activity": assignments_by_activity,
            "execution_results": execution_results,
            "skipped_items": skipped_items,
        }

    def preview_signup_candidates(
        self,
        *,
        shop: Shop,
        pxi_min: float = 70,
        sold_total_min: int = 3,
        target_activity_count: int = 2,
        custom_capacity_limit: int = 160,
        reserve_item_count: int = 3,
        real_capacity_fallback: int = 171,
    ) -> dict[str, Any]:
        target_activity_count = max(1, int(target_activity_count or 1))
        custom_capacity_limit = max(1, min(171, int(custom_capacity_limit or 160)))
        reserve_item_count = max(0, int(reserve_item_count or 0))
        real_capacity_fallback = max(1, int(real_capacity_fallback or 171))
        base_items = self._eligible_signup_items(shop=shop, pxi_min=float(pxi_min), sold_total_min=int(sold_total_min))
        activity_map, item_activity_map = self._eligible_activity_map(shop=shop, base_items=base_items)
        assignments_by_activity, skipped_items = assign_items_to_activities(
            base_items=base_items,
            activity_map=activity_map,
            item_activity_map=item_activity_map,
            target_activity_count=target_activity_count,
            custom_capacity_limit=custom_capacity_limit,
            reserve_item_count=reserve_item_count,
            real_capacity_fallback=real_capacity_fallback,
        )
        product_map = {item["product_id"]: item for item in base_items}
        rows_by_product: dict[str, dict[str, Any]] = {}
        for activity_id, product_ids in assignments_by_activity.items():
            activity = activity_map.get(activity_id) or {}
            for product_id in product_ids:
                product = product_map.get(product_id) or {}
                if product_id not in rows_by_product:
                    rows_by_product[product_id] = {
                        "product_id": product_id,
                        "title": product.get("title", ""),
                        "image_url": product.get("image_url", ""),
                        "pxi_score": product.get("pxi_score"),
                        "total_sales": product.get("total_sales"),
                        "joined_count": product.get("joined_count", 0),
                        "signup_price_min": product.get("signup_price_min"),
                        "signup_price_max": product.get("signup_price_max"),
                        "priced_sku_count": product.get("priced_sku_count", 0),
                        "normal_price_min": product.get("normal_price_min"),
                        "normal_price_max": product.get("normal_price_max"),
                        "current_price_min": product.get("current_price_min"),
                        "current_price_max": product.get("current_price_max"),
                        "current_item_price": product.get("current_item_price"),
                        "expected_item_price": product.get("expected_item_price"),
                        "item_price_mismatch": product.get("item_price_mismatch", False),
                        "price_mismatch_count": product.get("price_mismatch_count", 0),
                        "missing_normal_price_count": product.get("missing_normal_price_count", 0),
                        "price_status": product.get("price_status", ""),
                        "activities": [],
                    }
                rows_by_product[product_id]["activities"].append(
                    {
                        "activity_id": activity_id,
                        "activity_name": activity.get("activity_name", ""),
                        "selected": True,
                    }
                )
        rows = list(rows_by_product.values())
        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "candidate_count": len(base_items),
            "assignment_count": sum(len(row.get("activities", [])) for row in rows),
            "assignments_by_activity": assignments_by_activity,
            "rows": rows,
            "skipped_items": skipped_items,
        }

    def check_signup_assignments(
        self,
        *,
        shop: Shop,
        assignments_by_activity: dict[str, list[str]] | None,
        pxi_min: float = 70,
        sold_total_min: int = 3,
    ) -> dict[str, Any]:
        assignments = normalize_assignments(assignments_by_activity or {})
        rows: list[dict[str, Any]] = []
        failed_rows: list[dict[str, Any]] = []

        for activity_id, product_ids in assignments.items():
            for product_id in product_ids:
                row = self._check_signup_assignment(
                    shop=shop,
                    activity_id=activity_id,
                    product_id=product_id,
                    pxi_min=float(pxi_min),
                    sold_total_min=int(sold_total_min),
                )
                rows.append(row)
                if not row["ok"]:
                    failed_rows.append(row)

        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "checked_count": len(rows),
            "passed_count": len(rows) - len(failed_rows),
            "failed_count": len(failed_rows),
            "ok": not failed_rows,
            "rows": rows,
            "failed_rows": failed_rows,
        }

    def _check_signup_assignment(
        self,
        *,
        shop: Shop,
        activity_id: str,
        product_id: str,
        pxi_min: float,
        sold_total_min: int,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        details: dict[str, Any] = {}

        product = self.session.exec(
            select(Product).where(
                Product.platform == shop.platform,
                Product.shop_id == shop.shop_id,
                Product.product_id == product_id,
            )
        ).first()
        if not product:
            reasons.append("商品列表没有这个商品，请先获取商品列表")
        else:
            details.update(
                {
                    "title": product.title,
                    "product_status": product.status,
                    "total_sales": product.total_sales,
                    "current_item_price": float(product.price or 0),
                }
            )
            if product.status != "onsale":
                reasons.append(f"商品不是出售中，当前状态={product.status or '-'}")
            if int(product.total_sales or 0) < int(sold_total_min):
                reasons.append(f"累计销量 {int(product.total_sales or 0)} 小于设置值 {int(sold_total_min)}")

        pxi = self.session.exec(
            select(ProductPxi).where(
                ProductPxi.platform == shop.platform,
                ProductPxi.shop_id == shop.shop_id,
                ProductPxi.product_id == product_id,
                ProductPxi.status == "active",
            )
        ).first()
        pxi_score = to_float(pxi.pxi_score) if pxi else None
        details["pxi_score"] = pxi_score
        if not pxi:
            reasons.append("没有有效 PXI 分，请先一键 PXI 分")
        elif (pxi_score or 0.0) <= float(pxi_min):
            reasons.append(f"PXI {pxi_score or 0} 不大于设置值 {float(pxi_min):g}")

        skus = self.session.exec(
            select(ProductSku).where(
                ProductSku.platform == shop.platform,
                ProductSku.shop_id == shop.shop_id,
                ProductSku.product_id == product_id,
                ProductSku.status == "active",
            )
        ).all()
        signup_skus = [sku for sku in skus if sku.shunshou_signup_price is not None]
        stocked_signup_skus = [sku for sku in signup_skus if int(sku.stock or 0) > 0]
        normal_missing = [sku for sku in signup_skus if sku.normal_sale_price is None]
        price_mismatch = [
            sku
            for sku in signup_skus
            if sku.normal_sale_price is not None and abs(float(sku.taobao_price or 0) - float(sku.normal_sale_price)) >= 0.01
        ]
        details.update(
            {
                "sku_count": len(skus),
                "signup_sku_count": len(signup_skus),
                "stocked_signup_sku_count": len(stocked_signup_skus),
                "missing_normal_price_count": len(normal_missing),
                "price_mismatch_count": len(price_mismatch),
            }
        )
        if not skus:
            reasons.append("没有有效 SKU，请先一键 SKU 价/库存")
        elif not signup_skus:
            reasons.append("没有任何 SKU 有顺手报名价；无报名价的 SKU 默认不报名")
        elif not stocked_signup_skus:
            reasons.append("有顺手报名价的 SKU 库存都为 0")
        if normal_missing:
            reasons.append(f"{len(normal_missing)} 个待报名 SKU 缺正常价，请先飞书匹配价格")
        if price_mismatch:
            reasons.append(f"{len(price_mismatch)} 个待报名 SKU 当前价不等于正常价，请先一键修改")

        activity = self.session.exec(
            select(ShunshouActivity).where(
                ShunshouActivity.platform == shop.platform,
                ShunshouActivity.shop_id == shop.shop_id,
                ShunshouActivity.activity_id == activity_id,
            )
        ).first()
        if not activity:
            reasons.append("活动 ID 不在本地活动列表，请先获取活动 ID")
        else:
            details.update(
                {
                    "activity_status_text": activity.activity_status_text,
                    "activity_sync_status": activity.sync_status,
                    "signed_item_count": activity.signed_item_count,
                    "max_item_limit": activity.max_item_limit,
                }
            )
            if activity.sync_status != "active":
                reasons.append(f"活动本地状态不是有效，当前={activity.sync_status or '-'}")
            if activity.activity_status_text != "进行中":
                reasons.append(f"活动不是进行中，当前={activity.activity_status_text or '-'}")

        activity_item = self.session.exec(
            select(ShunshouActivityItem).where(
                ShunshouActivityItem.platform == shop.platform,
                ShunshouActivityItem.shop_id == shop.shop_id,
                ShunshouActivityItem.activity_id == activity_id,
                ShunshouActivityItem.product_id == product_id,
            )
        ).first()
        if not activity_item:
            reasons.append("活动商品快照没有这条商品，请先获取活动商品")
        else:
            details.update(
                {
                    "warn_message": activity_item.warn_message,
                    "warn_status": activity_item.warn_status,
                    "activity_item_status": activity_item.activity_item_status,
                    "is_joined": activity_item.is_joined,
                    "activity_item_sync_status": activity_item.sync_status,
                }
            )
            if activity_item.sync_status != "active":
                reasons.append(f"活动商品快照不是有效，当前={activity_item.sync_status or '-'}")
            if activity_item.warn_status != "null":
                reasons.append(f"活动商品有提示：{activity_item.warn_message or activity_item.warn_status or '-'}")
            if activity_item.activity_item_status != "可报名":
                reasons.append(f"活动商品状态不是可报名，当前={activity_item.activity_item_status or '-'}")
            if int(activity_item.is_joined or 0) != 0:
                reasons.append("活动商品已报名，不需要重复报名")

        return {
            "activity_id": activity_id,
            "product_id": product_id,
            "ok": not reasons,
            "reason": "；".join(reasons) if reasons else "通过",
            **details,
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

    def _eligible_signup_items(self, *, shop: Shop, pxi_min: float, sold_total_min: int) -> list[dict[str, Any]]:
        statement = (
            select(Product, ProductPxi)
            .join(
                ProductPxi,
                (ProductPxi.platform == Product.platform)
                & (ProductPxi.shop_id == Product.shop_id)
                & (ProductPxi.product_id == Product.product_id),
            )
            .where(Product.platform == shop.platform)
            .where(Product.shop_id == shop.shop_id)
            .where(Product.status == "onsale")
            .where(Product.total_sales >= sold_total_min)
            .where(ProductPxi.status == "active")
        )
        rows = []
        for product, pxi in self.session.exec(statement).all():
            pxi_score = to_float(pxi.pxi_score) or 0.0
            if pxi_score <= pxi_min:
                continue
            priced_skus = self.session.exec(
                select(ProductSku).where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == product.product_id,
                    ProductSku.status == "active",
                    ProductSku.shunshou_signup_price != None,
                )
            ).all()
            price_values = [
                float(sku.shunshou_signup_price)
                for sku in priced_skus
                if sku.shunshou_signup_price is not None
            ]
            if not price_values:
                continue
            normal_price_values = [
                float(sku.normal_sale_price)
                for sku in priced_skus
                if sku.normal_sale_price is not None
            ]
            current_price_values = [
                float(sku.taobao_price)
                for sku in priced_skus
                if sku.taobao_price is not None
            ]
            price_mismatch_count = 0
            missing_normal_price_count = 0
            for sku in priced_skus:
                if sku.normal_sale_price is None:
                    missing_normal_price_count += 1
                    continue
                if abs(float(sku.taobao_price or 0) - float(sku.normal_sale_price)) >= 0.01:
                    price_mismatch_count += 1
            stocked_normal_prices = [
                float(sku.normal_sale_price)
                for sku in priced_skus
                if sku.normal_sale_price is not None and int(sku.stock or 0) > 0
            ]
            expected_item_price = max(stocked_normal_prices or normal_price_values) if normal_price_values else None
            item_price_mismatch = (
                expected_item_price is not None
                and abs(float(product.price or 0) - float(expected_item_price)) >= 0.01
            )
            if item_price_mismatch:
                price_mismatch_count += 1
            joined_count = self.session.exec(
                select(ShunshouActivityItem.id).where(
                    ShunshouActivityItem.platform == shop.platform,
                    ShunshouActivityItem.shop_id == shop.shop_id,
                    ShunshouActivityItem.product_id == product.product_id,
                    ShunshouActivityItem.sync_status == "active",
                    ShunshouActivityItem.is_joined == 1,
                )
            ).all()
            rows.append(
                {
                    "product_id": product.product_id,
                    "title": product.title,
                    "image_url": product.main_image_url or "",
                    "total_sales": product.total_sales,
                    "pxi_score": pxi_score,
                    "joined_count": len(joined_count),
                    "signup_price_min": min(price_values),
                    "signup_price_max": max(price_values),
                    "priced_sku_count": len(price_values),
                    "normal_price_min": min(normal_price_values) if normal_price_values else None,
                    "normal_price_max": max(normal_price_values) if normal_price_values else None,
                    "current_price_min": min(current_price_values) if current_price_values else None,
                    "current_price_max": max(current_price_values) if current_price_values else None,
                    "current_item_price": float(product.price or 0),
                    "expected_item_price": expected_item_price,
                    "item_price_mismatch": item_price_mismatch,
                    "price_mismatch_count": price_mismatch_count,
                    "missing_normal_price_count": missing_normal_price_count,
                    "price_status": "abnormal" if price_mismatch_count or missing_normal_price_count else "ok",
                }
            )
        rows.sort(key=lambda item: item["product_id"])
        return rows

    def _eligible_activity_map(
        self,
        *,
        shop: Shop,
        base_items: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
        product_ids = [item["product_id"] for item in base_items]
        if not product_ids:
            return {}, {}
        statement = (
            select(ShunshouActivityItem, ShunshouActivity)
            .join(
                ShunshouActivity,
                (ShunshouActivity.platform == ShunshouActivityItem.platform)
                & (ShunshouActivity.shop_id == ShunshouActivityItem.shop_id)
                & (ShunshouActivity.activity_id == ShunshouActivityItem.activity_id),
            )
            .where(ShunshouActivityItem.platform == shop.platform)
            .where(ShunshouActivityItem.shop_id == shop.shop_id)
            .where(ShunshouActivityItem.product_id.in_(product_ids))
            .where(ShunshouActivityItem.sync_status == "active")
            .where(ShunshouActivityItem.warn_status == "null")
            .where(ShunshouActivityItem.activity_item_status == "可报名")
            .where(ShunshouActivityItem.is_joined == 0)
            .where(ShunshouActivity.sync_status == "active")
            .where(ShunshouActivity.activity_status_text == "进行中")
        )
        activity_map: dict[str, dict[str, Any]] = {}
        item_activity_map: dict[str, list[str]] = {}
        for item, activity in self.session.exec(statement).all():
            activity_map[activity.activity_id] = {
                "activity_id": activity.activity_id,
                "activity_name": activity.activity_name or "",
                "signed_item_count": activity.signed_item_count,
                "max_item_limit": activity.max_item_limit,
            }
            item_activity_map.setdefault(item.product_id, [])
            if activity.activity_id not in item_activity_map[item.product_id]:
                item_activity_map[item.product_id].append(activity.activity_id)
        return activity_map, item_activity_map

    def _fetch_sku_detail_rows(
        self,
        *,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        user_agent: str | None,
        activity_id: str,
        product_ids: list[str],
        cross_shop: bool,
        batch_size: int,
        wait_min: float,
        wait_max: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        cross_shop_text = str(bool(cross_shop)).lower()
        with httpx.Client(timeout=max(self.settings.request_timeout_seconds, 30)) as client:
            for start in range(0, len(product_ids), batch_size):
                chunk = product_ids[start:start + batch_size]
                item_csv = ",".join(chunk)
                referer = (
                    "https://shell.mkt.taobao.com/taobaoTied/create"
                    f"?activityId={activity_id}&crossShop={cross_shop_text}"
                    f"&hitBuyOneRefactor=true&itemIdList={urllib.parse.quote(item_csv, safe='')}"
                    "&mode=update&step=2"
                )
                headers = self._headers(cookie_dict=cookie_dict, xsrf_token=xsrf_token, referer=referer, user_agent=user_agent)
                sleep_random(wait_min, wait_max)
                response = client.get(
                    DETAIL_URL,
                    params={
                        "itemIdList": item_csv,
                        "activityId": activity_id,
                        "crossShop": cross_shop_text,
                        "showAllItem": "true",
                        "hitBuyOneRefactor": "true",
                    },
                    headers=headers,
                )
                payload = parse_json_response(response, "顺手SKU明细")
                raw_rows: list[dict[str, Any]] = []
                collect_sku_rows(payload, raw_rows)
                for raw in raw_rows:
                    product_id = text(raw.get("itemId"))
                    sku_id = text(raw.get("skuId"))
                    key = (product_id, sku_id)
                    if not product_id or not sku_id or product_id not in chunk or key in seen:
                        continue
                    seen.add(key)
                    rows.append(raw)
                sleep_random(wait_min, wait_max)
        return rows

    def _existing_signed_product_ids(self, *, shop: Shop, activity_id: str) -> list[str]:
        rows = self.session.exec(
            select(ShunshouActivityItem.product_id).where(
                ShunshouActivityItem.platform == shop.platform,
                ShunshouActivityItem.shop_id == shop.shop_id,
                ShunshouActivityItem.activity_id == activity_id,
                ShunshouActivityItem.sync_status == "active",
                ShunshouActivityItem.is_joined == 1,
            )
        ).all()
        return list(dict.fromkeys(text(product_id) for product_id in rows if text(product_id)))

    def _build_submit_params(
        self,
        *,
        shop: Shop,
        detail_rows: list[dict[str, Any]],
        new_product_ids: set[str],
        preserve_product_ids: set[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        params: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        stats: dict[str, Any] = {
            "new_params_count": 0,
            "preserved_params_count": 0,
            "ignored_sku_count": 0,
            "ignored_product_ids": [],
        }
        new_products_with_params: set[str] = set()
        ignored_products: set[str] = set()
        for row in detail_rows:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            is_new = product_id in new_product_ids
            is_preserve = product_id in preserve_product_ids
            if not is_new and not is_preserve:
                continue

            if is_preserve and not is_new:
                new_row = dict(row)
                new_row["checked"] = True
                promotion_price = to_float(new_row.get("promotionPrice"))
                promotion_price_cent = to_int(new_row.get("promotionPriceCent"))
                if promotion_price is None and promotion_price_cent is not None:
                    promotion_price = promotion_price_cent / 100
                if promotion_price is not None:
                    new_row["promotionPrice"] = price_text(promotion_price)
                    new_row["promotionPriceCent"] = int(round(promotion_price * 100))
                params.append(new_row)
                stats["preserved_params_count"] += 1
                continue

            sku = self.session.exec(
                select(ProductSku).where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == product_id,
                    ProductSku.sku_id == sku_id,
                    ProductSku.status == "active",
                )
            ).first()
            if not sku or sku.shunshou_signup_price is None:
                stats["ignored_sku_count"] += 1
                ignored_products.add(product_id)
                continue
            if text(row.get("editable", 1)) in ("0", "false", "False"):
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "当前SKU不可编辑"})
                continue
            quantity = to_float(row.get("quantity"))
            if quantity is not None and quantity <= 0:
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "库存小于等于0"})
                continue
            ok, reason = price_available(row, float(sku.shunshou_signup_price))
            if not ok:
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": reason})
                continue
            new_row = dict(row)
            new_row["checked"] = True
            new_row["promotionPrice"] = price_text(float(sku.shunshou_signup_price))
            new_row["promotionPriceCent"] = int(round(float(sku.shunshou_signup_price) * 100))
            params.append(new_row)
            stats["new_params_count"] += 1
            new_products_with_params.add(product_id)
        stats["ignored_product_ids"] = sorted(
            product_id for product_id in ignored_products if product_id in new_product_ids and product_id not in new_products_with_params
        )
        return params, skipped, stats

    def _submit_signup(
        self,
        *,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        user_agent: str | None,
        activity_id: str,
        params: list[dict[str, Any]],
        cross_shop: bool,
    ) -> dict[str, Any]:
        product_ids: list[str] = []
        for row in params:
            product_id = text(row.get("itemId"))
            if product_id and product_id not in product_ids:
                product_ids.append(product_id)
        cross_shop_text = str(bool(cross_shop)).lower()
        referer = (
            "https://shell.mkt.taobao.com/taobaoTied/create"
            f"?activityId={activity_id}&crossShop={cross_shop_text}"
            "&hitBuyOneRefactor=true"
            f"&itemIdList={','.join(product_ids)}&mode=update&step=2"
        )
        headers = self._headers(cookie_dict=cookie_dict, xsrf_token=xsrf_token, referer=referer, user_agent=user_agent)
        with httpx.Client(timeout=max(self.settings.request_timeout_seconds, 30), headers=headers) as client:
            response = client.post(
                SUBMIT_URL,
                data={
                    "activityId": activity_id,
                    "mode": "update",
                    "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                },
            )
        if 300 <= response.status_code < 400:
            location = response.headers.get("location", "")
            raise HTTPException(status_code=401, detail=f"顺手报名提交被重定向：HTTP {response.status_code} {location or '未返回 location'}，请重新保存完整 Cookie")
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"顺手报名提交异常：{response.text[:500]}")
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower() and response.text.lstrip().startswith("<"):
            raise HTTPException(status_code=401, detail="顺手报名提交返回 HTML，通常是登录态失效或被网关重定向，请重新保存完整 Cookie")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"顺手报名提交返回不是 JSON：{response.text[:500]}") from exc
        return payload

    def _mark_signup_success(
        self,
        *,
        shop: Shop,
        activity_id: str,
        params: list[dict[str, Any]],
        submit_result: dict[str, Any],
        product_ids: list[str],
    ) -> None:
        now = datetime.now()
        product_ids = list(dict.fromkeys(text(product_id) for product_id in product_ids if text(product_id)))
        for product_id in product_ids:
            item = self.session.exec(
                select(ShunshouActivityItem).where(
                    ShunshouActivityItem.platform == shop.platform,
                    ShunshouActivityItem.shop_id == shop.shop_id,
                    ShunshouActivityItem.activity_id == activity_id,
                    ShunshouActivityItem.product_id == product_id,
                )
            ).first()
            if not item:
                continue
            item.warn_status = "not_null"
            item.activity_item_status = "已参加活动"
            item.is_joined = 1
            item.raw_json = {"submit_result": submit_result, "params_count": len(params)}
            item.updated_at = now
            self.session.add(item)
        activity = self.session.exec(
            select(ShunshouActivity).where(
                ShunshouActivity.platform == shop.platform,
                ShunshouActivity.shop_id == shop.shop_id,
                ShunshouActivity.activity_id == activity_id,
            )
        ).first()
        if activity:
            signed_product_ids = self.session.exec(
                select(ShunshouActivityItem.product_id).where(
                    ShunshouActivityItem.platform == shop.platform,
                    ShunshouActivityItem.shop_id == shop.shop_id,
                    ShunshouActivityItem.activity_id == activity_id,
                    ShunshouActivityItem.sync_status == "active",
                    ShunshouActivityItem.is_joined == 1,
                )
            ).all()
            activity.signed_item_count = len({text(product_id) for product_id in signed_product_ids if text(product_id)})
            activity.updated_at = now
            self.session.add(activity)
        self.session.commit()

    def _fetch_activity_rows(
        self,
        *,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        user_agent: str | None,
        activity_status: str,
    ) -> list[dict[str, Any]]:
        current = 1
        rows: list[dict[str, Any]] = []
        headers = self._headers(cookie_dict=cookie_dict, xsrf_token=xsrf_token, referer=LIST_REFERER, user_agent=user_agent)
        with httpx.Client(timeout=max(self.settings.request_timeout_seconds, 20), headers=headers) as client:
            while True:
                response = client.get(
                    LIST_URL,
                    params={"pageSize": PAGE_SIZE, "activityStatus": activity_status or "null", "pageNo": current},
                )
                payload = parse_json_response(response, "顺手活动列表")
                data = payload.get("data", {}) or {}
                page_items = data.get("data", []) or []
                rows.extend(normalize_activity(item) for item in page_items if isinstance(item, dict))
                total_page = to_int(data.get("totalPage")) or 0
                if total_page > 0 and current >= total_page:
                    break
                if total_page <= 0 and len(page_items) < PAGE_SIZE:
                    break
                current += 1
        return rows

    def _fetch_activity_item_rows(
        self,
        *,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        user_agent: str | None,
        activity_id: str,
        cross_shop: bool,
        auction_status: int,
    ) -> list[dict[str, Any]]:
        current = 1
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        cross_shop_text = str(bool(cross_shop)).lower()
        referer = (
            "https://shell.mkt.taobao.com/taobaoTied/create"
            f"?activityId={activity_id}&crossShop={cross_shop_text}"
            "&hitBuyOneRefactor=true&mode=update&step=1"
        )
        headers = self._headers(cookie_dict=cookie_dict, xsrf_token=xsrf_token, referer=referer, user_agent=user_agent)
        with httpx.Client(timeout=max(self.settings.request_timeout_seconds, 20), headers=headers) as client:
            while True:
                response = client.get(
                    ITEM_URL,
                    params={
                        "activityId": activity_id,
                        "crossShop": cross_shop_text,
                        "hitBuyOneRefactor": "true",
                        "pageSize": PAGE_SIZE,
                        "auctionStatus": int(auction_status),
                        "pageNo": current,
                    },
                )
                payload = parse_json_response(response, "顺手活动商品")
                raw_rows: list[dict[str, Any]] = []
                collect_product_rows(payload, raw_rows)
                page_count = 0
                for raw in raw_rows:
                    product_id = text(raw.get("itemId"))
                    sku_id = text(raw.get("skuId"))
                    if not product_id or sku_id or product_id in seen:
                        continue
                    seen.add(product_id)
                    rows.append(normalize_activity_item(raw, activity_id=activity_id, auction_status=auction_status))
                    page_count += 1
                if page_count < PAGE_SIZE:
                    break
                current += 1
        return rows

    def _headers(
        self,
        *,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        referer: str,
        user_agent: str | None,
    ) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9",
            "bx-v": "2.5.36",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": referer,
            "x-xsrf-token": xsrf_token,
            "cookie": cookie_dict.get("__cookie_header") or "; ".join(
                f"{key}={value}" for key, value in cookie_dict.items() if not key.startswith("__")
            ),
        }
        if user_agent:
            headers["user-agent"] = user_agent
        return headers

    def _upsert_activities(self, *, shop: Shop, rows: list[dict[str, Any]]) -> dict[str, int]:
        now = datetime.now()
        inserted = 0
        updated = 0
        active_ids = {row["activity_id"] for row in rows if row.get("activity_id")}
        for row in rows:
            activity = self.session.exec(
                select(ShunshouActivity).where(
                    ShunshouActivity.platform == shop.platform,
                    ShunshouActivity.shop_id == shop.shop_id,
                    ShunshouActivity.activity_id == row["activity_id"],
                )
            ).first()
            values = {
                "activity_name": row["activity_name"],
                "activity_status": row["activity_status"],
                "activity_status_text": row["activity_status_text"],
                "signed_item_count": row["signed_item_count"],
                "max_item_limit": row["max_item_limit"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "sync_status": "active",
                "raw_json": row["raw"],
                "last_platform_updated_at": now,
                "updated_at": now,
            }
            if activity:
                if activity.sync_status == "deleted":
                    continue
                for key, value in values.items():
                    setattr(activity, key, value)
                updated += 1
            else:
                activity = ShunshouActivity(
                    platform=shop.platform,
                    shop_id=shop.shop_id,
                    activity_id=row["activity_id"],
                    **values,
                )
                inserted += 1
            self.session.add(activity)
        inactive = 0
        existing = self.session.exec(
            select(ShunshouActivity).where(
                ShunshouActivity.platform == shop.platform,
                ShunshouActivity.shop_id == shop.shop_id,
                ShunshouActivity.sync_status == "active",
            )
        ).all()
        for activity in existing:
            if activity.activity_id in active_ids:
                continue
            activity.sync_status = "inactive"
            activity.updated_at = now
            self.session.add(activity)
            inactive += 1
        self.session.commit()
        return {"inserted": inserted, "updated": updated, "inactive": inactive}

    def _upsert_activity_items(
        self,
        *,
        shop: Shop,
        activity_id: str,
        auction_status: int,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        now = datetime.now()
        inserted = 0
        updated = 0
        active_ids = {row["product_id"] for row in rows if row.get("product_id")}
        for row in rows:
            item = self.session.exec(
                select(ShunshouActivityItem).where(
                    ShunshouActivityItem.platform == shop.platform,
                    ShunshouActivityItem.shop_id == shop.shop_id,
                    ShunshouActivityItem.activity_id == activity_id,
                    ShunshouActivityItem.product_id == row["product_id"],
                )
            ).first()
            values = {
                "item_title": row["item_title"],
                "warn_message": row["warn_message"],
                "warn_status": row["warn_status"],
                "activity_item_status": row["activity_item_status"],
                "is_joined": row["is_joined"],
                "auction_status": auction_status,
                "sync_status": "active",
                "raw_json": row["raw"],
                "last_platform_updated_at": now,
                "updated_at": now,
            }
            if item:
                for key, value in values.items():
                    setattr(item, key, value)
                updated += 1
            else:
                item = ShunshouActivityItem(
                    platform=shop.platform,
                    shop_id=shop.shop_id,
                    activity_id=activity_id,
                    product_id=row["product_id"],
                    **values,
                )
                inserted += 1
            self.session.add(item)
        inactive = 0
        existing = self.session.exec(
            select(ShunshouActivityItem).where(
                ShunshouActivityItem.platform == shop.platform,
                ShunshouActivityItem.shop_id == shop.shop_id,
                ShunshouActivityItem.activity_id == activity_id,
                ShunshouActivityItem.sync_status == "active",
            )
        ).all()
        for item in existing:
            if item.product_id in active_ids:
                continue
            item.sync_status = "inactive"
            item.updated_at = now
            self.session.add(item)
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


def parse_json_response(response: httpx.Response, label: str) -> dict[str, Any]:
    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "")
        raise HTTPException(status_code=401, detail=f"{label}接口被重定向：HTTP {response.status_code} {location or '未返回 location'}，请重新保存完整 Cookie")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"{label}接口返回异常：{response.text[:500]}")
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower() and response.text.lstrip().startswith("<"):
        raise HTTPException(status_code=401, detail=f"{label}接口返回 HTML，通常是登录态失效或被网关重定向，请重新保存完整 Cookie")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"{label}接口返回不是 JSON：{response.text[:500]}") from exc
    if not payload.get("success"):
        raise HTTPException(status_code=400, detail=f"{label}请求失败：{payload}")
    return payload


def normalize_activity(item: dict[str, Any]) -> dict[str, Any]:
    signed_count, max_limit = extract_capacity(item)
    status_value = to_int(item.get("activityStatus"))
    return {
        "activity_id": text(item.get("activityId")),
        "activity_name": text(pick(item, "name", "activityName", "activity_name", "title", "activityTitle")),
        "activity_status": status_value,
        "activity_status_text": status_text(status_value),
        "signed_item_count": signed_count,
        "max_item_limit": max_limit,
        "start_time": pick(item, "startTime", "start_time", "开始时间"),
        "end_time": pick(item, "endTime", "end_time", "结束时间"),
        "raw": item,
    }


def normalize_activity_item(item: dict[str, Any], *, activity_id: str, auction_status: int) -> dict[str, Any]:
    status_info = normalize_candidate_status(item.get("warnMessage"))
    return {
        "activity_id": activity_id,
        "product_id": text(item.get("itemId")),
        "item_title": text(item.get("itemTitle") or item.get("title") or item.get("itemName")),
        "warn_message": text(item.get("warnMessage")) or None,
        "warn_status": status_info["warn_status"],
        "activity_item_status": status_info["activity_item_status"],
        "is_joined": status_info["is_joined"],
        "auction_status": auction_status,
        "raw": item,
    }


def collect_product_rows(node: Any, rows: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        item_id = node.get("itemId")
        sku_id = node.get("skuId")
        if item_id not in (None, "") and sku_id in (None, ""):
            rows.append(node)
        for value in node.values():
            collect_product_rows(value, rows)
    elif isinstance(node, list):
        for value in node:
            collect_product_rows(value, rows)


def collect_sku_rows(node: Any, rows: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        item_id = node.get("itemId")
        sku_id = node.get("skuId")
        if item_id not in (None, "") and sku_id not in (None, ""):
            rows.append(node)
        for value in node.values():
            collect_sku_rows(value, rows)
    elif isinstance(node, list):
        for value in node:
            collect_sku_rows(value, rows)


def assign_items_to_activities(
    *,
    base_items: list[dict[str, Any]],
    activity_map: dict[str, dict[str, Any]],
    item_activity_map: dict[str, list[str]],
    target_activity_count: int,
    custom_capacity_limit: int,
    reserve_item_count: int,
    real_capacity_fallback: int,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    assigned_by_activity: dict[str, list[str]] = {}
    assigned_counter: dict[str, int] = {}
    skipped: list[dict[str, Any]] = []
    activity_ids = list(activity_map.keys())
    random.shuffle(activity_ids)

    for item in base_items:
        product_id = item["product_id"]
        available = item_activity_map.get(product_id, [])
        joined_count = int(item.get("joined_count") or 0)
        if joined_count >= target_activity_count:
            skipped.append({"product_id": product_id, "title": item.get("title", ""), "reason": "已报名活动数达到目标"})
            continue
        needed = max(0, target_activity_count - joined_count)
        if needed <= 0:
            continue
        choices = [activity_id for activity_id in activity_ids if activity_id in available]
        selected: list[str] = []
        for activity_id in choices:
            if len(selected) >= needed:
                break
            capacity = remaining_capacity(
                activity_map.get(activity_id) or {},
                assigned_counter.get(activity_id, 0),
                custom_capacity_limit,
                reserve_item_count,
                real_capacity_fallback,
            )
            if capacity <= 0:
                continue
            selected.append(activity_id)
            assigned_counter[activity_id] = assigned_counter.get(activity_id, 0) + 1
            assigned_by_activity.setdefault(activity_id, []).append(product_id)
        if len(selected) < needed:
            skipped.append(
                {
                    "product_id": product_id,
                    "title": item.get("title", ""),
                    "reason": f"可报名活动不足，目标{target_activity_count}，本轮补{len(selected)}",
                }
            )
    return assigned_by_activity, skipped


def remaining_capacity(
    activity: dict[str, Any],
    assigned_count: int,
    custom_capacity_limit: int,
    reserve_item_count: int,
    real_capacity_fallback: int,
) -> int:
    signed_count = to_int(activity.get("signed_item_count")) or 0
    real_limit = to_int(activity.get("max_item_limit")) or real_capacity_fallback
    effective_limit = min(real_limit, custom_capacity_limit) if custom_capacity_limit > 0 else real_limit
    return effective_limit - signed_count - reserve_item_count - int(assigned_count or 0)


def price_available(row: dict[str, Any], price: float) -> tuple[bool, str]:
    min_limit = 0.01
    rule = row.get("hgPriceLimitRule") or {}
    if isinstance(rule, dict):
        min_rule = to_float(rule.get("minPriceLimit"))
        if min_rule is not None:
            min_limit = min_rule
    max_candidates = [to_float(row.get("originalPrice")), to_float(row.get("minDiscountPrice"))]
    if isinstance(rule, dict):
        max_candidates.append(to_float(rule.get("hgPriceUpperLimit")))
    max_values = [value for value in max_candidates if value is not None]
    max_limit = min(max_values) if max_values else None
    if price < min_limit:
        return False, f"价格低于最小值 {min_limit}"
    if max_limit is not None and price > max_limit:
        return False, f"价格高于最大值 {max_limit}"
    return True, ""


def price_text(value: float) -> str:
    rendered = f"{float(value):.2f}"
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def normalize_assignments(value: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for activity_id, product_ids in (value or {}).items():
        aid = text(activity_id)
        if not aid:
            continue
        ids = [text(product_id) for product_id in (product_ids or []) if text(product_id)]
        if ids:
            normalized[aid] = list(dict.fromkeys(ids))
    return normalized


def normalize_candidate_status(warn_message: Any) -> dict[str, Any]:
    message = text(warn_message)
    if not message:
        return {"warn_status": "null", "activity_item_status": "可报名", "is_joined": 0}
    if "已经参加当前的活动" in message or "已参加当前活动" in message or "已经参加活动" in message:
        return {"warn_status": "not_null", "activity_item_status": "已参加活动", "is_joined": 1}
    return {"warn_status": "not_null", "activity_item_status": "其他原因", "is_joined": 0}


def extract_capacity(item: dict[str, Any]) -> tuple[int | None, int | None]:
    signed = to_int(pick(item, "signedItemCount", "joinedItemCount", "joinItemCount", "applyItemCount", "itemSignedCount"))
    limit = to_int(pick(item, "maxItemLimit", "itemLimit", "itemMaxLimit", "maxItemCount", "activityItemLimit"))
    for value in item.values():
        if signed is not None and limit is not None:
            break
        if isinstance(value, str) and "/" in value:
            pair_signed, pair_limit = parse_capacity_pair(value)
            signed = signed if signed is not None else pair_signed
            limit = limit if limit is not None else pair_limit
    return signed, limit


def parse_capacity_pair(value: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if not match:
        return None, None
    left = to_int(match.group(1))
    right = to_int(match.group(2))
    if left is not None and right is not None and left > right:
        left, right = right, left
    return left, right


def pick(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def status_text(status: int | None) -> str:
    return STATUS_MAP.get(status, text(status))


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d+", text(value).replace(",", ""))
    return int(match.group(0)) if match else None


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(text(value).replace(",", ""))
    except ValueError:
        return None


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


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def default_user_agent() -> str:
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


def is_auth_error(message: Any) -> bool:
    value = str(message).upper()
    return "LOGIN" in value or "COOKIE" in value or "TOKEN" in value or "登录" in value


def is_submit_success(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("success") is not True:
        return False
    code = str(payload.get("code") or "")
    return code in ("", "200")
