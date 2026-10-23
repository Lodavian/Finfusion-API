import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
records=[]
for dist in metadata.distributions():
    name=dist.metadata['Name'];version=dist.version
    licenses=[]
    for f in dist.files or []:
        if any(word in f.name.lower() for word in ('license','copying')) and f.suffix.lower() in ('','.txt','.md','.rst'):
            file=Path(dist.locate_file(f))
            if file.is_file():
                target=root/'LICENSES'/name/f.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(file.read_bytes());licenses.append(str(target.relative_to(root)))
    records.append({'name':name,'version':version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''),'files':licenses})
(root/'docs/DEPENDENCIES.json').write_text(json.dumps(sorted(records,key=lambda d:d['name'].lower()),ensure_ascii=False,indent=2),encoding='utf-8')
resources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('assets','web') for p in (root/folder).rglob('*') if p.is_file()}
(root/'docs/UI-SOURCE.json').write_text(json.dumps({'repository':'https://github.com/Lodavian/-.git','commit':'680b5a8f2ce1a5c5830fc9e59ba4bf97735010dd','note':'Original CSS prefix, layout, icon reused; JavaScript replaced. No broker backend copied.','sha256':resources},ensure_ascii=False,indent=2),encoding='utf-8')
