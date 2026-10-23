"""Offline, own-window comparison using the supplied FastOrder reference."""
import argparse
import tempfile
import time
from pathlib import Path
import webview
from finfusion_client.capture import capture_own_window
from finfusion_client.desktop import Controller, Bridge
from finfusion_client.storage import Journal


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--reference',action='store_true');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='Finfusion-Visual-',ignore_cleanup_errors=True) as temp:
        folder=Path(temp); controller=Controller(folder,Journal(folder/'requests.sqlite3'))
        controller.engine.accounts=[{'accountRef':'QA-account','alias':'模拟账户','accountMask':'***1234'}];controller.engine.choose('QA-account')
        controller.state.update(connection='模拟数据 · 未连接真实服务器', accounts=controller.engine.accounts,context={'environment':'SANDBOX','tradeEnabled':False,'riskRules':{'maxOrderQty':1000,'maxOrderValue':'25000'}},balance={'usdBuyingPower':'10000.00'},market={'accountRef':'QA-account','symbol':'AAPL','version':1,'status':'READY','lastPrice':'100.25','change':'1.25','changePercent':'1.26','open':'99.00','high':'102.00','low':'98.00','volume':'123456','asOf':1791360000,'bid':{'price':'100.24','size':'5'},'ask':{'price':'100.26','size':'8'},'spread':'0.02'},trades={'trades':[{'time':'10:00:01','price':'100.25','size':'1','side':'BUY'}]},positions={'positions':[{'symbol':'AAPL','name':'Apple','lastPrice':'100.25','quantity':'3','unitCost':'95','unrealizedPnl':'15.75'}]})
        fixture=dict(controller.state)
        index=root/'tools/reference/index.html' if args.reference else root/'web/index.html'
        window=webview.create_window('UI 对比 · 模拟数据',str(index),js_api=None if args.reference else Bridge(controller),width=1240,height=900,background_color='#060b14');controller.window=window
        def take():
            try:
                window.events.loaded.wait(30);time.sleep(1)
                if not args.reference:
                    controller.state.update(fixture)
                time.sleep(1)
                if args.reference:
                    window.evaluate_js("""(()=>{const data={statusText:'模拟数据 · 未连接真实服务器',statusDetail:'订单事件未连接',accountText:'QA-account',headerUsdBuyingPower:'10000.00',symbolName:'AAPL',marketState:'实时',lastPrice:'100.25',priceChange:'1.25 (1.26%)',openPrice:'99.00',highPrice:'102.00',lowPrice:'98.00',volume:'123456',spread:'0.02',freshnessText:'1791360000',riskLimits:'1000 股 / 25000 USD'};for(const [id,text] of Object.entries(data)){const e=document.getElementById(id);if(e)e.textContent=text;}for(const [id,v] of [['bidBook',['买一','100.24','5']],['askBook',['卖一','100.26','8']],['tape',['10:00:01','100.25','1','BUY']]]){const div=document.createElement('div');div.className=id==='tape'?'tape-row':'book-row';v.forEach(t=>{const span=document.createElement('span');span.textContent=t;div.append(span);});document.getElementById(id).append(div);}})()""")
                if args.reference:
                    window.evaluate_js("document.getElementById('priceChange').className='price-change positive';document.getElementById('freshnessBar').dataset.level='20';document.getElementById('feedBadge').textContent='READY';document.getElementById('freshnessText').textContent='16:00:00'")
                time.sleep(0.6)
                import json
                from System import Action
                original_width=window.evaluate_js('innerWidth')
                window.native.Invoke(Action(lambda:setattr(window.native.webview,'ZoomFactor',1.25)))
                time.sleep(.3)
                zoom_ok=window.evaluate_js('innerWidth') < original_width
                window.native.Invoke(Action(lambda:setattr(window.native.webview,'ZoomFactor',1.0)))
                window.evaluate_js('scrollTo(0,document.body.scrollHeight)')
                scroll_ok=window.evaluate_js('scrollY > 0')
                window.evaluate_js('scrollTo(0,0)');time.sleep(.3)
                args.output.with_suffix('.json').write_text(json.dumps({'reference':args.reference,'price':window.evaluate_js("document.getElementById('lastPrice').textContent"),'viewport':window.evaluate_js('({width:innerWidth,height:innerHeight})'),'zoom125Responsive':zoom_ok,'scrollWorks':scroll_ok},ensure_ascii=False),encoding='utf-8')
                capture_own_window(window.native.Handle.ToInt64(),args.output)
            finally:window.destroy()
        webview.start(take,gui='edgechromium',debug=False,storage_path=str(folder/'WebView2'),private_mode=False)
        controller.close()

if __name__=='__main__':main()
