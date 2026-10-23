"""Explicit WebView bridge. All application work runs on one asyncio loop."""
import asyncio
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

from .worker import Worker
from .engine import Engine, order_payload, price_text, status_text
from .market import Market
from .security import KeyStore, private_pem, SecurityError
from .storage import ConfigStore, BusyError
from .transport import SignedTransport, ApiFailure
from . import __version__


class Controller:
    def __init__(self, directory, journal):
        self.worker = Worker()
        self.journal = journal
        self.config = ConfigStore(directory, journal)
        self.keys = KeyStore(directory)
        self.state = {"connection": "未连接", "event_connection": "未连接", "accounts": [],
                      "selected": None, "positions": {}, "balance": {}, "orders": [],
                      "market": {}, "trades": {}, "context": {}, "context_status": "", "server": {}, "cursor": None}
        self.engine = Engine(journal, self.notify)
        self.market = Market(self.engine, self.notify)
        self.clicks = set()
        self.last_mutation = {}
        self.click_lock = threading.Lock()
        self.window = None

    def notify(self, kind, data, generation=None):
        if generation is not None and generation != self.engine.generation:
            return
        if kind == "accounts" and self.state.get("selected") != self.engine.selected:
            self.clear_account()
            if hasattr(self, "market"):
                asyncio.create_task(self.market.stop())
        if kind == "events" and not self.engine.connected:
            self.clear_account()
            if hasattr(self, "market"):
                asyncio.create_task(self.market.stop())
        if kind == "market_clear":
            self.state["market"], self.state["trades"] = data, {}
        elif kind not in {"pending", "detail"}:
            self.state[kind] = data
        self.state["selected"] = self.engine.selected

    def clear_account(self):
        for key in ("positions", "balance", "market", "trades", "context"):
            self.state[key] = {}
        self.state["orders"], self.state["cursor"] = [], None
        self.state["context_status"] = ""

    async def snapshot(self):
        result = dict(self.state)
        result["clientVersion"] = __version__
        config = self.config.load()
        result["config"] = config
        result["keyPresent"] = self.keys.path.exists()
        result["connected"] = self.engine.connected
        result["selected"] = self.engine.selected
        result["pending"] = [{k: row[k] for k in ("request_id", "account_ref", "operation", "phase", "error_code", "target")} for row in self.journal.pending(config["origin"], config["client_id"])]
        for order in result["orders"]:
            order["statusText"] = status_text(order["status"])
        return result

    async def action(self, operation, data):
        if operation == "page_ready":
            previous = self.market.symbol
            await self.market.stop()
            if self.engine.connected:
                await self.refresh()
                if previous and self.engine.selected:
                    await self.market.select(previous)
        elif operation == "connect":
            await self.market.stop()
            self.clear_account()
            cfg = self.config.load()
            self.state["server"] = {}
            await self.engine.connect(SignedTransport(cfg["origin"], cfg["client_id"], private_pem(self.keys.load())))
            try:
                self.state["server"] = await self.engine.transport.request("GET", "/v1/info")
            except ApiFailure as exc:
                self.state["server"] = {"status": "LEGACY" if exc.status == 404 else "UNAVAILABLE"}
            await self.refresh()
        elif operation == "disconnect":
            await self.market.stop()
            await self.engine.stop()
            self.clear_account()
            self.state["server"] = {}
        elif operation == "account":
            await self.market.stop()
            self.engine.choose(data.get("accountRef"))
            self.clear_account()
            await self.refresh()
        elif operation == "refresh":
            await self.refresh(data.get("cursor"))
        elif operation == "search":
            return await self.market.search(data.get("q", ""))
        elif operation == "symbol":
            await self.market.select(data.get("symbol"))
        elif operation == "detail":
            return await self.engine.detail(data["orderId"])
        elif operation in {"submit", "replace", "cancel"}:
            if data.get("accountRef") != self.engine.selected:
                raise BusyError("账户已切换，请重新操作")
            context = self.state["context"]
            # LIVE must be explicitly supported by this server deployment.
            # Ordinary account approval cannot override a read-only perimeter.
            if context.get("environment") not in {"SANDBOX", "LIVE"} or (
                    context.get("environment") == "LIVE" and context.get("tradeDeploymentAllowed") is not True):
                raise BusyError("需要服务器明确授权的 SANDBOX 或 LIVE 交易部署；当前只读")
            if operation == "cancel":
                if context.get("cancelEnabled") is not True:
                    raise BusyError("服务器未授予撤单权限")
            elif context.get("tradeEnabled") is not True:
                raise BusyError("服务器交易权限或门禁未就绪")
            if operation == "submit":
                payload = order_payload(self.engine.selected, data.get("symbol", ""), data.get("side"), data.get("orderType"), str(data.get("quantity", "")), str(data.get("limitPrice", "")))
            else:
                payload = {"accountRef": self.engine.selected}
                if operation == "replace":
                    payload["limitPrice"] = price_text(str(data.get("limitPrice", "")))
            target = data.get("orderId", "")
            if operation != "submit":
                await self.engine.detail(target)
            intent = self.engine.prepare(operation, payload, target)
            await self.engine.dispatch(intent)
        else:
            raise ValueError("不支持的操作")
        return await self.snapshot()

    async def refresh(self, cursor=None):
        await self.engine.refresh(cursor)
        ref, generation = self.engine.selected, self.engine.generation
        if ref:
            try:
                info = await self.engine.transport.request("GET", "/v1/info")
                if generation == self.engine.generation:
                    self.state["server"] = info
            except ApiFailure:
                pass
            try:
                result = await self.engine.transport.request("GET", f"/v1/accounts/{quote(ref, safe='')}/ui-context")
                if generation == self.engine.generation and result.get("accountRef") == ref:
                    self.state["context"] = result
                    self.state["context_status"] = "READY"
                elif generation == self.engine.generation:
                    self.state["context"] = {}
                    self.state["context_status"] = "INVALID_RESPONSE"
            except ApiFailure as exc:
                if generation == self.engine.generation:
                    self.state["context"] = {}
                    self.state["context_status"] = "EDGE_BLOCKED" if exc.code == "EDGE_BLOCKED" else "NOT_SUPPORTED" if exc.status == 404 else "DENIED" if exc.status == 403 else "UNAVAILABLE"

    def close(self):
        async def stop():
            await self.market.stop()
            await self.engine.stop()
        try:
            self.worker.submit(stop()).result(10)
        finally:
            self.worker.close()


class Bridge:
    """Only these methods are exposed. Controller and keys remain private."""
    def __init__(self, controller):
        self._controller = controller

    def get_state(self):
        return self._call(self._controller.snapshot())

    def action(self, operation, data):
        if not isinstance(operation, str) or operation not in {"page_ready", "connect", "disconnect", "account", "refresh", "search", "symbol", "detail", "submit", "replace", "cancel"}:
            return {"error": "不支持的操作"}
        if not isinstance(data, dict) or any(not isinstance(data.get(key, ""), (str, type(None))) for key in ("accountRef", "orderId")):
            return {"error": "输入格式错误"}
        c = self._controller
        account = data.get("accountRef", c.engine.selected)
        tag = (operation, account, data.get("orderId", ""))
        with c.click_lock:
            if operation in {"submit", "replace", "cancel"} and time.monotonic() - c.last_mutation.get(tag, -10) < 1:
                return {"error": "操作刚刚提交，请等待状态更新"}
            if tag in c.clicks:
                return {"error": "操作处理中，请勿重复点击"}
            c.clicks.add(tag)
            if operation in {"submit", "replace", "cancel"}:
                c.last_mutation[tag] = time.monotonic()
        try:
            return self._call(c.action(operation, data))
        finally:
            with c.click_lock:
                c.clicks.discard(tag)

    def save_config(self, origin, client_id):
        async def save():
            if self._controller.engine.connected:
                raise BusyError("请先断开连接再保存配置")
            self._controller.config.save(origin, client_id)
            return {"message": "配置已保存；尚未连接服务器"}
        return self._call(save())

    def key_operation(self, operation):
        # Native dialogs keep private PEM and passphrases out of JavaScript.
        c = self._controller
        with c.click_lock:
            if "key" in c.clicks:
                return {"error": "密钥操作处理中"}
            c.clicks.add("key")
        try:
            if operation == "generate":
                async def generate():
                    if c.engine.connected:
                        raise BusyError("请先断开连接再更换密钥")
                    c.keys.generate()
                    return {"message": "密钥操作完成"}
                return self._call(generate())
            elif operation in {"import", "export"}:
                import webview
                mode = webview.FileDialog.OPEN if operation == "import" else webview.FileDialog.SAVE
                chosen = c.window.create_file_dialog(mode, save_filename="Finfusion-public.pem", file_types=("PEM (*.pem)",))
                if not chosen:
                    return {"message": "已取消"}
                if operation == "export":
                    async def export():
                        Path(chosen[0]).write_bytes(c.keys.public_pem())
                        return {"message": "公钥已导出"}
                    return self._call(export())
                else:
                    import tkinter as tk
                    from tkinter.simpledialog import askstring
                    root = tk.Tk(); root.withdraw()
                    try:
                        password = askstring("导入 P-256 私钥", "加密 PEM 的密码（未加密可留空）", show="*", parent=root)
                    finally:
                        root.destroy()
                    if password is None:
                        return {"message": "已取消"}
                    async def import_key():
                        if c.engine.connected:
                            raise BusyError("请先断开连接再更换密钥")
                        c.keys.import_file(chosen[0], password.encode() if password else None)
                        return {"message": "私钥已加密保存，请重新鉴权"}
                    return self._call(import_key())
            else:
                return {"error": "不支持的密钥操作"}
            return {"message": "密钥操作完成"}
        except Exception:
            return {"error": "密钥操作失败，请检查 P-256 PEM、密码及文件权限"}
        finally:
            with c.click_lock:
                c.clicks.discard("key")

    def _call(self, coroutine):
        try:
            return self._controller.worker.submit(coroutine).result(120)
        except (ApiFailure, ValueError, BusyError, SecurityError) as exc:
            return {"error": str(exc)}
        except Exception:
            return {"error": "操作未完成；交易记录将保留，切勿重复提交"}
