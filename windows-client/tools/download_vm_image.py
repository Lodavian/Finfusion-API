"""Download only the official Microsoft ISO selected from Evaluation Center."""
import hashlib
import json
from pathlib import Path
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

URL = 'https://software-static.download.prss.microsoft.com/dbazure/26300.9457.260913-1737.26h2_ge_release_svc_refresh_CLIENTENTERPRISEEVAL_OEMRET_x64FRE_zh-cn.iso'
PUBLISHER_SHA256 = 'b37a06d5121eee017826c0b133250bbd21bec694c2d607c60edd29090e667a84'
CHECKSUM_SOURCE = 'https://support.microsoft.com/en-us/servicing/os/windows/docs/2026/09/verify-the-authenticity-of-a-windows-11-enterprise-evaluation-iso-file'
DIRECTORY = Path('build/vm-media')


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / 'Windows11-Enterprise-Evaluation-zh-cn-x64.iso'
    partial = target.with_suffix('.iso.partial')
    report = DIRECTORY / 'download.json'
    if target.exists():
        with target.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest != PUBLISHER_SHA256: raise RuntimeError('Existing ISO fails Microsoft SHA256 verification')
        report.write_text(json.dumps({'status':'DOWNLOADED','source':URL,'path':str(target.resolve()),'bytes':target.stat().st_size,
            'sha256':digest,'publisherChecksumCompared':True,'checksumSource':CHECKSUM_SOURCE,'installed':False},indent=2),encoding='utf-8')
        print('Microsoft publisher SHA256 verified'); return
    offset = partial.stat().st_size if partial.exists() else 0
    if offset:
        resume_ranges(target, partial, report, offset)
        return
    request = Request(URL, headers={'Range': 'bytes='+str(offset)+'-'} if offset else {})
    with urlopen(request, timeout=45, context=ssl.create_default_context()) as response:
        endpoint = urlsplit(response.geturl())
        if endpoint.scheme != 'https' or not endpoint.hostname.endswith('.microsoft.com'):
            raise RuntimeError('Download redirected outside Microsoft HTTPS')
        if offset and (response.status != 206 or not response.headers.get('Content-Range','').startswith('bytes '+str(offset)+'-')):
            raise RuntimeError('Resume not accepted; partial file retained')
        total = offset + int(response.headers.get('Content-Length', 0))
        received = offset
        last_report = 0
        with partial.open('ab' if offset else 'wb') as stream:
            while chunk := response.read(1024*1024):
                stream.write(chunk); received += len(chunk)
                if time.monotonic()-last_report > 5:
                    report.write_text(json.dumps({'status':'DOWNLOADING','source':URL,'received':received,'expected':total}), encoding='utf-8')
                    last_report = time.monotonic()
            stream.flush()
        if not total or received != total:
            raise RuntimeError('Incomplete ISO; partial retained')
    partial.replace(target)
    digest = hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()
    if digest != PUBLISHER_SHA256: raise RuntimeError('Microsoft SHA256 mismatch')
    report.write_text(json.dumps({'status':'DOWNLOADED','source':URL,'path':str(target.resolve()),'bytes':total,
        'sha256':digest,'publisherChecksumCompared':True,'checksumSource':CHECKSUM_SOURCE,'installed':False}, indent=2),encoding='utf-8')
    print('Downloaded official Microsoft ISO:', target.resolve())


def resume_ranges(target, partial, report, offset):
    # Small verified ranges tolerate interrupted large responses, using <=32 MB RAM.
    with urlopen(Request(URL,method='HEAD'),timeout=45,context=ssl.create_default_context()) as response:
        total=int(response.headers['Content-Length'])
    if offset>=total: raise RuntimeError('Partial size must be smaller than source')
    folder=DIRECTORY/'iso-parts'; folder.mkdir(exist_ok=True)
    step=8*1024*1024
    ranges=[(start,min(total-1,start+step-1)) for start in range(offset,total,step)]
    def part(bounds):
        start,end=bounds; path=folder/f'{start}-{end}.part'
        if path.exists() and path.stat().st_size==end-start+1: return path
        for attempt in range(8):
            try:
                with urlopen(Request(URL,headers={'Range':f'bytes={start}-{end}'}),timeout=45,context=ssl.create_default_context()) as response:
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {start}-{end}/'):
                        raise RuntimeError('Server did not honor the exact range')
                    if not urlsplit(response.geturl()).hostname.endswith('.microsoft.com'): raise RuntimeError('Non-Microsoft redirect')
                    data=response.read()
                if len(data)!=end-start+1: raise RuntimeError('Incomplete range')
                path.write_bytes(data); return path
            except Exception:
                if attempt==7: raise
                time.sleep(min(8,attempt+1))
    received=offset
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures=[workers.submit(part,bounds) for bounds in ranges]
        for future in as_completed(futures):
            path=future.result(); received+=path.stat().st_size
            report.write_text(json.dumps({'status':'DOWNLOADING','source':URL,'received':received,'expected':total,'mode':'verified-ranges'}),encoding='utf-8')
    with partial.open('ab') as stream:
        for start,end in ranges:
            path=folder/f'{start}-{end}.part'
            with path.open('rb') as source:
                while chunk:=source.read(1024*1024): stream.write(chunk)
            stream.flush()
    if partial.stat().st_size!=total: raise RuntimeError('Merged ISO size mismatch')
    partial.replace(target)
    with target.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest != PUBLISHER_SHA256: raise RuntimeError('Microsoft SHA256 mismatch')
    report.write_text(json.dumps({'status':'DOWNLOADED','source':URL,'path':str(target.resolve()),'bytes':total,
        'sha256':digest,'publisherChecksumCompared':True,'checksumSource':CHECKSUM_SOURCE,'installed':False},indent=2),encoding='utf-8')
    print('Downloaded official Microsoft ISO:',target.resolve())


if __name__ == '__main__':
    main()
