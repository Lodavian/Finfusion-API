import asyncio
import time
import tkinter as tk

from finfusion_client.storage import Journal
from finfusion_client.ui import ClientWindow
from finfusion_client.theme import COLORS


def test_real_widgets_duplicate_click_and_nonblocking_worker(tmp_path):
    root = tk.Tk()
    app = ClientWindow(root, tmp_path, Journal(tmp_path / 'gui.db'))
    root.update()
    try:
        assert str(app.buy_button['state']) == 'disabled'
        app.engine.accounts = [{'accountRef': 'A'}, {'accountRef': 'B'}]
        app.engine.choose('A')
        app.engine.connected = True
        class FakeTransport:
            origin, client_id = 'https://example.com', '00000000-0000-4000-8000-000000000001'
        app.engine.transport = FakeTransport()
        captured = []
        original_job = app.job
        def capture(coroutine, **kwargs):
            captured.append(kwargs)
            coroutine.close()
        app.job = capture
        app._buttons()
        app.buy_button.invoke()
        app.buy_button.invoke()
        assert len(captured) == 1 and len(app.journal.pending()) == 1
        app.engine.choose('B')
        app._buttons()
        assert str(app.buy_button['state']) == 'normal'
        app.buy_button.invoke()
        assert len(captured) == 2 and len(app.journal.pending()) == 2
        app.job = original_job
        app.engine.transport = None
        before = time.monotonic()
        future = app.job(asyncio.sleep(.3))
        ticks = 0
        while time.monotonic() - before < .15:
            root.update()
            ticks += 1
            time.sleep(.005)
        assert ticks > 10 and not future.done()
        app._message('readiness', {'effectiveTradeEnabled': False})
        assert '未就绪' in app.readiness.get()
        app._message('balance', {'usdBuyingPower': None})
        assert '暂无数据' in app.balance.get()
        app.messages.put(('positions', {'positions': [{'symbol': 'OLD'}]}, app.engine.generation - 1))
        app._poll()
        assert not app.positions.get_children()
    finally:
        app.close()


def test_dark_layout_controls_and_detail_isolation(tmp_path):
    root = tk.Tk()
    app = ClientWindow(root, tmp_path, Journal(tmp_path / 'layout.db'))
    try:
        root.geometry('1000x650')
        root.update()
        assert root.cget('background') == COLORS['bg']
        assert app.style.lookup('Buy.TButton', 'background') == '#1c5748'
        assert app.style.lookup('Sell.TButton', 'background') == '#632a40'
        for button in (app.buy_button, app.sell_button):
            assert button.winfo_ismapped()
            assert button.winfo_rooty() + button.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert app.trade_card.winfo_x() > app.positions_card.winfo_x()
        app.quantity_presets[2].invoke()
        assert app.quantity.get() == '25'
        assert not app.journal.pending()
        app.limit_segment.invoke()
        root.update()
        assert app.kind.get() == 'LIMIT' and str(app.price_entry['state']) == 'normal'
        assert app.trade_fields.canvas.yview()[1] > .99
        app.market_segment.invoke()
        root.update()
        assert str(app.price_entry['state']) == 'disabled'
        app._message('detail', {'symbol':'AAPL', 'status':'ACKNOWLEDGED', 'accountRef':'A', 'privateKey':'never-display'})
        root.update()
        assert app.detail_dialog.winfo_viewable()
        texts = []
        def inspect(widget):
            if isinstance(widget, tk.Text):
                texts.append(widget.get('1.0','end'))
            for child in widget.winfo_children():
                inspect(child)
        inspect(app.detail_dialog)
        assert 'ACKNOWLEDGED' in ''.join(texts) and 'never-display' not in ''.join(texts)
        app._clear_account()
        assert app.detail_dialog is None
        app.settings()
        root.update()
        dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        buttons = []
        def find_buttons(widget):
            if widget.winfo_class() == 'TButton':
                buttons.append(widget)
            for child in widget.winfo_children():
                find_buttons(child)
        find_buttons(dialog)
        save = next(w for w in buttons if w.cget('text').startswith('保存配置'))
        assert save.winfo_ismapped()
        assert save.winfo_rooty() + save.winfo_height() < dialog.winfo_rooty() + dialog.winfo_height()
    finally:
        app.close()
