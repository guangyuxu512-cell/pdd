from __future__ import annotations

import json
import random
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
from app.services.shunshou_utils import (
    collect_product_rows,
    collect_sku_rows,
    default_user_agent,
    is_auth_error,
    is_submit_success,
    normalize_activity,
    normalize_activity_item,
    normalize_assignments,
    normalize_wait,
    price_available,
    price_text,
    sleep_random,
    text,
    to_float,
    to_int,
)


LIST_URL = "https://shell.mkt.taobao.com/taobaoTied/getList"
LIST_REFERER = "https://shell.mkt.taobao.com/taobaoTied/index"
ITEM_URL = "https://shell.mkt.taobao.com/taobaoTied/getItemList"
DETAIL_URL = "https://shell.mkt.taobao.com/taobaoTied/getDetailList"
SUBMIT_URL = "https://shell.mkt.taobao.com/taobaoTied/addOrUpdateDetails"
PAGE_SIZE = 20
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
        remove_assignments_by_activity: dict[str, list[str]] | None = None,
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
        remove_assignments_by_activity = normalize_assignments(remove_assignments_by_activity or {})
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
        activity_ids = list(dict.fromkeys([*assignments_by_activity.keys(), *remove_assignments_by_activity.keys()]))
        for activity_id in activity_ids:
            product_ids = assignments_by_activity.get(activity_id, [])
            remove_product_ids = set(remove_assignments_by_activity.get(activity_id, []))
            requested_product_ids = list(dict.fromkeys(text(product_id) for product_id in product_ids if text(product_id)))
            self._refresh_activity_item_snapshot(
                shop=shop,
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                cross_shop=cross_shop,
                auction_status=0,
            )
            existing_product_ids = self._existing_signed_product_ids(shop=shop, activity_id=activity_id)
            submit_product_ids = [
                product_id
                for product_id in list(dict.fromkeys(existing_product_ids + requested_product_ids))
                if product_id not in remove_product_ids
            ]
            new_product_ids = [product_id for product_id in requested_product_ids if product_id not in existing_product_ids]
            preserved_product_ids = [product_id for product_id in existing_product_ids if product_id in submit_product_ids]
            removed_product_ids = [product_id for product_id in existing_product_ids if product_id in remove_product_ids]
            sleep_random(wait_min, wait_max)
            detail_rows = []
            if submit_product_ids:
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
                preserve_product_ids=set(preserved_product_ids),
            )
            skipped_items.extend(skipped)
            result_row: dict[str, Any] = {
                "activity_id": activity_id,
                "item_count": len(requested_product_ids),
                "new_item_count": len(new_product_ids),
                "preserved_item_count": len(preserved_product_ids),
                "removed_item_count": len(removed_product_ids),
                "submit_item_count": len(submit_product_ids),
                "detail_count": len(detail_rows),
                "params_count": len(params),
                "new_params_count": param_stats["new_params_count"],
                "preserved_params_count": param_stats["preserved_params_count"],
                "ignored_sku_count": param_stats["ignored_sku_count"],
                "ignored_product_ids": param_stats["ignored_product_ids"],
                "param_product_ids": param_stats["submitted_product_ids"],
                "submitted_product_ids": [],
                "failed_product_ids": param_stats["failed_product_ids"],
                "submitted": False,
                "submit_success": False,
            }
            if dry_run:
                result_row["dry_run"] = True
                execution_results.append(result_row)
                continue
            if not params and submit_product_ids:
                result_row["error"] = "params_count=0"
                result_row["invalid_params"] = [
                    {"product_id": product_id, "sku_id": "", "reason": "本次需要提交商品，但没有任何可提交SKU参数"}
                    for product_id in requested_product_ids
                ][:20]
                execution_results.append(result_row)
                continue
            invalid_params = self._validate_submit_params(
                params,
                required_new_product_ids=set(new_product_ids),
                allowed_product_ids=set(submit_product_ids),
            )
            if invalid_params:
                result_row["error"] = "提交参数本地校验失败"
                result_row["invalid_params"] = invalid_params[:20]
                failed_product_ids = set(result_row.get("failed_product_ids") or [])
                failed_product_ids.update(text(row.get("product_id")) for row in invalid_params if text(row.get("product_id")))
                result_row["failed_product_ids"] = sorted(failed_product_ids)
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
                result_row["submit_success"] = True
                result_row["submitted_product_ids"] = param_stats["submitted_product_ids"]
                submitted_sku_count += param_stats["new_params_count"]
                self._mark_signup_success(
                    shop=shop,
                    activity_id=activity_id,
                    params=params,
                    submit_result=submit_result,
                    product_ids=param_stats["submitted_product_ids"],
                    removed_product_ids=removed_product_ids,
                )
            else:
                result_row["error"] = submit_error_message(submit_result)
                failed_product_ids = set(result_row.get("failed_product_ids") or [])
                failed_product_ids.update(param_stats["submitted_product_ids"])
                result_row["failed_product_ids"] = sorted(failed_product_ids)
            execution_results.append(result_row)

        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "candidate_count": len(base_items),
            "assignment_count": sum(len(values) for values in assignments_by_activity.values()),
            "submitted_activity_count": sum(1 for row in execution_results if row.get("submit_success")),
            "submitted_sku_count": submitted_sku_count,
            "skipped_count": len(skipped_items),
            "dry_run": bool(dry_run),
            "assignments_by_activity": assignments_by_activity,
            "remove_assignments_by_activity": remove_assignments_by_activity,
            "execution_results": execution_results,
            "skipped_items": skipped_items,
        }

    def preview_signup_candidates(
        self,
        *,
        shop: Shop,
        pxi_min: float = 70,
        sold_total_min: int = 3,
        product_id: str | None = None,
        joined_count_min: int | None = None,
        joined_count_max: int | None = None,
        target_activity_count: int = 2,
        custom_capacity_limit: int = 160,
        reserve_item_count: int = 3,
        real_capacity_fallback: int = 171,
    ) -> dict[str, Any]:
        base_items = self._eligible_signup_items(
            shop=shop,
            pxi_min=float(pxi_min),
            sold_total_min=int(sold_total_min),
            product_id=product_id,
            joined_count_min=joined_count_min,
            joined_count_max=joined_count_max,
        )
        activity_map, item_activity_map = self._selectable_activity_map(shop=shop, base_items=base_items)
        skipped_items: list[dict[str, Any]] = []
        assignments_by_activity: dict[str, list[str]] = {}
        product_map = {item["product_id"]: item for item in base_items}
        rows_by_product: dict[str, dict[str, Any]] = {}
        for product_id, activity_keys in item_activity_map.items():
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
            for activity_key in activity_keys:
                activity = activity_map.get(activity_key) or {}
                activity_id = activity.get("activity_id", "")
                if activity.get("is_joined"):
                    assignments_by_activity.setdefault(activity_id, []).append(product_id)
                rows_by_product[product_id]["activities"].append(
                    {
                        "activity_id": activity_id,
                        "activity_name": activity.get("activity_name", ""),
                        "selected": bool(activity.get("is_joined")),
                        "is_joined": int(activity.get("is_joined") or 0),
                        "activity_item_status": activity.get("activity_item_status", ""),
                        "warn_message": activity.get("warn_message", ""),
                    }
                )
        for item in base_items:
            product_id = item["product_id"]
            if product_id in rows_by_product:
                continue
            skipped_items.append({"product_id": product_id, "title": item.get("title", ""), "reason": "没有可报名或已报名活动"})
        rows = list(rows_by_product.values())
        rows.sort(key=lambda row: row["product_id"])
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
        remove_assignments_by_activity: dict[str, list[str]] | None = None,
        pxi_min: float = 70,
        sold_total_min: int = 3,
    ) -> dict[str, Any]:
        assignments = normalize_assignments(assignments_by_activity or {})
        removals = normalize_assignments(remove_assignments_by_activity or {})
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
        for activity_id, product_ids in removals.items():
            for product_id in product_ids:
                row = self._check_signup_removal(shop=shop, activity_id=activity_id, product_id=product_id)
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

    def detect_signup_price_changes(
        self,
        *,
        shop: Shop,
        product_ids: list[str],
        cross_shop: bool = False,
        batch_size: int = 25,
        min_wait_seconds: float = 0.6,
        max_wait_seconds: float = 1.8,
    ) -> dict[str, Any]:
        cookie_dict, xsrf_token, user_agent = self._request_context(shop=shop, action="检测报名价变动")
        product_ids = normalize_product_ids(product_ids)
        batch_size = max(1, int(batch_size or 25))
        wait_min, wait_max = normalize_wait(min_wait_seconds, max_wait_seconds)
        activity_products = self._joined_activity_products(shop=shop, product_ids=product_ids)
        rows: list[dict[str, Any]] = []
        for activity_id, ids in activity_products.items():
            detail_rows = self._fetch_sku_detail_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                product_ids=ids,
                cross_shop=cross_shop,
                batch_size=batch_size,
                wait_min=wait_min,
                wait_max=wait_max,
            )
            rows.extend(self._build_price_change_rows(shop=shop, activity_id=activity_id, detail_rows=detail_rows))
        changed_rows = [row for row in rows if row.get("changed")]
        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "requested_product_count": len(product_ids),
            "joined_product_count": len({product_id for ids in activity_products.values() for product_id in ids}),
            "activity_count": len(activity_products),
            "sku_count": len(rows),
            "changed_count": len(changed_rows),
            "can_update_count": sum(1 for row in changed_rows if row.get("can_update")),
            "rows": rows,
        }

    def update_joined_signup_prices(
        self,
        *,
        shop: Shop,
        product_ids: list[str],
        assignments_by_activity: dict[str, list[str]] | None = None,
        cross_shop: bool = False,
        batch_size: int = 25,
        min_wait_seconds: float = 0.6,
        max_wait_seconds: float = 1.8,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        cookie_dict, xsrf_token, user_agent = self._request_context(shop=shop, action="更新已报名价格")
        product_ids = normalize_product_ids(product_ids)
        assignments = normalize_assignments(assignments_by_activity or {})
        if assignments:
            product_ids = normalize_product_ids([product_id for ids in assignments.values() for product_id in ids])
        if not product_ids:
            raise HTTPException(status_code=400, detail="请先勾选要更新已报名价格的商品")
        batch_size = max(1, int(batch_size or 25))
        wait_min, wait_max = normalize_wait(min_wait_seconds, max_wait_seconds)
        activity_products = assignments or self._joined_activity_products(shop=shop, product_ids=product_ids)
        execution_results: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []
        updated_sku_count = 0
        for activity_id, target_product_ids in activity_products.items():
            self._refresh_activity_item_snapshot(
                shop=shop,
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                cross_shop=cross_shop,
                auction_status=0,
            )
            existing_product_ids = self._existing_signed_product_ids(shop=shop, activity_id=activity_id)
            if not existing_product_ids:
                execution_results.append({"activity_id": activity_id, "submitted": False, "error": "没有已报名商品"})
                continue
            detail_rows = self._fetch_sku_detail_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                product_ids=existing_product_ids,
                cross_shop=cross_shop,
                batch_size=batch_size,
                wait_min=wait_min,
                wait_max=wait_max,
            )
            params, skipped, stats = self._build_update_price_params(
                shop=shop,
                detail_rows=detail_rows,
                update_product_ids=set(target_product_ids),
            )
            skipped_items.extend(skipped)
            result_row: dict[str, Any] = {
                "activity_id": activity_id,
                "target_item_count": len(target_product_ids),
                "preserved_item_count": max(0, len(existing_product_ids) - len(target_product_ids)),
                "submit_item_count": len(existing_product_ids),
                "detail_count": len(detail_rows),
                "params_count": len(params),
                "updated_params_count": stats["updated_params_count"],
                "preserved_params_count": stats["preserved_params_count"],
                "unchanged_params_count": stats["unchanged_params_count"],
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
            invalid_params = self._validate_submit_params(params, allowed_product_ids=set(existing_product_ids))
            if invalid_params:
                result_row["error"] = "提交参数本地校验失败"
                result_row["invalid_params"] = invalid_params[:20]
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
                updated_sku_count += stats["updated_params_count"]
                self._mark_signup_price_update(
                    shop=shop,
                    activity_id=activity_id,
                    product_ids=target_product_ids,
                    submit_result=submit_result,
                    updated_params_count=stats["updated_params_count"],
                )
            else:
                result_row["error"] = submit_error_message(submit_result)
            execution_results.append(result_row)
        return {
            "platform": shop.platform,
            "shop_id": shop.shop_id,
            "requested_product_count": len(product_ids),
            "activity_count": len(activity_products),
            "submitted_activity_count": sum(1 for row in execution_results if row.get("submitted") and not row.get("error")),
            "updated_sku_count": updated_sku_count,
            "skipped_count": len(skipped_items),
            "dry_run": bool(dry_run),
            "execution_results": execution_results,
            "skipped_items": skipped_items,
        }

    def verify_signup_assignments(
        self,
        *,
        shop: Shop,
        assignments_by_activity: dict[str, list[str]],
        remove_assignments_by_activity: dict[str, list[str]] | None = None,
        cross_shop: bool = False,
        batch_size: int = 25,
        min_wait_seconds: float = 0.3,
        max_wait_seconds: float = 0.6,
    ) -> dict[str, Any]:
        cookie_dict, xsrf_token, user_agent = self._request_context(shop=shop, action="复查报名结果")
        assignments = normalize_assignments(assignments_by_activity or {})
        removals = normalize_assignments(remove_assignments_by_activity or {})
        batch_size = max(1, int(batch_size or 25))
        wait_min, wait_max = normalize_wait(min_wait_seconds, max_wait_seconds)
        rows: list[dict[str, Any]] = []
        failed_rows: list[dict[str, Any]] = []
        activity_ids = list(dict.fromkeys([*assignments.keys(), *removals.keys()]))
        for activity_id in activity_ids:
            expected_joined = assignments.get(activity_id, [])
            expected_removed = removals.get(activity_id, [])
            verify_product_ids = list(dict.fromkeys([*expected_joined, *expected_removed]))
            detail_rows = self._fetch_sku_detail_rows(
                cookie_dict=cookie_dict,
                xsrf_token=xsrf_token,
                user_agent=user_agent,
                activity_id=activity_id,
                product_ids=verify_product_ids,
                cross_shop=cross_shop,
                batch_size=batch_size,
                wait_min=wait_min,
                wait_max=wait_max,
            ) if verify_product_ids else []
            detail_product_ids = {text(row.get("itemId")) for row in detail_rows if text(row.get("itemId"))}
            for product_id in expected_joined:
                ok = product_id in detail_product_ids
                row = {
                    "activity_id": activity_id,
                    "product_id": product_id,
                    "action": "add",
                    "ok": ok,
                    "reason": "SKU明细仍可读取，确认在活动编辑清单" if ok else "SKU明细接口未返回该商品，未确认已报名",
                    "sku_count": sum(1 for detail in detail_rows if text(detail.get("itemId")) == product_id),
                }
                rows.append(row)
                if not ok:
                    failed_rows.append(row)
            for product_id in expected_removed:
                ok = product_id not in detail_product_ids
                row = {
                    "activity_id": activity_id,
                    "product_id": product_id,
                    "action": "remove",
                    "ok": ok,
                    "reason": "SKU明细不再返回该商品，确认已取消" if ok else "SKU明细仍返回该商品，未确认取消",
                    "sku_count": sum(1 for detail in detail_rows if text(detail.get("itemId")) == product_id),
                }
                rows.append(row)
                if not ok:
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

    def _check_signup_removal(self, *, shop: Shop, activity_id: str, product_id: str) -> dict[str, Any]:
        reasons: list[str] = []
        item = self.session.exec(
            select(ShunshouActivityItem).where(
                ShunshouActivityItem.platform == shop.platform,
                ShunshouActivityItem.shop_id == shop.shop_id,
                ShunshouActivityItem.activity_id == activity_id,
                ShunshouActivityItem.product_id == product_id,
            )
        ).first()
        if not item:
            reasons.append("活动商品快照没有这条商品，无法取消报名")
        else:
            if item.sync_status != "active":
                reasons.append(f"活动商品快照不是有效，当前={item.sync_status or '-'}")
            if int(item.is_joined or 0) != 1:
                reasons.append("当前本地状态不是已报名，无需取消")
        return {
            "activity_id": activity_id,
            "product_id": product_id,
            "action": "remove",
            "ok": not reasons,
            "reason": "；".join(reasons) if reasons else "通过",
            "activity_item_status": item.activity_item_status if item else None,
            "is_joined": item.is_joined if item else None,
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
            details["activity_item_status"] = "未同步"
            details["activity_item_sync_status"] = "missing"
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
            if int(activity_item.is_joined or 0) == 1:
                details["already_joined"] = True
            elif activity_item.warn_status != "null":
                reasons.append(f"活动商品有提示：{activity_item.warn_message or activity_item.warn_status or '-'}")
            elif activity_item.activity_item_status != "可报名":
                reasons.append(f"活动商品状态不是可报名，当前={activity_item.activity_item_status or '-'}")

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

    def _request_context(self, *, shop: Shop, action: str) -> tuple[dict[str, str], str, str | None]:
        snapshot = self._latest_main_cookie(shop)
        cookie_dict = cookies_to_dict(snapshot.cookies_json)
        cookie_header = snapshot.cookie_header_text or build_cookie_header(snapshot.cookies_json)
        cookie_dict["__cookie_header"] = cookie_header
        xsrf_token = extract_cookie_value_from_header(cookie_header, "XSRF-TOKEN") or cookie_dict.get("XSRF-TOKEN")
        if not xsrf_token:
            raise HTTPException(status_code=400, detail=f"cookie 中未找到 XSRF-TOKEN，请重新登录店铺后再{action}")
        return cookie_dict, xsrf_token, self._user_agent(shop, snapshot)

    def _eligible_signup_items(
        self,
        *,
        shop: Shop,
        pxi_min: float,
        sold_total_min: int,
        product_id: str | None = None,
        joined_count_min: int | None = None,
        joined_count_max: int | None = None,
    ) -> list[dict[str, Any]]:
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
        product_id_text = text(product_id)
        if product_id_text:
            statement = statement.where(Product.product_id == product_id_text)
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
            joined_total = len(joined_count)
            if joined_count_min is not None and joined_total < int(joined_count_min):
                continue
            if joined_count_max is not None and joined_total > int(joined_count_max):
                continue
            rows.append(
                {
                    "product_id": product.product_id,
                    "title": product.title,
                    "image_url": product.main_image_url or "",
                    "total_sales": product.total_sales,
                    "pxi_score": pxi_score,
                    "joined_count": joined_total,
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
            activity_key = f"{item.product_id}::{activity.activity_id}"
            activity_map[activity_key] = {
                "activity_id": activity.activity_id,
                "activity_name": activity.activity_name or "",
                "signed_item_count": activity.signed_item_count,
                "max_item_limit": activity.max_item_limit,
            }
            item_activity_map.setdefault(item.product_id, [])
            if activity_key not in item_activity_map[item.product_id]:
                item_activity_map[item.product_id].append(activity_key)
        return activity_map, item_activity_map

    def _selectable_activity_map(
        self,
        *,
        shop: Shop,
        base_items: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
        product_ids = [item["product_id"] for item in base_items]
        if not product_ids:
            return {}, {}
        activities = self.session.exec(
            select(ShunshouActivity)
            .where(ShunshouActivity.platform == shop.platform)
            .where(ShunshouActivity.shop_id == shop.shop_id)
            .where(ShunshouActivity.sync_status == "active")
            .where(ShunshouActivity.activity_status_text == "进行中")
            .order_by(ShunshouActivity.updated_at.desc())
        ).all()
        if not activities:
            return {}, {}
        item_rows = self.session.exec(
            select(ShunshouActivityItem)
            .where(ShunshouActivityItem.platform == shop.platform)
            .where(ShunshouActivityItem.shop_id == shop.shop_id)
            .where(ShunshouActivityItem.product_id.in_(product_ids))
            .where(ShunshouActivityItem.sync_status == "active")
        ).all()
        item_status = {
            (item.product_id, item.activity_id): item
            for item in item_rows
        }
        activity_map: dict[str, dict[str, Any]] = {}
        item_activity_map: dict[str, list[str]] = {}
        for product_id in product_ids:
            item_activity_map.setdefault(product_id, [])
            for activity in activities:
                item = item_status.get((product_id, activity.activity_id))
                is_joined = int(item.is_joined or 0) if item else 0
                activity_key = f"{product_id}::{activity.activity_id}"
                activity_map[activity_key] = {
                    "activity_id": activity.activity_id,
                    "activity_name": activity.activity_name or "",
                    "signed_item_count": activity.signed_item_count,
                    "max_item_limit": activity.max_item_limit,
                    "is_joined": is_joined,
                    "activity_item_status": item.activity_item_status if item else "未同步",
                    "warn_message": item.warn_message if item else "",
                    "has_activity_item_snapshot": bool(item),
                }
                item_activity_map[product_id].append(activity_key)
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

    def _joined_activity_products(self, *, shop: Shop, product_ids: list[str]) -> dict[str, list[str]]:
        statement = select(ShunshouActivityItem).where(
            ShunshouActivityItem.platform == shop.platform,
            ShunshouActivityItem.shop_id == shop.shop_id,
            ShunshouActivityItem.sync_status == "active",
            ShunshouActivityItem.is_joined == 1,
        )
        if product_ids:
            statement = statement.where(ShunshouActivityItem.product_id.in_(product_ids))
        rows = self.session.exec(statement).all()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.activity_id, [])
            if row.product_id not in grouped[row.activity_id]:
                grouped[row.activity_id].append(row.product_id)
        return grouped

    def _build_price_change_rows(
        self,
        *,
        shop: Shop,
        activity_id: str,
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        activity = self.session.exec(
            select(ShunshouActivity).where(
                ShunshouActivity.platform == shop.platform,
                ShunshouActivity.shop_id == shop.shop_id,
                ShunshouActivity.activity_id == activity_id,
            )
        ).first()
        product_ids = list(dict.fromkeys(text(row.get("itemId")) for row in detail_rows if text(row.get("itemId"))))
        products_by_id: dict[str, Product] = {}
        if product_ids:
            products = self.session.exec(
                select(Product).where(
                    Product.platform == shop.platform,
                    Product.shop_id == shop.shop_id,
                    Product.product_id.in_(product_ids),
                )
            ).all()
            products_by_id = {product.product_id: product for product in products}
        rows: list[dict[str, Any]] = []
        for row in detail_rows:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            product = products_by_id.get(product_id)
            sku = self.session.exec(
                select(ProductSku).where(
                    ProductSku.platform == shop.platform,
                    ProductSku.shop_id == shop.shop_id,
                    ProductSku.product_id == product_id,
                    ProductSku.sku_id == sku_id,
                    ProductSku.status == "active",
                )
            ).first()
            current_price = activity_signup_price(row)
            feishu_price = float(sku.shunshou_signup_price) if sku and sku.shunshou_signup_price is not None else None
            changed = current_price is not None and feishu_price is not None and abs(current_price - feishu_price) >= 0.01
            reason = ""
            if not sku:
                reason = "本地没有有效SKU"
            elif feishu_price is None:
                reason = "SKU没有顺手报名价"
            elif current_price is None:
                reason = "活动接口未返回当前报名价"
            elif not changed:
                reason = "价格未变化"
            rows.append(
                {
                    "activity_id": activity_id,
                    "activity_name": activity.activity_name if activity else "",
                    "product_id": product_id,
                    "title": product.title if product else text(row.get("itemTitle") or row.get("title")),
                    "image_url": (product.main_image_url if product else None) or (sku.image_url if sku else ""),
                    "sku_id": sku_id,
                    "sku_code": sku.sku_code if sku else "",
                    "sku_name": sku.sku_name if sku else text(row.get("skuName") or row.get("skuTitle")),
                    "current_signup_price": current_price,
                    "feishu_signup_price": feishu_price,
                    "changed": changed,
                    "can_update": changed and bool(sku and feishu_price is not None),
                    "reason": reason,
                }
            )
        return rows

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
            "submitted_product_ids": [],
            "failed_product_ids": [],
        }
        new_products_with_params: set[str] = set()
        ignored_products: set[str] = set()
        skipped_products: set[str] = set()
        detail_products: set[str] = set()
        for row in detail_rows:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            is_new = product_id in new_product_ids
            is_preserve = product_id in preserve_product_ids
            if not is_new and not is_preserve:
                continue
            if product_id:
                detail_products.add(product_id)

            if is_preserve and not is_new:
                new_row = dict(row)
                new_row["checked"] = True
                editable = text(new_row.get("editable", 1))
                promotion_price = to_float(new_row.get("promotionPrice"))
                promotion_price_cent = to_int(new_row.get("promotionPriceCent"))
                if promotion_price is None and promotion_price_cent is not None:
                    promotion_price = promotion_price_cent / 100
                if promotion_price is None and editable not in ("0", "false", "False"):
                    sku = self.session.exec(
                        select(ProductSku).where(
                            ProductSku.platform == shop.platform,
                            ProductSku.shop_id == shop.shop_id,
                            ProductSku.product_id == product_id,
                            ProductSku.sku_id == sku_id,
                            ProductSku.status == "active",
                        )
                    ).first()
                    if sku and sku.shunshou_signup_price is not None:
                        ok, reason = price_available(row, float(sku.shunshou_signup_price))
                        if ok:
                            promotion_price = float(sku.shunshou_signup_price)
                        else:
                            skipped.append({
                                "product_id": product_id,
                                "sku_id": sku_id,
                                "reason": f"保留已报名SKU补齐报名价失败：{reason}",
                                "editable": editable,
                                "sku_code": sku.sku_code or "",
                                "sku_name": sku.sku_name or text(row.get("skuName") or row.get("skuTitle")),
                                "signup_price": float(sku.shunshou_signup_price),
                            })
                            skipped_products.add(product_id)
                            continue
                if promotion_price is not None:
                    new_row["promotionPrice"] = price_text(promotion_price)
                    new_row["promotionPriceCent"] = int(round(promotion_price * 100))
                else:
                    reason = "平台置灰的已报名SKU未返回当前活动报名价，无法随本次请求保留提交" if editable in ("0", "false", "False") else "保留已报名SKU缺少当前活动报名价，无法构造合法提交参数"
                    skipped.append({
                        "product_id": product_id,
                        "sku_id": sku_id,
                        "reason": reason,
                        "editable": editable,
                        "raw_keys": sorted(str(key) for key in row.keys())[:40],
                    })
                    skipped_products.add(product_id)
                    continue
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
            sku_context = {
                "sku_code": sku.sku_code or "",
                "sku_name": sku.sku_name or text(row.get("skuName") or row.get("skuTitle")),
                "signup_price": float(sku.shunshou_signup_price),
            }
            if text(row.get("editable", 1)) in ("0", "false", "False"):
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "当前SKU不可编辑", **sku_context})
                skipped_products.add(product_id)
                continue
            quantity = to_float(row.get("quantity"))
            if quantity is not None and quantity <= 0:
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "库存小于等于0", **sku_context})
                skipped_products.add(product_id)
                continue
            ok, reason = price_available(row, float(sku.shunshou_signup_price))
            if not ok:
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": reason, **sku_context})
                skipped_products.add(product_id)
                continue
            new_row = dict(row)
            new_row["checked"] = True
            new_row["promotionPrice"] = price_text(float(sku.shunshou_signup_price))
            new_row["promotionPriceCent"] = int(round(float(sku.shunshou_signup_price) * 100))
            params.append(new_row)
            stats["new_params_count"] += 1
            new_products_with_params.add(product_id)
        missing_detail_products = set(new_product_ids) - detail_products
        for product_id in sorted(missing_detail_products):
            skipped.append({"product_id": product_id, "sku_id": "", "reason": "淘宝SKU明细未返回该商品，无法提交报名"})
            skipped_products.add(product_id)
        stats["ignored_product_ids"] = sorted(
            product_id for product_id in ignored_products if product_id in new_product_ids and product_id not in new_products_with_params
        )
        stats["submitted_product_ids"] = sorted(product_id for product_id in new_products_with_params if product_id in new_product_ids)
        stats["failed_product_ids"] = sorted(
            product_id
            for product_id in set(new_product_ids)
            if product_id not in new_products_with_params
        )
        return params, skipped, stats

    def _validate_submit_params_legacy(self, params: list[dict[str, Any]]) -> list[dict[str, str]]:
        invalid: list[dict[str, str]] = []
        for row in params:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            price = to_float(row.get("promotionPrice"))
            price_cent = to_int(row.get("promotionPriceCent"))
            if not product_id or not sku_id:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "缺 itemId 或 skuId"})
            elif price is None or price_cent is None:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "缺 promotionPrice 或 promotionPriceCent"})
        return invalid

    def _build_update_price_params(
        self,
        *,
        shop: Shop,
        detail_rows: list[dict[str, Any]],
        update_product_ids: set[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        params: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        stats = {"updated_params_count": 0, "preserved_params_count": 0, "unchanged_params_count": 0}
        for row in detail_rows:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            new_row = dict(row)
            new_row["checked"] = True
            if product_id not in update_product_ids:
                normalize_existing_promotion_price(new_row)
                if activity_signup_price(new_row) is None and text(new_row.get("editable", 1)) not in ("0", "false", "False"):
                    sku = self.session.exec(
                        select(ProductSku).where(
                            ProductSku.platform == shop.platform,
                            ProductSku.shop_id == shop.shop_id,
                            ProductSku.product_id == product_id,
                            ProductSku.sku_id == sku_id,
                            ProductSku.status == "active",
                        )
                    ).first()
                    if sku and sku.shunshou_signup_price is not None:
                        ok, reason = price_available(row, float(sku.shunshou_signup_price))
                        if ok:
                            new_row["promotionPrice"] = price_text(float(sku.shunshou_signup_price))
                            new_row["promotionPriceCent"] = int(round(float(sku.shunshou_signup_price) * 100))
                        else:
                            skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": f"保留SKU补齐报名价失败：{reason}"})
                if activity_signup_price(new_row) is None:
                    skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "保留SKU缺少当前活动报名价，无法构造合法提交参数"})
                    continue
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
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "本地SKU没有顺手报名价"})
                normalize_existing_promotion_price(new_row)
                if activity_signup_price(new_row) is None:
                    skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "目标SKU缺少本地顺手报名价，且淘宝未返回当前活动报名价"})
                    continue
                params.append(new_row)
                stats["preserved_params_count"] += 1
                continue
            ok, reason = price_available(row, float(sku.shunshou_signup_price))
            if not ok:
                skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": reason})
                normalize_existing_promotion_price(new_row)
                if activity_signup_price(new_row) is None:
                    skipped.append({"product_id": product_id, "sku_id": sku_id, "reason": "目标SKU价格不符合活动限制，且淘宝未返回当前活动报名价"})
                    continue
                params.append(new_row)
                stats["preserved_params_count"] += 1
                continue
            current_price = activity_signup_price(row)
            if current_price is not None and abs(current_price - float(sku.shunshou_signup_price)) < 0.01:
                stats["unchanged_params_count"] += 1
            else:
                stats["updated_params_count"] += 1
            new_row["promotionPrice"] = price_text(float(sku.shunshou_signup_price))
            new_row["promotionPriceCent"] = int(round(float(sku.shunshou_signup_price) * 100))
            params.append(new_row)
        return params, skipped, stats

    def _validate_submit_params(
        self,
        params: list[dict[str, Any]],
        *,
        required_new_product_ids: set[str] | None = None,
        allowed_product_ids: set[str] | None = None,
    ) -> list[dict[str, str]]:
        invalid: list[dict[str, str]] = []
        required_new_product_ids = {text(product_id) for product_id in (required_new_product_ids or set()) if text(product_id)}
        allowed_product_ids = {text(product_id) for product_id in (allowed_product_ids or set()) if text(product_id)}
        seen_skus: set[tuple[str, str]] = set()
        product_ids_with_params: set[str] = set()
        for row in params:
            product_id = text(row.get("itemId"))
            sku_id = text(row.get("skuId"))
            price = to_float(row.get("promotionPrice"))
            price_cent = to_int(row.get("promotionPriceCent"))
            if not product_id or not sku_id:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "缺 itemId 或 skuId"})
                continue
            product_ids_with_params.add(product_id)
            key = (product_id, sku_id)
            if key in seen_skus:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "重复SKU参数"})
            seen_skus.add(key)
            if allowed_product_ids and product_id not in allowed_product_ids:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "提交参数包含非本次活动目标商品"})
            if price is None or price_cent is None:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "缺 promotionPrice 或 promotionPriceCent"})
                continue
            if price <= 0 or price_cent <= 0:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "报名价必须大于0"})
            elif abs(int(round(price * 100)) - price_cent) > 1:
                invalid.append({"product_id": product_id, "sku_id": sku_id, "reason": "promotionPrice 与 promotionPriceCent 不一致"})
        for product_id in sorted(required_new_product_ids - product_ids_with_params):
            invalid.append({"product_id": product_id, "sku_id": "", "reason": "新增商品没有任何可提交SKU"})
        return invalid

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
        removed_product_ids: list[str] | None = None,
    ) -> None:
        now = datetime.now()
        product_ids = list(dict.fromkeys(text(product_id) for product_id in product_ids if text(product_id)))
        removed_product_ids = list(dict.fromkeys(text(product_id) for product_id in (removed_product_ids or []) if text(product_id)))
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
        for product_id in removed_product_ids:
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
            item.warn_status = "null"
            item.activity_item_status = "可报名"
            item.is_joined = 0
            item.raw_json = {"submit_result": submit_result, "removed": True}
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

    def _mark_signup_price_update(
        self,
        *,
        shop: Shop,
        activity_id: str,
        product_ids: list[str],
        submit_result: dict[str, Any],
        updated_params_count: int,
    ) -> None:
        now = datetime.now()
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
            raw_json = item.raw_json if isinstance(item.raw_json, dict) else {}
            raw_json["price_update"] = {
                "submit_result": submit_result,
                "updated_params_count": updated_params_count,
                "updated_at": now.isoformat(),
            }
            item.raw_json = raw_json
            item.updated_at = now
            self.session.add(item)
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

    def _refresh_activity_item_snapshot(
        self,
        *,
        shop: Shop,
        cookie_dict: dict[str, str],
        xsrf_token: str,
        user_agent: str | None,
        activity_id: str,
        cross_shop: bool,
        auction_status: int,
    ) -> None:
        rows = self._fetch_activity_item_rows(
            cookie_dict=cookie_dict,
            xsrf_token=xsrf_token,
            user_agent=user_agent,
            activity_id=activity_id,
            cross_shop=cross_shop,
            auction_status=auction_status,
        )
        self._upsert_activity_items(
            shop=shop,
            activity_id=activity_id,
            auction_status=auction_status,
            rows=rows,
        )

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


def submit_error_message(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "淘宝提交返回格式异常"
    code = payload.get("code") or payload.get("errorCode") or ""
    message = payload.get("message") or payload.get("errorMsg") or payload.get("msg") or ""
    data = payload.get("data")
    parts = []
    if code:
        parts.append(f"code={code}")
    if message:
        parts.append(str(message))
    if data not in (None, "", [], {}):
        parts.append(f"data={str(data)[:300]}")
    return "；".join(parts) or f"淘宝提交未返回成功：{str(payload)[:500]}"


def normalize_product_ids(product_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(text(product_id) for product_id in (product_ids or []) if text(product_id)))


def activity_signup_price(row: dict[str, Any]) -> float | None:
    price = to_float(row.get("promotionPrice"))
    if price is not None:
        return price
    price_cent = to_int(row.get("promotionPriceCent"))
    if price_cent is not None:
        return price_cent / 100
    return None


def normalize_existing_promotion_price(row: dict[str, Any]) -> None:
    promotion_price = activity_signup_price(row)
    if promotion_price is None:
        return
    row["promotionPrice"] = price_text(promotion_price)
    row["promotionPriceCent"] = int(round(promotion_price * 100))


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
