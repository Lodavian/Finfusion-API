"""Run the real WebView2 page/bridge against LIVE reads, reporting booleans only."""
import asyncio,json,tempfile,time
from pathlib import Path
import webview
from finfusion_client.desktop import Controller,Bridge
from finfusion_client.security import data_directory
from finfusion_client.storage import Journal

report={'mode':'LIVE_READ_ONLY','orderMutations':0,'checks':[]}
failed=[]
with tempfile.TemporaryDirectory(prefix='Finfusion-live-ui-',ignore_cleanup_errors=True) as temporary:
    controller=Controller(data_directory(),Journal(Path(temporary)/'requests.sqlite3'))
    bridge=Bridge(controller)
    window=webview.create_window('Finfusion Client · 正式只读验收',str(Path(__file__).resolve().parents[1]/'web/index.html'),js_api=bridge,width=1240,height=900,min_size=(1000,650),background_color='#060b14')
    controller.window=window
    def wait(predicate,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.2)
        raise TimeoutError('UI acceptance condition timed out')
    def action(operation,data):
        result=bridge.action(operation,data)
        assert 'error' not in result,'Read-only bridge action failed'
        return result
    def test():
        try:
            wait(lambda:window.evaluate_js("typeof window.pywebview !== 'undefined' && !!document.getElementById('connectButton').onclick"))
            state=action('connect',{})
            accounts=state['accounts'];assert len(accounts)==2
            for index,account in enumerate(accounts):
                ref=account['accountRef'];state=action('account',{'accountRef':ref})
                assert state['balance']['accountRef']==ref and state['positions']['accountRef']==ref
                assert state['context']['environment']=='LIVE' and not state['context']['tradeEnabled']
                expected_cash=state['balance']['usdCashBalance']
                expected_power=state['balance']['usdBuyingPower']
                wait(lambda:window.evaluate_js("document.getElementById('accountSelect').value")==ref)
                wait(lambda:window.evaluate_js("document.getElementById('usdCashBalance').textContent")==('暂无数据' if expected_cash is None else str(expected_cash)))
                wait(lambda:window.evaluate_js("document.getElementById('buyingPower').textContent")==('暂无数据' if expected_power is None else str(expected_power)))
                assert window.evaluate_js("document.getElementById('buyButton').disabled && document.getElementById('sellButton').disabled")
                symbols=action('search',{'q':'AAPL'});assert any(s['symbol']=='AAPL' for s in symbols['symbols'])
                action('symbol',{'symbol':'AAPL'})
                wait(lambda:bridge.get_state().get('market',{}).get('lastPrice') is not None)
                market=bridge.get_state()['market'];assert market['accountRef']==ref and market['symbol']=='AAPL'
                wait(lambda:window.evaluate_js("document.getElementById('lastPrice').textContent")==market['lastPrice'])
                assert window.evaluate_js("document.getElementById('modeBadge').textContent === 'LIVE'")
                assert window.evaluate_js("document.getElementById('freshnessText').textContent !== '无有效时间戳'")
                if not state['positions']['positions']:
                    assert window.evaluate_js("document.getElementById('positionsBody').textContent.includes('无美元股票')")
                report['checks'].append({'accountIndex':index+1,'cashDisplayMatchesBroker':True,'buyingPowerSeparate':True,'positionsDisplayMatches':True,'AAPLPriceDisplayed':True,'timestampDisplayed':True,'tradeButtonsDisabled':True,'marketStatus':market['status']})
            action('disconnect',{})
            wait(lambda:window.evaluate_js("document.getElementById('lastPrice').textContent === '—' && document.getElementById('usdCashBalance').textContent === '暂无数据'"))
            state=action('connect',{});action('account',{'accountRef':accounts[0]['accountRef']})
            action('symbol',{'symbol':'MSFT'})
            wait(lambda:bridge.get_state().get('market',{}).get('symbol')=='MSFT' and bridge.get_state().get('market',{}).get('lastPrice') is not None)
            report['reconnectAndChangeSymbol']=True
            print('PASS: real WebView2 rendered both LIVE account cash/positions/AAPL prices, timestamps and disabled trade buttons; disconnect/reconnect/MSFT verified.')
        except Exception as exc:
            failed.append(type(exc).__name__);report['failed']=type(exc).__name__
            print('WebView acceptance failed: '+type(exc).__name__)
        finally:
            (Path(__file__).resolve().parents[1]/'build/live-webview-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            window.evaluate_js("window.dispatchEvent(new Event('finfusion-closing'))")
            wait(lambda:window.evaluate_js("document.body.dataset.polling !== 'true'"),timeout=3)
            window.destroy()
    try:webview.start(test,gui='edgechromium',debug=False,private_mode=True,storage_path=str(Path(temporary)/'WebView2'))
    finally:controller.close()
if failed:raise SystemExit(1)
