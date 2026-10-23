"""Read-only HTTPS integration probe. Never submits or changes an order.

Run from the project root: .venv/Scripts/python.exe -m tools.check_readonly_connection
Uses the current user's existing DPAPI key; reports schemas/counts, never secrets.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import quote

from finfusion_client.security import KeyStore, data_directory, private_pem
from finfusion_client.transport import SignedTransport, ApiFailure
from finfusion_client.engine import order_from
from finfusion_client.desktop import Controller
from finfusion_client.storage import Journal


async def probe():
    directory = data_directory()
    config = json.loads((directory / 'settings.json').read_text(encoding='utf-8'))
    transport = SignedTransport(config['origin'], config['client_id'],
                                private_pem(KeyStore(directory).load()), timeout=15)
    report = {'time': datetime.now(timezone.utc).isoformat(), 'origin': config['origin'],
              'mode': 'READ_ONLY', 'mutations': 0, 'checks': []}

    async def read(label, path, query=None, validate=None, allowed_statuses=()):
        safe_path = path
        if path.startswith('/v1/accounts/'):
            safe_path = '/v1/accounts/{accountRef}/' + path.rsplit('/', 1)[-1]
        check = {'check': label, 'path': safe_path}
        try:
            data = await transport.request('GET', path, query=query, allowed_statuses=allowed_statuses)
            check['result'] = 'PASS'
            check['fields'] = sorted(data)
            if validate:
                check.update(validate(data))
            report['checks'].append(check)
            return data
        except ApiFailure as exc:
            check.update(result='FAIL', code=exc.code, httpStatus=exc.status)
        except (ValueError, KeyError, TypeError):
            check.update(result='FAIL', code='SCHEMA_MISMATCH')
        report['checks'].append(check)
        return None

    async def stream(label, path, query=None):
        check = {'check': label, 'path': path}
        iterator = transport.stream(path, query=query)
        try:
            event = await asyncio.wait_for(anext(iterator), timeout=10)
            check.update(result='PASS', firstEventType=event.get('type'), fields=sorted(event))
        except ApiFailure as exc:
            check.update(result='FAIL', code=exc.code, httpStatus=exc.status)
        except (asyncio.TimeoutError, StopAsyncIteration):
            check.update(result='INCONCLUSIVE', code='NO_INITIAL_EVENT')
        finally:
            await iterator.aclose()
        report['checks'].append(check)

    try:
        await read('health', '/livez')
        await read('server_version', '/v1/info', validate=lambda d: {'version':d.get('version'),
            'deploymentMode':d.get('deploymentMode'), 'operationalStatus':d.get('operations',{}).get('status')})
        await read('readiness', '/readyz', allowed_statuses=(503,), validate=lambda d: {
            'readiness': {k: v for k, v in d.items() if isinstance(v, bool)}})
        accounts = await read('signed_accounts', '/v1/accounts', validate=lambda d: {'count': len(d['accounts'])})
        if accounts:
            for account in accounts.get('accounts', []):
                ref = account['accountRef']
                prefix = hashlib.sha256(ref.encode()).hexdigest()[:8]
                base = '/v1/accounts/' + quote(ref, safe='')
                await read(prefix + '_positions', base + '/positions', validate=lambda d: {'count': len(d['positions'])})
                await read(prefix + '_balance', base + '/balance', validate=lambda d: {'buyingPowerAvailable': d.get('usdBuyingPower') is not None})
                await read(prefix + '_ui_context', base + '/ui-context', validate=lambda d: {
                    'environment': d.get('environment'), 'tradeEnabled': d.get('tradeEnabled')})
                orders = await read(prefix + '_orders', '/v1/orders', {'accountRef': ref, 'limit': 50},
                                    lambda d: {'count': len(d['orders'])})
                if orders:
                    for order in orders['orders'][:1]:
                        order_from(order, ref)
                        await read(prefix + '_detail', '/v1/orders/' + quote(order['clientOrderId'], safe=''),
                                   validate=lambda d: {'status': order_from(d, ref)['status']})
                query = {'accountRef': ref, 'symbol': 'AAPL'}
                await read(prefix + '_symbols', '/v1/market/symbols', {'accountRef': ref, 'q': 'AAPL'})
                await read(prefix + '_snapshot', '/v1/market/snapshot', query,
                           lambda d: {'status': d.get('status'), 'priceAvailable': d.get('lastPrice') is not None})
                await read(prefix + '_trades', '/v1/market/trades', query)
                await stream(prefix + '_market_events', '/v1/market/events', query)
            await stream('order_events', '/v1/events')
            # Exercise the actual desktop controller as well as raw transport.
            # A disposable journal ensures the user's pending records are untouched.
            with tempfile.TemporaryDirectory(prefix='Finfusion-readonly-') as temporary:
                controller = Controller(directory, Journal(Path(temporary) / 'requests.sqlite'))
                try:
                    await asyncio.wrap_future(controller.worker.submit(controller.action('connect', {})))
                    for account in accounts.get('accounts', []):
                        state = await asyncio.wrap_future(controller.worker.submit(
                            controller.action('account', {'accountRef': account['accountRef']})))
                        prefix = hashlib.sha256(account['accountRef'].encode()).hexdigest()[:8]
                        report['checks'].append({'check': prefix + '_desktop_core', 'result': 'PASS' if
                            state['connected'] and state['positions'].get('accountRef') == account['accountRef'] and
                            state['balance'].get('accountRef') == account['accountRef'] else 'FAIL',
                            'authenticated': state['connected'], 'contextStatus': state['context_status'],
                            'positionCount': len(state['positions'].get('positions', [])),
                            'orderCount': len(state['orders']),
                            'buyingPowerAvailable': state['balance'].get('usdBuyingPower') is not None})
                finally:
                    controller.close()
    finally:
        await transport.close()
        output = Path('build/readonly-integration.json')
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Account references are not included in terminal output.
        for check in report['checks']:
            print(check['check'], check['result'], check.get('httpStatus', ''), check.get('code', ''))
        print('Report:', output.resolve())


if __name__ == '__main__':
    asyncio.run(probe())
