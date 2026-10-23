"""PyInstaller entrypoint; all application imports are inside this project."""
from finfusion_client.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main())
