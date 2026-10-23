"""Build EXE metadata from the client version, without external project paths."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = re.search(r'__version__ = "([^"]+)"', (root/'finfusion_client/__init__.py').read_text())[1]
    major, minor, patch, rc = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?', version).groups()
    numeric = tuple(map(int, (major, minor, patch, rc or '0')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f'''VSVersionInfo(ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, mask=0x3f, flags=0x2, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), kids=[StringFileInfo([StringTable('080404b0', [StringStruct('CompanyName','Finfusion'), StringStruct('FileDescription','Finfusion Client 1.0'), StringStruct('FileVersion',{version!r}), StringStruct('InternalName','FinfusionClient'), StringStruct('OriginalFilename','FinfusionClient.exe'), StringStruct('ProductName','Finfusion Client'), StringStruct('ProductVersion',{version!r})])]), VarFileInfo([VarStruct('Translation',[2052,1200])])])''', encoding='utf-8')
    print(version)


if __name__ == '__main__': main()
