import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from .security import data_directory, restrict_directory, InstanceLock, private_pem
from .runtime import prerequisites, AppMutex, message
from .storage import Journal
from .desktop import Controller, Bridge
from . import __version__, DISPLAY_NAME

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--smoke-result', type=Path)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    runtime = prerequisites()
    if not runtime['webview2'] or runtime['netRelease'] < 528040:
        message('需要 Microsoft Edge WebView2 Evergreen Runtime 和 .NET Framework 4.8。请使用附带安装器安装运行时。')
        return 1
    temporary = tempfile.TemporaryDirectory(prefix='Finfusion-WebView-',ignore_cleanup_errors=True) if args.smoke_test else None
    directory = Path(temporary.name) if temporary else data_directory()
    restrict_directory(directory)
    lock, mutex = InstanceLock(directory), AppMutex()
    if not mutex.acquire() or not lock.acquire():
        message('当前 Windows 用户已有 Finfusion Client 实例运行。')
        mutex.release()
        return 2
    controller = None
    smoke_failed = []
    try:
        import webview
        controller = Controller(directory, Journal(directory / 'requests.sqlite3'))
        assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        window = webview.create_window(DISPLAY_NAME + ' · ' + __version__, str(assets / 'web/index.html'), js_api=Bridge(controller), width=1240, height=900, min_size=(1000,650), background_color='#060b14')
        controller.window = window
        def stop_page_polling():
            try:
                window.evaluate_js("window.dispatchEvent(new Event('finfusion-closing'))")
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline and window.evaluate_js("document.body.dataset.polling === 'true'"):
                    time.sleep(0.02)
            except Exception:
                pass
        close_state = {'started': False, 'ready': False}
        def before_close():
            if close_state['ready']:
                return True
            if not close_state['started']:
                close_state['started'] = True
                def finish_close():
                    try:
                        stop_page_polling()
                    finally:
                        close_state['ready'] = True
                        window.destroy()
                threading.Thread(target=finish_close, daemon=True).start()
            # The native closing callback runs on the UI thread; let it return
            # before waiting for JavaScript so the WebView can drain callbacks.
            return False
        window.events.closing += before_close
        allowed = {'url': None}
        def protect():
            native = window.native
            def navigating(_sender, event):
                target = str(event.Uri).split('#')[0]
                if allowed['url'] is None:
                    allowed['url'] = target
                if target != allowed['url']:
                    event.Cancel = True
            native.webview.NavigationStarting += navigating
            def initialized(_sender, _event):
                def new_window(_s, event):
                    event.Handled = True
                native.webview.CoreWebView2.NewWindowRequested += new_window
            native.webview.CoreWebView2InitializationCompleted += initialized
        window.events.before_show += protect
        def smoke():
            try:
                window.events.loaded.wait(30)
                time.sleep(2)
                from .transport import SignedTransport
                result = dict(runtime)
                result['guiOpened'] = window.events.loaded.is_set()
                result['tradeDisabledBeforeAuth'] = window.evaluate_js("document.getElementById('buyButton').disabled")
                result['bridgeLoaded'] = window.evaluate_js("typeof window.pywebview.api.action === 'function'")
                result['noNetworkConnection'] = not controller.engine.connected
                result['viewport'] = window.evaluate_js("({width:innerWidth,height:innerHeight})")
                result['bridgeMethods'] = window.evaluate_js("Object.keys(pywebview.api).sort()")
                from System import Action
                window.native.Invoke(Action(lambda: result.update(devToolsDisabled=not window.native.webview.CoreWebView2.Settings.AreDevToolsEnabled)))
                result['originalButtonEffect'] = window.evaluate_js("getComputedStyle(document.getElementById('connectButton')).boxShadow !== 'none'")
                window.evaluate_js("document.querySelector('[data-order-type=LIMIT]').click(); document.querySelectorAll('[data-qty]')[3].click()")
                result['limitAndPreset'] = window.evaluate_js("!document.getElementById('limitField').classList.contains('hidden') && document.getElementById('quantityInput').value === '100'")
                window.evaluate_js("document.getElementById('popoverApiButton').click()")
                result['settingsModal'] = window.evaluate_js("!document.getElementById('settingsDialog').hidden && document.activeElement.id === 'originInput'")
                window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
                result['keyboardEscape'] = window.evaluate_js("document.getElementById('settingsDialog').hidden")
                original_action = controller.action
                async def delayed(operation,data):
                    import asyncio
                    await asyncio.sleep(0.5)
                    return await controller.snapshot()
                controller.action = delayed
                window.evaluate_js("document.body.dataset.responsive='waiting'; pywebview.api.action('refresh',{}); setTimeout(()=>document.body.dataset.responsive='yes',30)")
                time.sleep(0.1)
                result['responsiveDuringBridgeCall'] = window.evaluate_js("document.body.dataset.responsive === 'yes'")
                time.sleep(0.6)
                controller.action = original_action
                original_url = window.evaluate_js('location.href')
                window.evaluate_js("location.href = 'https://example.invalid/'")
                time.sleep(0.2)
                result['externalNavigationBlocked'] = window.evaluate_js('location.href') == original_url
                window.evaluate_js("document.querySelector('[data-order-type=MARKET]').click(); document.querySelectorAll('[data-qty]')[0].click()")
                controller.keys.generate()
                key = controller.keys.load()
                signer = SignedTransport('https://example.invalid', '00000000-0000-4000-8000-000000000001', private_pem(key))
                result['dpapiRoundTrip'] = key.curve.name == 'secp256r1'
                result['privateFileEncrypted'] = b'PRIVATE KEY' not in controller.keys.path.read_bytes()
                result['signatureProduced'] = bool(signer.sdk.headers('GET','/v1/accounts')['X-Client-Signature'])
                if args.screenshot:
                    from .capture import capture_own_window
                    capture_own_window(window.native.Handle.ToInt64(), args.screenshot)
                if args.smoke_result:
                    args.smoke_result.parent.mkdir(parents=True, exist_ok=True)
                    args.smoke_result.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:
                smoke_failed.append(type(exc).__name__)
                if args.smoke_result:
                    args.smoke_result.write_text(json.dumps({'smokeFailed': type(exc).__name__}), encoding='utf-8')
            finally:
                window.destroy()
        webview.start(smoke if args.smoke_test else None,gui='edgechromium',debug=False,private_mode=False,storage_path=str(directory/'WebView2'),icon=str(assets/'assets/FinfusionClient.ico'))
        return 1 if smoke_failed else 0
    except Exception:
        message('无法初始化 WebView2 或安全存储。请检查运行时和用户目录权限。')
        return 1
    finally:
        if controller:
            controller.close()
        lock.release(); mutex.release()
        if temporary:
            temporary.cleanup()

if __name__ == '__main__':
    sys.exit(main())
