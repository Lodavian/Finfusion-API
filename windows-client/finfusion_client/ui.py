import asyncio
import concurrent.futures
import hashlib
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from .engine import Engine, order_payload, price_text, status_text
from .security import KeyStore, private_pem
from .storage import ConfigStore
from .transport import SignedTransport, ApiFailure, ERRORS
from .theme import COLORS, GlassCard, ScrollableFields, apply_theme, dark_caption


class Worker:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        remaining = asyncio.all_tasks(self.loop)
        for task in remaining:
            task.cancel()
        if remaining:
            self.loop.run_until_complete(asyncio.gather(*remaining, return_exceptions=True))
        self.loop.close()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=8)


def table(parent, columns, headings, height=5):
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, pady=4)
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=height)
    for col, heading in zip(columns, headings):
        tree.heading(col, text=heading)
        tree.column(col, width=115, minwidth=65)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.empty_label = tk.Label(frame, text="选择账户并刷新后显示数据", background=COLORS['surface'],
                               foreground=COLORS['muted'], font=("Microsoft YaHei UI", 10))
    tree.tag_configure('confirmed', foreground=COLORS['green'])
    tree.tag_configure('uncertain', foreground=COLORS['amber'])
    tree.tag_configure('rejected', foreground=COLORS['red'])
    return tree


class ClientWindow:
    def __init__(self, root, directory, journal):
        self.root, self.directory, self.journal = root, directory, journal
        self.worker = Worker()
        self.messages = queue.Queue()
        self.engine = Engine(journal, lambda k, d, g=None: self.messages.put((k, d, g)))
        self.config = ConfigStore(directory, journal)
        self.keys = KeyStore(directory)
        self.rows = {}
        self.account_labels = {}
        self.current_ref = None
        self.cursor = None
        self.closing = False
        self.busy_accounts = set()
        self.pending_rows = journal.pending()
        self.connect_busy = False
        self.server_trade_gate = None
        self.detail_dialog = None
        from . import __version__
        self.root.title("Finfusion Client · " + __version__)
        self.root.geometry("1240x780")
        self.root.minsize(1000, 650)
        self.style = apply_theme(root)
        self.connection = tk.StringVar(value="未连接 · 启动不会发送交易")
        self.event_status = tk.StringVar(value="订单事件未连接")
        self.readiness = tk.StringVar(value="交易就绪：未知，以服务器为准")
        self.balance = tk.StringVar(value="美元购买力：暂无数据")
        self.notice = tk.StringVar(value="先在设置中配置服务器、clientId 和密钥，再点击连接。")
        self.symbol = tk.StringVar(value="AAPL")
        self.kind = tk.StringVar(value="MARKET")
        self.quantity = tk.StringVar(value="1")
        self.price = tk.StringVar(value="")
        self.balance_value = tk.StringVar(value="暂无数据")
        self._build()
        self._render_pending(journal.pending())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(60, self._poll)
        root.after_idle(lambda: dark_caption(root))

    def _build(self):
        outer = ttk.Frame(self.root, style="App.TFrame", padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        self.header_card = GlassCard(outer, height=90, padding=16)
        self.header_card.grid(row=0, column=0, sticky="ew")
        top = self.header_card.body
        brand = ttk.Frame(top)
        brand.pack(side="left")
        ttk.Label(brand, text="FINFUSION API  /  SINGLE SYMBOL", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Finfusion Client", style="Title.TLabel").pack(anchor="w")
        self.connect_button = ttk.Button(top, text="连接服务器", style="Primary.TButton", command=self.connect)
        self.connect_button.pack(side="right", padx=(10, 0))
        ttk.Button(top, text="设置 / 密钥", command=self.settings).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="断开", command=self.disconnect).pack(side="right", padx=(10, 0))
        power = ttk.Frame(top)
        power.pack(side="right", padx=18)
        ttk.Label(power, text="美元购买力  /  USD", style="Eyebrow.TLabel").pack(anchor="e")
        ttk.Label(power, textvariable=self.balance_value, style="Green.TLabel").pack(anchor="e", pady=(3, 0))

        self.symbol_card = GlassCard(outer, height=106, padding=14)
        self.symbol_card.grid(row=1, column=0, sticky="ew", pady=12)
        strip = self.symbol_card.body
        strip.columnconfigure(1, weight=1)
        symbol = ttk.Frame(strip)
        symbol.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 22))
        ttk.Label(symbol, text="股票代码  /  SYMBOL", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Entry(symbol, textvariable=self.symbol, width=10, style="Symbol.TEntry", font=("Segoe UI", 16, "bold")).pack(fill="x", pady=(6, 0))
        ttk.Label(strip, text="授权账户  /  ACCOUNT", style="Eyebrow.TLabel").grid(row=0, column=1, sticky="w")
        self.account = ttk.Combobox(strip, state="readonly", width=35)
        self.account.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.account.bind("<<ComboboxSelected>>", self.select_account)
        self.refresh_button = ttk.Button(strip, text="刷新数据", command=self.refresh)
        self.refresh_button.grid(row=1, column=2, padx=14)
        state = ttk.Frame(strip)
        state.grid(row=0, column=3, rowspan=2, sticky="w")
        ttk.Label(state, text="连接状态  /  CONNECTION", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(state, textvariable=self.connection, style="Cyan.TLabel", wraplength=260).pack(anchor="w", pady=(6, 0))

        workspace = ttk.Frame(outer, style="App.TFrame")
        workspace.grid(row=2, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.columnconfigure(1, minsize=338)
        workspace.rowconfigure(0, weight=1)
        left = ttk.Frame(workspace, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=2, minsize=170)
        left.rowconfigure(1, weight=3, minsize=230)
        self.positions_card = GlassCard(left, padding=14)
        self.positions_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        position_frame = self.positions_card.body
        heading = ttk.Frame(position_frame)
        heading.pack(fill="x", pady=(0, 7))
        copy = ttk.Frame(heading)
        copy.pack(side="left")
        ttk.Label(copy, text="ACCOUNT POSITIONS", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(copy, text="持仓", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(heading, text="服务器账户快照", style="Cyan.TLabel").pack(side="right")
        self.positions = table(position_frame, ("symbol", "name", "lastPrice", "quantity", "unitCost", "unrealizedPnl"),
                               ("股票代码", "股票名称", "当前单价", "股数", "每股成本", "未实现盈亏"), height=3)
        self.positions.column('symbol', width=90)
        self.positions.column('name', width=145)

        self.activity_card = GlassCard(left, padding=14)
        self.activity_card.grid(row=1, column=0, sticky="nsew")
        activity = self.activity_card.body
        title = ttk.Frame(activity)
        title.pack(fill="x", pady=(0, 8))
        ttk.Label(title, text="ORDER ACTIVITY", style="Eyebrow.TLabel").pack(side="left")
        ttk.Label(title, textvariable=self.event_status, style="Cyan.TLabel").pack(side="right")
        self.notebook = ttk.Notebook(activity)
        self.notebook.pack(fill="both", expand=True)
        order_frame, pending_frame = ttk.Frame(self.notebook), ttk.Frame(self.notebook)
        self.notebook.add(order_frame, text="最近订单 / 详情")
        self.notebook.add(pending_frame, text="待确认请求")
        buttons = ttk.Frame(order_frame)
        buttons.pack(fill="x", pady=(0, 4))
        ttk.Button(buttons, text="订单详情", command=self.detail).pack(side="left")
        self.replace_button = ttk.Button(buttons, text="修改限价", command=self.replace)
        self.replace_button.pack(side="left", padx=6)
        self.cancel_button = ttk.Button(buttons, text="撤单", command=self.cancel, style="Danger.TButton")
        self.cancel_button.pack(side="left")
        self.more_button = ttk.Button(buttons, text="更早订单", command=self.more)
        self.more_button.pack(side="right")
        self.order_table = table(order_frame, ("symbol", "side", "type", "qty", "price", "status", "id"),
                                 ("股票", "方向", "类型", "股数", "限价", "服务器状态", "订单编号"), height=3)
        for key, width in {'symbol':80, 'side':65, 'type':80, 'qty':60, 'price':75, 'status':215, 'id':230}.items():
            self.order_table.column(key, width=width)
        self.order_table.bind("<Double-1>", lambda _: self.detail())
        self.order_table.bind("<<TreeviewSelect>>", lambda _: self._buttons())
        self.detail_text = tk.Text(order_frame, height=2, wrap="word", state="disabled",
            background=COLORS['input'], foreground=COLORS['muted'], insertbackground=COLORS['text'],
            selectbackground="#25466d", relief="flat", borderwidth=0, padx=10, pady=7,
            font=("Microsoft YaHei UI", 9))
        ttk.Button(pending_frame, text="查询原请求结果", command=self.recover).pack(anchor="w", pady=(0, 5))
        self.pending_table = table(pending_frame, ("account", "operation", "phase", "request", "error"),
                                   ("账户引用", "操作", "本地恢复状态", "原幂等编号", "查询结果"), height=3)
        self.pending_table.column("request", width=285)

        self.trade_card = GlassCard(workspace, width=338, padding=18)
        self.trade_card.grid(row=0, column=1, sticky="nsew")
        form = self.trade_card.body
        ttk.Label(form, text="DIRECT ORDER", style="Eyebrow.TLabel").pack(anchor="w")
        title = ttk.Frame(form)
        title.pack(fill="x", pady=(3, 12))
        ttk.Label(title, text="一击下单", style="Heading.TLabel").pack(side="left")
        ttk.Label(title, text="单击直发", foreground=COLORS['red']).pack(side="right")
        footer = ttk.Frame(form)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Label(footer, textvariable=self.readiness, style="Amber.TLabel", wraplength=285).pack(fill="x", pady=(0, 12))
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self.buy_button = ttk.Button(actions, text="买入 BUY", style="Buy.TButton", command=lambda: self.trade("BUY"))
        self.sell_button = ttk.Button(actions, text="卖出 SELL", style="Sell.TButton", command=lambda: self.trade("SELL"))
        self.buy_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.sell_button.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ttk.Label(footer, text="订单状态以服务器返回为准。超时进入待确认，请查询原请求。",
                  style="Muted.TLabel", wraplength=285).pack(fill="x", pady=(12, 0))
        self.trade_fields = ScrollableFields(form)
        self.trade_fields.pack(fill="both", expand=True)
        fields = self.trade_fields.body
        segments = ttk.Frame(fields)
        segments.pack(fill="x")
        self.market_segment = ttk.Radiobutton(segments, text="市价单", variable=self.kind, value="MARKET",
                                              style="Segment.TRadiobutton", command=self._price_mode)
        self.limit_segment = ttk.Radiobutton(segments, text="限价单", variable=self.kind, value="LIMIT",
                                             style="Segment.TRadiobutton", command=self._price_mode)
        self.market_segment.pack(side="left", fill="x", expand=True)
        self.limit_segment.pack(side="left", fill="x", expand=True)
        ttk.Label(fields, text="数量                                      整股", style="Muted.TLabel").pack(anchor="w", pady=(12, 5))
        ttk.Entry(fields, textvariable=self.quantity).pack(fill="x")
        presets = ttk.Frame(fields)
        presets.pack(fill="x", pady=(6, 0))
        self.quantity_presets = []
        for number in (1, 10, 25, 100):
            button = ttk.Button(presets, text=str(number), width=4, command=lambda n=number: self.quantity.set(str(n)))
            button.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.quantity_presets.append(button)
        ttk.Label(fields, text="限价                                      USD", style="Muted.TLabel").pack(anchor="w", pady=(10, 5))
        self.price_entry = ttk.Entry(fields, textvariable=self.price)
        self.price_entry.pack(fill="x")
        preview = ttk.Frame(fields)
        preview.pack(fill="x", pady=12)
        ttk.Label(preview, text="交易标的", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview, text="交易时段", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(30, 0))
        ttk.Label(preview, textvariable=self.symbol).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(preview, text="CORE · DAY", style="Cyan.TLabel").grid(row=1, column=1, sticky="w", padx=(30, 0), pady=(3, 0))
        self.trade_fields.bind_wheel()
        ttk.Label(outer, textvariable=self.notice, style="Notice.TLabel", wraplength=1180).grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._price_mode()
        self._buttons()

    def _price_mode(self):
        self.price_entry.configure(state="normal" if self.kind.get() == "LIMIT" else "disabled")
        if hasattr(self, 'trade_fields'):
            self.root.after_idle(lambda: self.trade_fields.canvas.yview_moveto(1 if self.kind.get() == 'LIMIT' else 0))

    def _buttons(self):
        for tree in (self.positions, self.order_table, self.pending_table):
            if tree.get_children():
                tree.empty_label.place_forget()
            else:
                if tree is self.pending_table:
                    text = "没有待确认请求"
                elif not self.engine.connected:
                    text = "连接服务器后显示数据"
                elif not self.engine.selected:
                    text = "请先选择授权账户"
                else:
                    text = "暂无持仓" if tree is self.positions else "暂无订单"
                tree.empty_label.configure(text=text)
                tree.empty_label.place(relx=.5, rely=.6, anchor="center")
        ready = self.engine.connected and bool(self.engine.selected) and self.engine.selected not in self.busy_accounts
        for button in (self.buy_button, self.sell_button, self.replace_button, self.cancel_button):
            button.configure(state="normal" if ready else "disabled")
        account = next((item for item in self.engine.accounts if item['accountRef'] == self.engine.selected), {})
        if self.server_trade_gate is False or account.get('tradeEnabled') is False:
            for button in (self.buy_button, self.sell_button, self.replace_button):
                button.configure(state="disabled")
        pending = [item for item in self.pending_rows if item['account_ref'] == self.engine.selected]
        if any(item['operation'] in {'submit', 'replace'} for item in pending):
            for button in (self.buy_button, self.sell_button, self.replace_button):
                button.configure(state='disabled')
        selected = self.order_table.selection()
        order = self.rows.get(selected[0]) if selected else None
        if not order:
            self.replace_button.configure(state='disabled')
            self.cancel_button.configure(state='disabled')
        else:
            if order.get('orderType') != 'LIMIT' or order.get('status') in {'FILLED', 'CANCELLED', 'REJECTED'}:
                self.replace_button.configure(state='disabled')
            if order.get('status') in {'FILLED', 'CANCELLED', 'REJECTED'} or any(
                    item['target'] == order['clientOrderId'] for item in pending):
                self.cancel_button.configure(state='disabled')
        self.more_button.configure(state="normal" if ready and self.cursor else "disabled")

    def job(self, coroutine, *, mutation=False, connection=False, account_ref=None):
        future = self.worker.submit(coroutine)
        def complete(result):
            try:
                result.result()
            except (concurrent.futures.CancelledError, asyncio.CancelledError):
                pass
            except ApiFailure as exc:
                self.messages.put(("error", f"{exc} [{exc.code}; HTTP {exc.status or '无响应'}]", None))
            except Exception:
                # No exception repr / tracebacks: they may contain paths or key input.
                self.messages.put(("error", "操作未完成；请检查配置、接口及待确认请求。不会自动重发交易。", None))
            finally:
                self.messages.put(("mutation_done" if mutation else "connect_done" if connection else "job_done", account_ref, None))
        future.add_done_callback(complete)
        return future

    def connect(self):
        if self.busy_accounts or self.connect_busy:
            return
        try:
            config = self.config.load()
            transport = SignedTransport(config["origin"], config["client_id"], private_pem(self.keys.load()))
        except Exception:
            messagebox.showerror("连接配置", "请先保存有效的 HTTPS 地址、clientId，并生成或导入 P-256 私钥。", parent=self.root)
            return
        self._clear_account()
        self.connect_button.configure(state="disabled")
        self.connect_busy = True
        self.connection.set("正在连接；尚未完成鉴权")
        self.job(self.engine.connect(transport), connection=True)

    def disconnect(self):
        self.engine.connected = False
        self.engine.choose(None)
        self._clear_account()
        self.account.set("")
        self.account.configure(values=())
        self.connection.set("未连接")
        self.readiness.set("交易就绪：未知，以服务器为准")
        self.server_trade_gate = None
        self.job(self.engine.stop())
        self._buttons()

    def _clear_account(self):
        if self.detail_dialog is not None and self.detail_dialog.winfo_exists():
            self.detail_dialog.destroy()
        self.detail_dialog = None
        self.current_ref = None
        self.cursor = None
        self.rows.clear()
        for tree in (self.positions, self.order_table):
            tree.delete(*tree.get_children())
        self.balance.set("美元购买力：暂无数据")
        self.balance_value.set("暂无数据")
        self._detail_display("")

    def _account_display(self, accounts):
        self.account_labels = {}
        for item in accounts:
            ref = item["accountRef"]
            label = f"{str(item.get('alias', '账户'))[:40]} · {item.get('accountMask', '')} · {ref}"
            self.account_labels[label] = ref
        self.account.configure(values=tuple(self.account_labels))
        selected = self.engine.selected
        if selected != self.current_ref:
            self._clear_account()
            self.current_ref = selected
        label = next((label for label, ref in self.account_labels.items() if ref == selected), "")
        self.account.set(label)
        if not accounts:
            self.notice.set("无已授权账户，请联系管理员配置账户归属。")
        elif not selected:
            self.notice.set("多个授权账户，请明确选择一个。")
        elif self.engine.connected:
            self.job(self.engine.refresh())

    def select_account(self, _event=None):
        ref = self.account_labels.get(self.account.get())
        self._clear_account()
        self.engine.choose(ref)
        self.current_ref = ref
        self._buttons()
        self.job(self.engine.refresh())

    async def _refresh(self):
        await self.engine.refresh_accounts()
        await self.engine.refresh()

    def refresh(self):
        if self.engine.connected:
            self.job(self._refresh())
        else:
            self.notice.set("请先连接并完成签名鉴权。")

    def more(self):
        if self.cursor and self.engine.connected:
            self.job(self.engine.refresh(self.cursor, recover=False))

    def trade(self, side):
        if self.engine.selected in self.busy_accounts:
            return
        try:
            payload = order_payload(self.engine.selected, self.symbol.get(), side, self.kind.get(),
                                    self.quantity.get(), self.price.get())
            self._mutation("submit", payload)
        except (ValueError, RuntimeError):
            self.notice.set("请核对输入，确保已选择授权账户；有待确认请求时先查询原请求。")

    def selected_order(self):
        selected = self.order_table.selection()
        if not selected or selected[0] not in self.rows:
            raise ValueError("请选择订单")
        return self.rows[selected[0]]

    def detail(self):
        try:
            order = self.selected_order()
        except ValueError:
            self.notice.set("请先选择订单。")
            return
        self.job(self.engine.detail(order["clientOrderId"]))

    def replace(self):
        if self.engine.selected in self.busy_accounts:
            return
        try:
            order = self.selected_order()
            if order.get("orderType") != "LIMIT":
                raise ValueError()
            price = simpledialog.askstring("修改限价", "新限价（USD）；服务器决定是否允许修改", parent=self.root)
            if price is None:
                return
            self._mutation("replace", {"accountRef": order["accountRef"], "limitPrice": price_text(price)}, order["clientOrderId"])
        except (ValueError, RuntimeError):
            self.notice.set("请选择限价订单并填写有效价格；有待确认请求时先查询。")

    def cancel(self):
        if self.engine.selected in self.busy_accounts:
            return
        try:
            order = self.selected_order()
            self._mutation("cancel", {"accountRef": order["accountRef"]}, order["clientOrderId"])
        except (ValueError, RuntimeError):
            self.notice.set("请选择订单；该订单有待确认操作时先查询原请求。")

    def _mutation(self, operation, payload, target=""):
        if self.engine.selected in self.busy_accounts:
            return
        # Lock before persistence/enqueue so queued double clicks cannot create another intent.
        account_ref = self.engine.selected
        self.busy_accounts.add(account_ref)
        self._buttons()
        try:
            intent = self.engine.prepare(operation, payload, target)
        except Exception:
            self.busy_accounts.discard(account_ref)
            self._buttons()
            raise RuntimeError("无法保存请求或已有待确认操作") from None
        self.notice.set(f"请求已持久化并准备发送：{intent['request_id']}；尚不能认定券商接受或成交。")
        self._render_pending(self.journal.pending())
        self.job(self.engine.dispatch(intent), mutation=True, account_ref=account_ref)

    def recover(self):
        if self.engine.connected:
            self.job(self.engine.reconcile())
        else:
            self.notice.set("请使用原服务器及 clientId 连接后查询；不会重发历史请求。")

    def _render_pending(self, rows):
        self.pending_rows = rows
        self.pending_table.delete(*self.pending_table.get_children())
        operation_names = {"submit": "下单", "replace": "改单", "cancel": "撤单"}
        phases = {"PREPARED": "已持久化", "SENDING": "发送中", "UNCERTAIN": "待确认", "OPERATION_PENDING": "操作结果待确认"}
        for item in rows:
            self.pending_table.insert("", "end", values=(item["account_ref"], operation_names.get(item["operation"]),
                phases.get(item["phase"], item["phase"]), item["request_id"], item["error_code"]))

    def _detail_display(self, text):
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def _show_detail(self, data):
        if self.detail_dialog is not None and self.detail_dialog.winfo_exists():
            self.detail_dialog.destroy()
        dialog = self.detail_dialog = tk.Toplevel(self.root)
        dialog.title("订单详情")
        dialog.geometry("640x470")
        dialog.configure(background=COLORS['bg'])
        dialog.transient(self.root)
        card = GlassCard(dialog, padding=20)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(card.body, text="ORDER DETAILS", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(card.body, text=data.get('symbol', '订单详情'), style="Heading.TLabel").pack(anchor="w", pady=(4, 10))
        fields = {'accountRef':'账户引用', 'clientOrderId':'订单编号', 'requestId':'原请求编号',
                  'status':'服务器状态', 'symbol':'股票', 'side':'方向', 'orderType':'类型',
                  'quantity':'股数', 'limitPrice':'限价（USD）', 'version':'状态版本',
                  'pendingAction':'待处理操作', 'createdAt':'创建时间', 'updatedAt':'更新时间'}
        body = ttk.Frame(card.body)
        body.pack(fill='both', expand=True)
        text = tk.Text(body, background=COLORS['input'], foreground=COLORS['text'],
                       relief='flat', wrap='word', padx=12, pady=10, font=("Microsoft YaHei UI", 10))
        scroll = ttk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        lines = []
        for key, label in fields.items():
            value = data.get(key)
            if key == 'status' and value is not None:
                value = status_text(value)
            lines.append(f"{label}：{value if value is not None else '—'}")
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        dialog.after_idle(lambda: dark_caption(dialog))

    def _poll(self):
        if self.closing:
            return
        for _ in range(150):
            try:
                kind, data, generation = self.messages.get_nowait()
            except queue.Empty:
                break
            if generation is not None and generation != self.engine.generation:
                continue
            try:
                self._message(kind, data)
            except Exception:
                self.notice.set("收到不兼容的数据，未更新显示；请检查服务器接口版本。")
        self._buttons()
        self.poll_id = self.root.after(60, self._poll)

    def _message(self, kind, data):
        if kind == "connection":
            self.connection.set(data)
        elif kind == "events":
            self.event_status.set(data)
        elif kind == "readiness":
            self.server_trade_gate = data.get('effectiveTradeEnabled')
            self.readiness.set("交易就绪：" + ("服务器门禁报告开启，账户权限仍由服务器校验" if data.get("effectiveTradeEnabled") is True else
                              "服务器未就绪 / 交易开关关闭" if "effectiveTradeEnabled" in data else "未知，以服务器为准"))
        elif kind == "accounts":
            self._account_display(data)
        elif kind == "balance":
            value = data.get("usdBuyingPower")
            self.balance.set("美元购买力：" + ("暂无数据" if value is None else str(value)))
            self.balance_value.set("暂无数据" if value is None else str(value) + " USD")
        elif kind == "positions":
            self.positions.delete(*self.positions.get_children())
            for item in data.get("positions", []):
                self.positions.insert("", "end", values=tuple(item.get(k, "—") for k in
                    ("symbol", "name", "lastPrice", "quantity", "unitCost", "unrealizedPnl")))
        elif kind == "orders":
            selected = self.order_table.selection()
            previous = self.rows.get(selected[0], {}).get("clientOrderId") if selected else None
            self.order_table.delete(*self.order_table.get_children())
            self.rows.clear()
            for order in sorted(data, key=lambda o: o.get("createdAt", 0), reverse=True):
                tag = 'confirmed' if order['status'] == 'FILLED' else 'rejected' if order['status'] == 'REJECTED' else 'uncertain' if order['status'] == 'UNKNOWN' else ''
                iid = self.order_table.insert("", "end", tags=(tag,), values=(order.get("symbol", "—"), order.get("side", "—"),
                    order.get("orderType", "—"), order.get("quantity", "—"), order.get("limitPrice") or "—",
                    status_text(order["status"]), order["clientOrderId"]))
                self.rows[iid] = order
                if order["clientOrderId"] == previous:
                    self.order_table.selection_set(iid)
        elif kind == "detail":
            allowed = ("accountRef", "clientOrderId", "requestId", "status", "symbol", "side", "orderType",
                       "quantity", "limitPrice", "version", "pendingAction", "createdAt", "updatedAt")
            self._detail_display(json.dumps({k: data.get(k) for k in allowed}, ensure_ascii=False, indent=2))
            self._show_detail({k: data.get(k) for k in allowed})
        elif kind == "cursor":
            self.cursor = data
        elif kind == "pending":
            self._render_pending(data)
        elif kind == "read_error":
            if data["kind"] == "balance":
                self.balance.set("美元购买力：读取失败 / 接口未开放")
                self.balance_value.set("读取失败")
            if data["kind"] == "positions":
                self.positions.delete(*self.positions.get_children())
            if data["kind"] == "order_page":
                self.order_table.delete(*self.order_table.get_children())
                self.rows.clear()
            self.notice.set(f"{data['kind']}：{ERRORS.get(data['code'], '接口不可用')} [HTTP {data['status'] or '无响应'}]")
        elif kind == "error":
            self.notice.set(data)
            if not self.engine.connected:
                self.connection.set("未完成连接/鉴权；配置保存不代表连接成功")
        elif kind == "mutation_done":
            # Keep the latch for a short interval after a very fast response.
            self.root.after(500, self._release_mutation, data)
        elif kind == "connect_done":
            self.connect_busy = False
            self.connect_button.configure(state="normal")

    def _release_mutation(self, account_ref):
        if not self.closing:
            self.busy_accounts.discard(account_ref)
            self._buttons()

    def settings(self):
        self.disconnect()
        dialog = tk.Toplevel(self.root)
        dialog.title("连接配置与密钥")
        dialog.geometry("660x520")
        dialog.configure(background=COLORS['bg'])
        dialog.transient(self.root)
        dialog.grab_set()
        try:
            config = self.config.load()
        except RuntimeError:
            config = {"origin": "", "client_id": ""}
            self.notice.set("配置损坏；请恢复原服务器和 clientId，待确认记录仍保留。")
        origin, client_id = tk.StringVar(value=config["origin"]), tk.StringVar(value=config["client_id"])
        card = GlassCard(dialog, padding=22)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        frame = card.body
        ttk.Label(frame, text="CONNECTION SETUP", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="连接配置与密钥", style="Heading.TLabel").pack(anchor="w", pady=(3, 14))
        ttk.Label(frame, text="HTTPS 服务器地址（仅 origin）").pack(anchor="w")
        ttk.Entry(frame, textvariable=origin, width=65).pack(fill="x", pady=5)
        ttk.Label(frame, text="管理员登记返回的 clientId").pack(anchor="w")
        ttk.Entry(frame, textvariable=client_id, width=65).pack(fill="x", pady=5)
        key_label = tk.StringVar(value="私钥：已保护保存" if self.keys.path.exists() else "私钥：未配置")
        ttk.Label(frame, textvariable=key_label).pack(anchor="w", pady=5)
        key_buttons = ttk.Frame(frame)
        key_buttons.pack(fill="x", pady=5)
        def key_action(action):
            try:
                action()
                fingerprint = hashlib.sha256(self.keys.public_pem()).hexdigest()[:16]
                key_label.set(f"私钥：DPAPI 已保护保存 · 公钥指纹 {fingerprint}")
            except Exception:
                messagebox.showerror("密钥操作", "操作失败：请检查 P-256 PEM 文件、密码和 Windows 安全存储。已有私钥不会因失败被覆盖。", parent=dialog)
        def import_key():
            path = filedialog.askopenfilename(parent=dialog, title="导入 P-256 PEM 私钥", filetypes=[("PEM", "*.pem"), ("所有文件", "*")])
            if not path:
                return
            if self.keys.path.exists() and not messagebox.askokcancel("更换私钥", "更换后需管理员登记对应公钥。待确认请求保留，仍只查询原编号。", parent=dialog):
                return
            password = simpledialog.askstring("私钥密码", "加密 PEM 的密码（未加密则留空）", show="*", parent=dialog)
            if password is None:
                return
            key_action(lambda: self.keys.import_file(path, password.encode() if password else None))
        def export_public():
            path = filedialog.asksaveasfilename(parent=dialog, title="导出公钥供管理员登记", defaultextension=".pem", initialfile="public.pem")
            if path:
                from pathlib import Path
                key_action(lambda: Path(path).write_bytes(self.keys.public_pem()))
        ttk.Button(key_buttons, text="生成 P-256 密钥", command=lambda: key_action(self.keys.generate)).pack(side="left", padx=3)
        ttk.Button(key_buttons, text="导入私钥", command=import_key).pack(side="left", padx=3)
        ttk.Button(key_buttons, text="导出公钥", command=export_public).pack(side="left", padx=3)
        ttk.Label(frame, text="客户端不保存券商凭据。导出的仅为公钥；私钥不在界面展示。", wraplength=610).pack(anchor="w", pady=8)
        def save():
            try:
                self.config.save(origin.get().strip(), client_id.get().strip())
            except Exception:
                messagebox.showerror("配置保存", "需要 HTTPS origin 和 UUID clientId。有待确认请求时不能改变服务器或 clientId。", parent=dialog)
                return
            self.connection.set("配置已保存 · 未连接，尚未鉴权")
            self.notice.set("请点击连接服务器，完成签名鉴权。")
            dialog.destroy()
        ttk.Button(frame, text="保存配置（不会自动连接）", command=save, style="Primary.TButton").pack(anchor="e")
        dialog.after_idle(lambda: dark_caption(dialog))

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.root.after_cancel(self.poll_id)
        future = self.worker.submit(self.engine.stop())
        with __import__('contextlib').suppress(Exception):
            future.result(timeout=5)
        self.worker.close()
        self.root.destroy()
