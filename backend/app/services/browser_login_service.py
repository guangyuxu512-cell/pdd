from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

from fastapi import HTTPException
from playwright.sync_api import BrowserContext, Page, sync_playwright
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.cookies import build_cookie_header, parse_cookie_header
from app.models import CookieSnapshot, Shop
from app.platforms import platform_registry


@dataclass
class LoginSession:
    session_id: str
    platform: str
    profile_id: str
    profile_path: Path
    login_url: str
    target_shop_pk: int | None
    backend: str
    playwright: object | None
    context: BrowserContext | ChromeDebugContext
    page: Page | None
    debug_port: int | None = None


class BrowserLoginService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.sessions: dict[str, LoginSession] = {}

    def start(
        self,
        platform: str | None = None,
        login_url: str | None = None,
        cookie_type: str = "main",
        profile_id: str | None = None,
        profile_path: str | None = None,
        target_shop_pk: int | None = None,
    ) -> LoginSession:
        resolved_platform = (platform or self.settings.default_platform).strip() or "default"
        adapter = platform_registry.get(resolved_platform)
        resolved_login_url = (login_url or adapter.login_url(cookie_type)).strip() or "about:blank"
        session_id = uuid4().hex
        resolved_profile_id = profile_id or f"login_{session_id[:12]}"
        resolved_profile_path = Path(profile_path) if profile_path else (
            self.settings.data_dir / "profiles" / resolved_platform / resolved_profile_id
        )
        resolved_profile_path.mkdir(parents=True, exist_ok=True)

        chrome_error: Exception | None = None
        browser_executable = self.resolve_system_browser()
        if browser_executable:
            try:
                session = self._start_chrome_debug(
                    session_id=session_id,
                    platform=resolved_platform,
                    login_url=resolved_login_url,
                    profile_id=resolved_profile_id,
                    profile_path=resolved_profile_path,
                    target_shop_pk=target_shop_pk,
                    browser_executable=browser_executable,
                )
                self.sessions[session_id] = session
                return session
            except Exception as exc:
                chrome_error = exc

        try:
            session = self._start_playwright(
                session_id=session_id,
                platform=resolved_platform,
                login_url=resolved_login_url,
                profile_id=resolved_profile_id,
                profile_path=resolved_profile_path,
                target_shop_pk=target_shop_pk,
            )
        except Exception as exc:
            details = [f"Playwright 错误：{exc}"]
            if chrome_error:
                details.insert(0, f"系统 Chrome 错误：{chrome_error}")
            raise HTTPException(
                status_code=500,
                detail=(
                    "无法打开浏览器。请确认本机已安装 Chrome/Edge，"
                    "且店铺 Profile 没有被其他浏览器实例占用。"
                    f" {'；'.join(details)}"
                ),
            ) from exc

        self.sessions[session_id] = session
        return session

    def _start_playwright(
        self,
        session_id: str,
        platform: str,
        login_url: str,
        profile_id: str,
        profile_path: Path,
        target_shop_pk: int | None,
    ) -> LoginSession:
        playwright = sync_playwright().start()
        launch_options = {"headless": False}
        if self.settings.browser_channel:
            launch_options["channel"] = self.settings.browser_channel
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            **launch_options,
        )
        page = context.pages[0] if context.pages else context.new_page()
        if login_url != "about:blank":
            page.goto(login_url, wait_until="domcontentloaded")
        return LoginSession(
            session_id=session_id,
            platform=platform,
            profile_id=profile_id,
            profile_path=profile_path,
            login_url=login_url,
            target_shop_pk=target_shop_pk,
            backend="playwright",
            playwright=playwright,
            context=context,
            page=page,
        )

    def _start_chrome_debug(
        self,
        session_id: str,
        platform: str,
        login_url: str,
        profile_id: str,
        profile_path: Path,
        target_shop_pk: int | None,
        browser_executable: str,
    ) -> LoginSession:
        debug_port = find_free_port()
        args = [
            browser_executable,
            f"--user-data-dir={profile_path}",
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--new-window",
            login_url,
        ]
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        context = ChromeDebugContext(
            login_url=login_url,
            profile_path=profile_path,
            browser_executable=browser_executable,
            process=process,
            debug_port=debug_port,
        )
        context.wait_until_ready()
        return LoginSession(
            session_id=session_id,
            platform=platform,
            profile_id=profile_id,
            profile_path=profile_path,
            login_url=login_url,
            target_shop_pk=target_shop_pk,
            backend="chrome-cdp",
            playwright=None,
            context=context,
            page=None,
            debug_port=debug_port,
        )

    def resolve_system_browser(self) -> str | None:
        channel = (self.settings.browser_channel or "").strip().lower()
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        edge_paths = [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        if channel in {"msedge", "edge"}:
            candidates = edge_paths + chrome_paths
        elif channel == "chrome":
            candidates = chrome_paths + edge_paths
        else:
            candidates = chrome_paths + edge_paths

        for executable in candidates:
            if Path(executable).exists():
                return executable
        for command in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
            resolved = shutil.which(command)
            if resolved:
                return resolved
        return None

    def capture_and_save(
        self,
        db: Session,
        session_id: str,
        shop_id: str | None,
        shop_name: str | None,
        close_browser: bool = True,
        cookie_type: str = "main",
        cookie_header_text: str | None = None,
    ) -> tuple[Shop, CookieSnapshot]:
        login_session = self.sessions.get(session_id)
        if not login_session:
            raise HTTPException(status_code=404, detail="login session not found")

        manual_cookie_header = str(cookie_header_text or "").strip()
        if manual_cookie_header:
            cookies = parse_cookie_header(manual_cookie_header)
        else:
            cookies = login_session.context.cookies()
        storage_state = login_session.context.storage_state()
        browser_env = self.build_browser_env(login_session, storage_state)
        adapter = platform_registry.get(login_session.platform)
        identity = None
        wangwang: str | None = None
        shop_type: str | None = None
        target_shop = db.get(Shop, login_session.target_shop_pk) if login_session.target_shop_pk else None
        identity_error: Exception | None = None

        if cookie_type == "main":
            try:
                identity = adapter.identify_shop(cookies, storage_state, cookie_type)
            except Exception as exc:
                identity_error = exc
            if identity:
                shop_id = identity.shop_id
                shop_name = identity.shop_name
                wangwang = identity.raw.get("wangwang") if isinstance(identity.raw, dict) else None
                shop_type = identity.raw.get("shop_type") if isinstance(identity.raw, dict) else None
            elif target_shop:
                shop_id = shop_id or target_shop.shop_id
                shop_name = shop_name or target_shop.shop_name
                wangwang = target_shop.wangwang
                shop_type = target_shop.shop_type
            elif identity_error:
                raise identity_error
        elif target_shop:
            shop_id = shop_id or target_shop.shop_id
            shop_name = shop_name or target_shop.shop_name
            wangwang = target_shop.wangwang
            shop_type = target_shop.shop_type

        if not shop_id or not shop_name:
            raise HTTPException(status_code=400, detail="无法确定店铺名和店铺 ID；推广 cookie 请从已有店铺行重新登录")

        cookie_status = "valid" if cookies and (cookie_type != "main" or (shop_id and shop_name)) else "invalid"
        if cookie_type != "main" and cookies:
            cookie_status = target_shop.cookie_status if target_shop else "valid"

        shop = db.exec(
            select(Shop).where(
                Shop.platform == login_session.platform,
                Shop.shop_id == shop_id,
            )
        ).first()
        now = datetime.now()
        if shop:
            shop.shop_name = shop_name
            shop.wangwang = wangwang
            shop.shop_type = shop_type
            shop.profile_id = login_session.profile_id
            shop.profile_path = str(login_session.profile_path)
            shop.browser_env_json = browser_env
            shop.cookie_status = cookie_status
            shop.last_cookie_check_at = now
            shop.updated_at = now
        else:
            shop = Shop(
                platform=login_session.platform,
                shop_id=shop_id,
                shop_name=shop_name,
                wangwang=wangwang,
                shop_type=shop_type,
                profile_id=login_session.profile_id,
                profile_path=str(login_session.profile_path),
                browser_env_json=browser_env,
                cookie_status=cookie_status,
                last_cookie_check_at=now,
            )
        db.add(shop)
        db.commit()
        db.refresh(shop)

        cookie_health = self.taobao_cookie_health(cookies) if login_session.platform == "taobao" and cookie_type == "main" else {}
        missing_cookie_keys = cookie_health.get("missing", []) if isinstance(cookie_health, dict) else []
        snapshot = CookieSnapshot(
            platform=login_session.platform,
            shop_id=shop_id,
            shop_name=shop_name,
            profile_id=login_session.profile_id,
            profile_path=str(login_session.profile_path),
            cookie_count=len(cookies),
            cookie_type=cookie_type,
            cookie_header_text=manual_cookie_header or build_cookie_header(cookies),
            cookies_json=cookies,
            storage_state_json=storage_state,
            status=("incomplete" if missing_cookie_keys else "captured") if cookies else "empty",
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        if close_browser:
            self.close(session_id)
        return shop, snapshot

    @staticmethod
    def taobao_cookie_health(cookies: list[dict[str, Any]]) -> dict[str, Any]:
        names = {str(cookie.get("name") or "") for cookie in cookies}
        required = ["_m_h5_tk", "_m_h5_tk_enc", "tfstk", "isg", "cookie2", "sgcookie", "_tb_token_"]
        recommended = ["p_h5_u", "tracknick", "JSESSIONID", "XSRF-TOKEN"]
        missing = [name for name in required if name not in names]
        missing_recommended = [name for name in recommended if name not in names]
        return {
            "required": required,
            "recommended": recommended,
            "missing": missing,
            "missing_recommended": missing_recommended,
        }

    def warmup_cookie_domains(self, login_session: LoginSession, *, cookie_type: str) -> None:
        if login_session.platform != "taobao" or cookie_type != "main":
            return
        urls = [
            "https://loginmyseller.taobao.com/",
            "https://myseller.taobao.com/",
            "https://myseller.taobao.com/home.htm/SellManage/in_stock?current=1&pageSize=20",
            "https://myseller.taobao.com/home.htm/SellManage/warehouse?current=1&pageSize=20",
            "https://item.upload.taobao.com/sell/v2/publish.htm",
            "https://inventorymanage.taobao.com/qn/inventory/editInventory?hideHeader=5&hasDrawerHeader=true&title=%E7%BC%96%E8%BE%91%E5%BA%93%E5%AD%98&from=taobao-sellManage-edit&showChangeInvMode=false",
            "https://h5api.m.taobao.com/h5/mtop.taobao.sell.pc.manage.async/1.0/",
            "https://login.taobao.com/member/login.jhtml",
        ]
        pages: list[Any] = []
        for url in urls:
            try:
                if isinstance(login_session.context, ChromeDebugContext):
                    login_session.context.open_page(url)
                else:
                    page = login_session.context.new_page()
                    pages.append(page)
                    page.goto(url, wait_until="domcontentloaded", timeout=8000)
                time.sleep(1.2)
            except Exception:
                continue
        time.sleep(2.0)
        for page in pages:
            try:
                page.close()
            except Exception:
                pass

    @staticmethod
    def build_browser_env(login_session: LoginSession, storage_state: dict[str, Any]) -> dict[str, Any]:
        browser_info = storage_state.get("browser") if isinstance(storage_state, dict) else None
        if not isinstance(browser_info, dict):
            browser_info = {}
        user_agent = None
        if login_session.page:
            try:
                user_agent = login_session.page.evaluate("() => navigator.userAgent")
            except Exception:
                user_agent = None
        if not user_agent:
            user_agent = browser_info.get("user_agent")
        return {
            "platform": login_session.platform,
            "profile_id": login_session.profile_id,
            "profile_path": str(login_session.profile_path),
            "backend": login_session.backend,
            "browser_executable": browser_info.get("executable"),
            "user_agent": user_agent,
            "storage_state": storage_state,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
        }

    def close(self, session_id: str) -> None:
        login_session = self.sessions.pop(session_id, None)
        if not login_session:
            return
        try:
            login_session.context.close()
        finally:
            if login_session.playwright:
                login_session.playwright.stop()


class ChromeDebugContext:
    def __init__(
        self,
        login_url: str,
        profile_path: Path,
        browser_executable: str,
        process: subprocess.Popen[bytes],
        debug_port: int,
    ) -> None:
        self.login_url = login_url
        self.profile_path = profile_path
        self.browser_executable = browser_executable
        self.process = process
        self.debug_port = debug_port

    def wait_until_ready(self, timeout_seconds: float = 12.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Chrome 进程已退出，可能是 Profile 被占用或浏览器启动失败")
            try:
                self._debug_json("/json/version")
                return
            except (OSError, URLError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError(f"Chrome 调试端口未就绪：{last_error}")

    def cookies(self) -> list[dict[str, Any]]:
        with CDPClient(self._page_ws_url()) as client:
            try:
                result = client.send("Network.getAllCookies")
            except RuntimeError:
                result = client.send("Storage.getCookies")
        return [normalize_cdp_cookie(cookie) for cookie in result.get("cookies", [])]

    def storage_state(self) -> dict[str, Any]:
        return {
            "cookies": self.cookies(),
            "origins": [],
            "browser": {
                "backend": "chrome-cdp",
                "debug_port": self.debug_port,
                "executable": self.browser_executable,
                "profile_path": str(self.profile_path),
                "user_agent": self.user_agent(),
            },
        }

    def user_agent(self) -> str | None:
        try:
            with CDPClient(self._page_ws_url()) as client:
                result = client.send("Browser.getVersion")
                user_agent = result.get("userAgent")
                return str(user_agent) if user_agent else None
        except Exception:
            return None

    def open_page(self, url: str) -> None:
        with CDPClient(self._page_ws_url()) as client:
            client.send("Target.createTarget", {"url": url})

    def close(self) -> None:
        try:
            version = self._debug_json("/json/version")
            websocket_url = version.get("webSocketDebuggerUrl")
            if websocket_url:
                with CDPClient(websocket_url) as client:
                    client.send("Browser.close")
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()

    def _page_ws_url(self) -> str:
        targets = self._debug_json("/json/list")
        preferred_host = urlparse(self.login_url).hostname or ""
        for target in targets:
            if target.get("type") == "page" and preferred_host in target.get("url", ""):
                return str(target["webSocketDebuggerUrl"])
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
        raise RuntimeError("没有找到可读取 cookie 的浏览器页面")

    def _debug_json(self, path: str) -> Any:
        url = f"http://127.0.0.1:{self.debug_port}{path}"
        with urlopen(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


class CDPClient:
    def __init__(self, websocket_url: str) -> None:
        self.websocket_url = websocket_url
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> CDPClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        if self.sock:
            try:
                self._send_frame(b"", opcode=0x8)
            finally:
                self.sock.close()

    def connect(self) -> None:
        parsed = urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise RuntimeError(f"不支持的 WebSocket 地址：{self.websocket_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)
        response = self._recv_http_header(sock)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("Chrome 调试 WebSocket 握手失败")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        if accept not in response:
            sock.close()
            raise RuntimeError("Chrome 调试 WebSocket 校验失败")
        self.sock = sock

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self.next_id
        self.next_id += 1
        payload = json.dumps(
            {"id": message_id, "method": method, "params": params or {}},
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_frame(payload)
        while True:
            message = json.loads(self._recv_message())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result", {})

    @staticmethod
    def _recv_http_header(sock: socket.socket) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        if not self.sock:
            raise RuntimeError("WebSocket 未连接")
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_message(self) -> str:
        if not self.sock:
            raise RuntimeError("WebSocket 未连接")
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            masked = bool(second & 0x80)
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("WebSocket 已关闭")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode in {0x1, 0x2}:
                return payload.decode("utf-8")

    def _recv_exact(self, length: int) -> bytes:
        if not self.sock:
            raise RuntimeError("WebSocket 未连接")
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise RuntimeError("WebSocket 连接已断开")
            chunks.extend(chunk)
        return bytes(chunks)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def normalize_cdp_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"):
        if key in cookie:
            normalized[key] = cookie[key]
    if "expires" not in normalized:
        normalized["expires"] = -1 if cookie.get("session") else 0
    for key in ("priority", "sameParty", "sourceScheme", "sourcePort"):
        if key in cookie:
            normalized[key] = cookie[key]
    return normalized


browser_login_service = BrowserLoginService()
