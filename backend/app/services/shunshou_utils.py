from __future__ import annotations

import random
import re
import time
from typing import Any


STATUS_MAP = {
    0: "未知",
    1: "未开始",
    2: "进行中",
    3: "已结束",
    4: "已暂停",
}


def normalize_candidate_status(warn_message: Any) -> dict[str, Any]:
    message = text(warn_message)
    if not message:
        return {"warn_status": "null", "activity_item_status": "可报名", "is_joined": 0}
    if "已经参加当前的活动" in message or "已参加当前活动" in message or "已经参加活动" in message:
        return {"warn_status": "not_null", "activity_item_status": "已参加活动", "is_joined": 1}
    return {"warn_status": "not_null", "activity_item_status": "其他原因", "is_joined": 0}


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


def price_available(row: dict[str, Any], price: float) -> tuple[bool, str]:
    min_limit = 0.01
    rule = row.get("hgPriceLimitRule") or {}
    min_source = "默认"
    if isinstance(rule, dict):
        min_rule = to_float(rule.get("minPriceLimit"))
        if min_rule is not None:
            min_limit = min_rule
            min_source = "minPriceLimit"
    max_candidates = [
        ("originalPrice", to_float(row.get("originalPrice"))),
        ("minDiscountPrice", to_float(row.get("minDiscountPrice"))),
    ]
    if isinstance(rule, dict):
        max_candidates.append(("hgPriceUpperLimit", to_float(rule.get("hgPriceUpperLimit"))))
    max_values = [(name, value) for name, value in max_candidates if value is not None]
    max_source = ""
    max_limit = None
    if max_values:
        max_source, max_limit = min(max_values, key=lambda item: item[1])
    if price < min_limit:
        return False, f"报名价 {price_text(price)} 低于活动最小值 {price_text(min_limit)}（来源 {min_source}）"
    if max_limit is not None and price > max_limit:
        source_text = "，".join(f"{name}={price_text(value)}" for name, value in max_values)
        return False, f"报名价 {price_text(price)} 高于活动最大值 {price_text(max_limit)}（取自 {max_source}；{source_text}）"
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
