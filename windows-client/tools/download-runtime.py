import concurrent.futures
import urllib.request
from pathlib import Path
url='https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/18c66e75-0385-4019-be3f-3f4a2bb867d5/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
root=Path(r'D:\Finfusion Client\packaging\vendor')
size=212358352
step=8*1024*1024

def download(i):
    start=i*step;end=min(size-1,start+step-1)
    path=root/f'runtime-part-{i:02d}'
    if path.exists() and path.stat().st_size==end-start+1:
        return path
    for attempt in range(8):
        try:
            req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(req,timeout=120) as response:
                if response.status!=206: raise RuntimeError('Expected ranged download')
                data=response.read()
            if len(data)!=end-start+1: raise RuntimeError('Incomplete part')
            path.write_bytes(data)
            print('Part',i,flush=True)
            return path
        except Exception:
            if attempt==7: raise
    raise RuntimeError('Download failed')

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    paths=list(pool.map(download, range((size+step-1)//step)))
with (root/'WebView2-verified-download.exe').open('wb') as output:
    for path in paths: output.write(path.read_bytes())
print('Downloaded',size)
