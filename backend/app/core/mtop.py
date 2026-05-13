from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any


def current_millis() -> str:
    return str(int(time.time() * 1000))


def generate_mtop_sign(token: str, timestamp: str, app_key: str, data: str) -> str:
    raw = f"{token}&{timestamp}&{app_key}&{data}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def extract_h5_token(cookie_dict: dict[str, str], cookie_name: str = "_m_h5_tk") -> str | None:
    raw = cookie_dict.get(cookie_name)
    if not raw:
        return None
    return raw.split("_", 1)[0].strip() or None


def parse_jsonp(body: str, callback: str) -> dict[str, Any]:
    pattern = rf"^{re.escape(callback)}\((.*)\)\s*;?$"
    match = re.match(pattern, body.strip(), re.S)
    if not match:
        raise ValueError("response is not expected JSONP")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("JSONP payload is not an object")
    return payload
