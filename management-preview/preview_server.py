"""Loopback-only, read-only UI preview. Never forwards to a production API."""
import argparse
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1] / 'server_admin'
STATE = {
    'control': {'global_trade_enabled': False, 'updated_at': None},
    'users': [
        {'user_id': 'demo/research', 'casdoor_name': 'research-team', 'enabled': True, 'trade_enabled': False},
        {'user_id': 'demo/operations', 'casdoor_name': 'operations', 'enabled': True, 'trade_enabled': False},
        {'user_id': 'demo/new-user', 'casdoor_name': 'new-user', 'enabled': False, 'trade_enabled': False},
    ],
    'clients': [
        {'client_id': 'demo-client-windows', 'user_id': 'demo/research', 'label': 'Windows 工作站', 'enabled': True, 'can_read': True, 'can_trade': False, 'can_cancel': False},
        {'client_id': 'demo-client-monitor', 'user_id': 'demo/operations', 'label': '只读监控终端', 'enabled': True, 'can_read': True, 'can_trade': False, 'can_cancel': False},
        {'client_id': 'demo-client-new', 'user_id': 'demo/new-user', 'label': '待批准客户端', 'enabled': False, 'can_read': True, 'can_trade': False, 'can_cancel': False},
    ],
    'accounts': [
        {'account_ref': 'demo-account-01', 'account_mask': '示例 · ****0124', 'alias': '研究账户', 'user_id': 'demo/research', 'enabled': True, 'trade_enabled': False},
        {'account_ref': 'demo-account-02', 'account_mask': '示例 · ****0836', 'alias': '观察账户', 'user_id': 'demo/operations', 'enabled': True, 'trade_enabled': False},
        {'account_ref': 'demo-account-03', 'account_mask': '示例 · ****0921', 'alias': '待分配账户', 'user_id': '', 'enabled': True, 'trade_enabled': False},
    ],
}

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
            return self.json({'error': {'message': 'Invalid local host'}}, 403)
        path = unquote(urlsplit(self.path).path)
        if path == '/admin/config': return self.json({'preview': True})
        if path == '/admin/v1/state': return self.json(STATE)
        if path == '/preview-health': return self.json({'application': 'finfusion-admin-readonly-preview', 'root': str(ROOT), 'preview': True})
        if path in {'/', '/admin', '/admin/'}:
            path = '/admin/index.html'
        if not path.startswith('/admin/'):
            return self.json({'error': {'message': 'Preview route unavailable'}}, 404)
        relative = path[len('/admin/'):]
        resolved = (ROOT / relative).resolve()
        if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
            return self.json({'error': {'message': 'Not found'}}, 404)
        self.path = '/' + relative
        super().do_GET()

    def do_HEAD(self):
        self.send_error(405, 'Preview supports GET only')

    def reject_mutation(self):
        self.json({'error': {'message': 'Read-only UI preview; no mutation route exists'}}, 405)

    do_POST = do_PATCH = do_PUT = do_DELETE = reject_mutation

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    factory = lambda *a, **kw: Handler(*a, directory=str(ROOT), **kw)
    print(f'Finfusion read-only UI preview: http://127.0.0.1:{args.port}/admin/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), factory).serve_forever()
