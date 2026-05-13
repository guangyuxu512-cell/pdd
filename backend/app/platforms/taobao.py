from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.core.cookies import cookies_to_dict
from app.core.mtop import current_millis, extract_h5_token, generate_mtop_sign, parse_jsonp
from app.platforms.base import CookieCheckResult, ShopIdentity

TAOBAO_SHOP_INFO_URL = "https://h5api.m.taobao.com/h5/mtop.alibaba.shop.shopinfo.info.get/1.0/"
TAOBAO_APP_KEY = "12574478"
TAOBAO_API = "mtop.alibaba.shop.shopInfo.info.get"
TAOBAO_TTID = "11320@taobao_WEB_9.9.99"
TAOBAO_DATA = '{"isFast":false}'
TAOBAO_REFERER = "https://myseller.taobao.com/home.htm/shop-manage/shop-center"


class TaobaoPlatformAdapter:
    platform = "taobao"

    def login_url(self, cookie_type: str = "main") -> str:
        return "https://myseller.taobao.com/home.htm/SellManage/in_stock?current=1&pageSize=20"

    def identify_shop(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> ShopIdentity:
        cookie_dict = cookies_to_dict(cookies)
        token = extract_h5_token(cookie_dict)
        if not token:
            raise HTTPException(
                status_code=400,
                detail="淘宝登录态里没有 _m_h5_tk，无法生成 mtop sign，暂时不能自动抓取店铺信息",
            )

        user_agent = None
        if isinstance(storage_state, dict):
            browser_info = storage_state.get("browser")
            if isinstance(browser_info, dict):
                user_agent = browser_info.get("user_agent")

        payload = self.fetch_shop_info(
            cookie_dict=cookie_dict,
            token=token,
            user_agent=str(user_agent) if user_agent else None,
        )
        shop_id, shop_name = self.extract_shop_identity(payload)
        if not shop_id or not shop_name:
            raise HTTPException(
                status_code=400,
                detail="已请求淘宝店铺信息接口，但未识别出店铺 ID 或店铺名；请检查接口返回结构是否变化",
            )
        metadata = self.extract_shop_metadata(payload)
        return ShopIdentity(
            shop_id=str(shop_id),
            shop_name=str(shop_name),
            raw={
                "wangwang": metadata.get("wangwang"),
                "shop_type": metadata.get("shop_type"),
                "payload": payload,
            },
        )

    def check_cookie(
        self,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        cookie_type: str = "main",
    ) -> CookieCheckResult:
        if not cookies:
            return CookieCheckResult(valid=False, message="没有可用 cookie")
        try:
            identity = self.identify_shop(cookies, storage_state, cookie_type)
            return CookieCheckResult(valid=True, shop_identity=identity, message="淘宝 cookie 有效")
        except Exception as exc:
            return CookieCheckResult(valid=False, message=str(exc))

    def fetch_shop_info(
        self,
        *,
        cookie_dict: dict[str, str],
        token: str,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        timestamp = current_millis()
        sign = generate_mtop_sign(token, timestamp, TAOBAO_APP_KEY, TAOBAO_DATA)
        params = {
            "jsv": "2.6.1",
            "appKey": TAOBAO_APP_KEY,
            "t": timestamp,
            "sign": sign,
            "api": TAOBAO_API,
            "v": "1.0",
            "ttid": TAOBAO_TTID,
            "dataType": "originaljsonp",
            "type": "originaljsonp",
            "callback": "mtopjsonp_shopinfo",
            "data": TAOBAO_DATA,
        }
        headers: dict[str, str] = {
            "accept": "*/*",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": TAOBAO_REFERER,
        }
        if user_agent:
            headers["user-agent"] = user_agent

        try:
            with httpx.Client(
                timeout=20,
                cookies=cookie_dict,
                headers=headers,
                follow_redirects=True,
            ) as client:
                response = client.get(TAOBAO_SHOP_INFO_URL, params=params)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"请求淘宝店铺信息接口失败：{exc}") from exc

        body = response.text.strip()
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"淘宝店铺信息接口返回异常：{body[:500]}")

        try:
            payload = parse_jsonp(body, params["callback"])
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="淘宝店铺信息接口返回不是预期的 JSONP 格式") from exc
        ret = payload.get("ret")
        if isinstance(ret, list) and ret and not str(ret[0]).startswith("SUCCESS"):
            raise HTTPException(status_code=400, detail=f"淘宝店铺信息接口返回失败：{ret[0]}")
        return payload

    @classmethod
    def extract_shop_identity(cls, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        candidates: list[dict[str, Any]] = []
        cls.collect_dicts(payload, candidates)
        for item in candidates:
            shop_id = cls.pick_first_text(item, ("shopId", "shop_id", "shopid", "sellerId", "mallId", "memberId"))
            shop_name = cls.pick_first_text(
                item,
                ("shopName", "shop_name", "shopTitle", "sellerNick", "nick", "wangwang", "name"),
            )
            if shop_id and shop_name:
                return shop_id, shop_name
        return None, None

    @classmethod
    def extract_shop_metadata(cls, payload: dict[str, Any]) -> dict[str, str | None]:
        candidates: list[dict[str, Any]] = []
        cls.collect_dicts(payload, candidates)
        metadata = {"wangwang": None, "shop_type": None}
        for item in candidates:
            if metadata["wangwang"] is None:
                metadata["wangwang"] = cls.pick_first_text(
                    item,
                    ("wangwang", "wangWang", "userNick", "user_nick", "sellerNick", "nick", "accountName", "loginNick"),
                )
            if metadata["shop_type"] is None:
                metadata["shop_type"] = cls.pick_first_text(
                    item,
                    ("shopType", "shop_type", "shopTypeName", "shopTypeDesc", "shopCategory", "sellerType"),
                )
            if metadata["wangwang"] and metadata["shop_type"]:
                break
        return metadata

    @classmethod
    def collect_dicts(cls, value: Any, output: list[dict[str, Any]]) -> None:
        if isinstance(value, dict):
            output.append(value)
            for item in value.values():
                cls.collect_dicts(item, output)
        elif isinstance(value, list):
            for item in value:
                cls.collect_dicts(item, output)

    @staticmethod
    def pick_first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)) and str(value).strip():
                return str(value)
        return None
