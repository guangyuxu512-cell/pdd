from __future__ import annotations

import re
from collections import OrderedDict, defaultdict
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import AppConfig, FeishuPriceSyncResult, FeishuSkuPriceMap, ProductSku, Shop


GLOBAL_SHOP_ID = "__GLOBAL__"
GLOBAL_SHOP_NAME = "通用价"
FEISHU_OPEN_BASE = "https://open.feishu.cn/open-apis"

FIELD_ALIASES = {
    "shop_id": ["店铺ID", "shop_id", "店铺编号", "店铺编码", "shopid"],
    "shop_name": ["店铺名称", "店铺名", "shop_name", "shopname"],
    "sku_code": ["SKU编码", "sku_code", "SKU Code", "sku code", "skuOuterId", "商家SKU编码", "外部编码", "商家编码"],
    "normal_price": ["正常售价", "日常售价", "原价", "售价", "normal_sale_price", "normal_price"],
    "signup_price": ["顺手报名价", "报名价", "活动价", "申报价", "activity_price", "signup_price", "price", "价格"],
    "enabled": ["是否启用", "启用", "状态", "记录状态", "record_status"],
    "activity_id": ["活动ID", "activity_id"],
    "activity_name": ["活动名称", "activity_name"],
    "remark": ["备注", "remark", "说明"],
    "record_id": ["记录ID", "record_id", "recordId", "飞书记录ID", "feishu_record_id"],
}


class FeishuPriceSyncService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_from_feishu(self) -> FeishuPriceSyncResult:
        config = self._config()
        app_id = required_config(config, "feishu_app_id")
        app_secret = required_config(config, "feishu_app_secret")
        app_token = required_config(config, "feishu_bitable_id")
        table_id = required_config(config, "feishu_sheet_id")

        records = self._fetch_records(
            app_id=app_id,
            app_secret=app_secret,
            app_token=app_token,
            table_id=table_id,
        )
        normalized_rows, skipped = self._normalize_rows(records)
        resolved_rows, warnings = self._resolve_rows(normalized_rows)
        resolved_rows = dedupe_rows(resolved_rows)
        global_rows = [row for row in resolved_rows if row["resolved_shop_id"] == GLOBAL_SHOP_ID]
        shop_rows = [row for row in resolved_rows if row["resolved_shop_id"] != GLOBAL_SHOP_ID]

        now = datetime.now()
        for row in resolved_rows:
            self._upsert_price_row(row, now)
        self.session.commit()

        updated_global = self._apply_global_prices(global_rows, now)
        updated_shop = self._apply_shop_prices(shop_rows, now)
        self.session.commit()

        return FeishuPriceSyncResult(
            success=True,
            source_rows=len(records),
            valid_rows=len(normalized_rows),
            skipped_rows=len(skipped),
            global_rows=len(global_rows),
            shop_rows=len(shop_rows),
            mapping_upserted=len(resolved_rows),
            updated_global_skus=updated_global,
            updated_shop_skus=updated_shop,
            warnings=warnings + [item["error"] for item in skipped[:20]],
        )

    def _config(self) -> dict[str, str]:
        rows = self.session.exec(select(AppConfig)).all()
        return {row.key: row.value for row in rows}

    def _fetch_records(self, *, app_id: str, app_secret: str, app_token: str, table_id: str) -> list[dict[str, Any]]:
        tenant_token = self._tenant_access_token(app_id, app_secret)
        headers = {"Authorization": f"Bearer {tenant_token}"}
        records: list[dict[str, Any]] = []
        page_token = ""
        with httpx.Client(timeout=30, headers=headers) as client:
            while True:
                params = {"page_size": "100"}
                if page_token:
                    params["page_token"] = page_token
                response = client.get(
                    f"{FEISHU_OPEN_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                    params=params,
                )
                payload = response.json()
                if response.status_code >= 400 or payload.get("code") not in (0, None):
                    raise HTTPException(status_code=502, detail=f"飞书记录读取失败：{payload}")
                data = payload.get("data", {})
                records.extend(data.get("items", []) or [])
                page_token = data.get("page_token") or ""
                if not data.get("has_more"):
                    break
        return records

    def _tenant_access_token(self, app_id: str, app_secret: str) -> str:
        response = httpx.post(
            f"{FEISHU_OPEN_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=20,
        )
        payload = response.json()
        token = payload.get("tenant_access_token")
        if response.status_code >= 400 or payload.get("code") not in (0, None) or not token:
            raise HTTPException(status_code=502, detail=f"飞书 tenant_access_token 获取失败：{payload}")
        return str(token)

    def _normalize_rows(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized_rows = []
        skipped = []
        for record in records:
            fields = record.get("fields") if isinstance(record, dict) else None
            if not isinstance(fields, dict):
                skipped.append({"error": "飞书记录缺少 fields", "record": record})
                continue
            row = dict(fields)
            row["record_id"] = record.get("record_id") or record.get("recordId") or record.get("id")
            normalized, error = normalize_price_row(row)
            if error:
                skipped.append({"error": error, "record": row})
            else:
                normalized_rows.append(normalized)
        return normalized_rows, skipped

    def _resolve_rows(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        shops = self.session.exec(select(Shop)).all()
        shop_id_to_name = {shop.shop_id: shop.shop_name for shop in shops}
        shop_name_to_ids: dict[str, list[str]] = defaultdict(list)
        for shop in shops:
            shop_name_to_ids[shop.shop_name].append(shop.shop_id)

        resolved_rows = []
        warnings = []
        for row in rows:
            resolved, warning = resolve_scope_row(row, shop_name_to_ids, shop_id_to_name)
            if warning:
                warnings.append(warning)
            else:
                resolved_rows.append(resolved)
        return resolved_rows, warnings

    def _upsert_price_row(self, row: dict[str, Any], now: datetime) -> None:
        price_row = self.session.exec(
            select(FeishuSkuPriceMap).where(
                FeishuSkuPriceMap.shop_id == row["resolved_shop_id"],
                FeishuSkuPriceMap.sku_code == row["sku_code"],
            )
        ).first()
        values = {
            "shop_name": row["resolved_shop_name"],
            "normal_sale_price": row["normal_sale_price"],
            "shunshou_signup_price": row["shunshou_signup_price"],
            "record_status": row["record_status"],
            "feishu_record_id": row["record_id"],
            "activity_id": row["activity_id"],
            "activity_name": row["activity_name"],
            "remark": row["remark"],
            "raw_json": row["raw"],
            "last_sync_at": now,
            "updated_at": now,
        }
        if price_row:
            for key, value in values.items():
                setattr(price_row, key, value)
        else:
            price_row = FeishuSkuPriceMap(
                shop_id=row["resolved_shop_id"],
                sku_code=row["sku_code"],
                created_at=now,
                **values,
            )
        self.session.add(price_row)

    def _apply_global_prices(self, rows: list[dict[str, Any]], now: datetime) -> int:
        updated = 0
        for row in rows:
            skus = self.session.exec(
                select(ProductSku).where(ProductSku.sku_code == row["sku_code"])
            ).all()
            for sku in skus:
                if row["record_status"] != "active":
                    sku.normal_sale_price = None
                    sku.shunshou_signup_price = None
                else:
                    sku.normal_sale_price = row["normal_sale_price"]
                    sku.shunshou_signup_price = row["shunshou_signup_price"]
                sku.updated_at = now
                self.session.add(sku)
                updated += 1
        return updated

    def _apply_shop_prices(self, rows: list[dict[str, Any]], now: datetime) -> int:
        global_prices = {
            row.sku_code: row
            for row in self.session.exec(
                select(FeishuSkuPriceMap).where(
                    FeishuSkuPriceMap.shop_id == GLOBAL_SHOP_ID,
                    FeishuSkuPriceMap.record_status == "active",
                )
            ).all()
        }
        updated = 0
        for row in rows:
            skus = self.session.exec(
                select(ProductSku).where(
                    ProductSku.shop_id == row["resolved_shop_id"],
                    ProductSku.sku_code == row["sku_code"],
                )
            ).all()
            fallback = global_prices.get(row["sku_code"])
            for sku in skus:
                if row["record_status"] == "active":
                    sku.normal_sale_price = row["normal_sale_price"]
                    sku.shunshou_signup_price = row["shunshou_signup_price"]
                elif fallback:
                    sku.normal_sale_price = fallback.normal_sale_price
                    sku.shunshou_signup_price = fallback.shunshou_signup_price
                else:
                    sku.normal_sale_price = None
                    sku.shunshou_signup_price = None
                sku.updated_at = now
                self.session.add(sku)
                updated += 1
        return updated


def required_config(config: dict[str, str], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"运行配置缺少 {key}")
    return value


def normalize_price_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    sku_code = safe_str(pick_value(row, "sku_code"))
    normal_price = safe_decimal(pick_value(row, "normal_price"))
    signup_price = safe_decimal(pick_value(row, "signup_price"))
    shop_id = safe_str(pick_value(row, "shop_id"))
    shop_name = safe_str(pick_value(row, "shop_name"))
    record_status = normalize_record_status(row)
    if not sku_code:
        return None, "缺少SKU编码"
    if record_status == "active" and normal_price is None and signup_price is None:
        return None, f"SKU编码={sku_code} 缺少正常售价或顺手报名价"

    is_global = looks_like_global_marker(shop_id) or looks_like_global_marker(shop_name) or (not shop_id and not shop_name)
    if is_global:
        shop_id = None
        shop_name = None
    return {
        "raw": row,
        "record_id": safe_str(pick_value(row, "record_id")) or safe_str(row.get("record_id")),
        "shop_id": shop_id,
        "shop_name": shop_name,
        "sku_code": sku_code,
        "normal_sale_price": normal_price,
        "shunshou_signup_price": signup_price,
        "record_status": record_status,
        "activity_id": safe_str(pick_value(row, "activity_id")),
        "activity_name": safe_str(pick_value(row, "activity_name")),
        "remark": safe_str(pick_value(row, "remark")),
        "scope": "global" if is_global else "shop",
    }, None


def resolve_scope_row(
    row: dict[str, Any],
    shop_name_to_ids: dict[str, list[str]],
    shop_id_to_name: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    if row["scope"] == "global":
        resolved = dict(row)
        resolved["resolved_shop_id"] = GLOBAL_SHOP_ID
        resolved["resolved_shop_name"] = GLOBAL_SHOP_NAME
        return resolved, None
    if row.get("shop_id"):
        resolved = dict(row)
        resolved["resolved_shop_id"] = row["shop_id"]
        resolved["resolved_shop_name"] = row.get("shop_name") or shop_id_to_name.get(row["shop_id"]) or row["shop_id"]
        return resolved, None
    if row.get("shop_name"):
        matched_ids = list(OrderedDict.fromkeys(shop_name_to_ids.get(row["shop_name"], [])))
        if len(matched_ids) == 1:
            resolved = dict(row)
            resolved["resolved_shop_id"] = matched_ids[0]
            resolved["resolved_shop_name"] = row["shop_name"]
            return resolved, None
        if len(matched_ids) > 1:
            return None, f"店铺名称={row['shop_name']} 匹配到多个店铺ID，请改用店铺ID"
        return None, f"店铺名称={row['shop_name']} 未找到对应店铺ID"
    return None, "店铺覆盖价缺少店铺ID/店铺名称"


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = OrderedDict()
    for row in rows:
        deduped[(row["resolved_shop_id"], row["sku_code"])] = row
    return list(deduped.values())


def pick_value(row: dict[str, Any], field_name: str) -> Any:
    key_map = {normalize_key_name(key): key for key in row.keys() if normalize_key_name(key)}
    for alias in FIELD_ALIASES.get(field_name, []):
        raw_key = key_map.get(normalize_key_name(alias))
        if raw_key is not None:
            return row.get(raw_key)
    return None


def normalize_key_name(name: Any) -> str:
    text = str(name or "").strip().replace("\u3000", " ")
    return re.sub(r"[\s_\-\(\)（）:：/\\\.]+", "", text).lower()


def normalize_record_status(row: dict[str, Any]) -> str:
    enabled = pick_value(row, "enabled")
    text = str(enabled or "").strip().lower()
    if text in ("0", "false", "no", "n", "否", "停用", "禁用", "失效", "inactive", "off", "disabled"):
        return "inactive"
    return "active"


def looks_like_global_marker(value: Any) -> bool:
    text = safe_str(value)
    if not text:
        return False
    return text.strip().lower() in {"*", "all", "global", "__global__", "全部店铺", "全店铺", "全局", "通用", "通用价", "所有店铺"}


def safe_str(value: Any) -> str | None:
    value = unwrap_feishu_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def safe_decimal(value: Any) -> float | None:
    value = unwrap_feishu_value(value)
    if value is None or value == "":
        return None
    text = str(value).strip().replace("¥", "").replace("￥", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def unwrap_feishu_value(value: Any) -> Any:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or item.get("value") or "").strip())
            else:
                parts.append(str(item).strip())
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if value.get(key) is not None:
                return value.get(key)
    return value
