"""Verify code/config has no reference to the three source projects."""
from pathlib import Path
import ast
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "runtime", "build", "__pycache__", ".pytest_cache", "obj", "Release", "deployment-tools", "windows-client"}


def verify():
    errors = []
    source_roots = [r"E:\python", "E:/python"]
    count = 0
    for path in ROOT.rglob("*"):
        if any(part in EXCLUDED for part in path.relative_to(ROOT).parts):
            continue
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            errors.append(f"link: {path.relative_to(ROOT)}")
        if not path.is_file() or path.suffix not in {".py", ".ps1", ".cs", ".csproj", ".sh", ".json", ".toml", ".ini", ".service", ".in", ".txt"}:
            continue
        count += 1
        text = path.read_text(encoding="utf-8-sig")
        if path.name not in {"source-manifest.json", "verify_independence.py"} and any(root.lower() in text.lower() for root in source_roots):
            errors.append(f"old project reference: {path.relative_to(ROOT)}")
        if path.suffix == ".py":
            ast.parse(text, filename=str(path))
            # The isolated restore verifier intentionally loads the installed release.
            if path.relative_to(ROOT).as_posix() not in {"tools/verify_independence.py", "ops/verify_restore.py", "ops/db_helpers.py", "tools/live_db_acceptance/acceptance.py"} and ("sys.path.insert" in text or "sys.path.append" in text):
                errors.append(f"path injection: {path.relative_to(ROOT)}")
    cfg = ROOT / ".venv/pyvenv.cfg"
    if cfg.exists() and "include-system-site-packages = false" not in cfg.read_text():
        errors.append("virtual environment inherits system packages")
    report = {"checkedFiles": count, "errors": errors}
    print(json.dumps(report, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(verify())
