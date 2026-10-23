import ast
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
errors = []
count = 0
for folder in ('finfusion_client', 'client_sdk'):
    for path in (root / folder).rglob('*.py'):
        count += 1
        if path.is_symlink():
            errors.append(f'link:{path.relative_to(root)}')
        text = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(text)
        if 'sys.path.insert' in text or 'sys.path.append' in text:
            errors.append(f'path injection:{path.relative_to(root)}')
        for node in ast.walk(tree):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            if any(name.split('.')[0] in {'webull', 'tigeropen', 'longbridge', 'longport', 'fast_order', 'fast_order_server', 'finfusion'} for name in names):
                errors.append(f'external/broker import:{path.relative_to(root)}')
        if 'E:\\python' in text or 'E:\\Finfusion API' in text or '/home/finfusion_tech' in text:
            errors.append(f'external project path:{path.relative_to(root)}')
manifest = root / 'docs' / 'SDK-SOURCE.json'
if manifest.exists():
    expected = json.loads(manifest.read_text(encoding='utf-8'))['sha256']
    for name, digest in expected.items():
        if hashlib.sha256((root / 'client_sdk' / name).read_bytes()).hexdigest() != digest:
            errors.append(f'SDK differs:{name}')
venv = root / '.venv' / 'pyvenv.cfg'
if venv.exists() and 'include-system-site-packages = false' not in venv.read_text():
    errors.append('venv inherits external system packages')
print(json.dumps({'checkedPythonFiles': count, 'errors': errors}, ensure_ascii=False))
raise SystemExit(bool(errors))
