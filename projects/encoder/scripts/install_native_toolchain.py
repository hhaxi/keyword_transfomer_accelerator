"""Download verified vendor archives into the project's private tools directory."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import shutil
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ITEMS = {
    'nuclei-gcc': 'https://download.nucleisys.com/upload/files/toolchain/gcc/nuclei_riscv_newlibc_prebuilt_win64_2025.10.zip',
    'build-tools': 'https://download.nucleisys.com/upload/files/toolchain/build-tools/win32-buildtools-1.2.zip',
}

def request(url, headers=None, method='GET'):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}, method=method), timeout=90)

def filehash(path, algorithm):
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        for data in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()

def install(item):
    name, url = item
    downloads = ROOT / '.tools/downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / url.rsplit('/', 1)[-1]
    with request(url, method='HEAD') as r:
        size = int(r.headers['Content-Length'])
        md5 = base64.b64decode(r.headers['Content-MD5']).hex()
        etag = r.headers['ETag']
    if not archive.exists():
        count = 8 if size > 100_000_000 else 1
        width = (size + count - 1) // count
        parts = [archive.with_name(archive.name + '.part' + str(i)) for i in range(count)]
        def fetch(i):
            first, last = i * width, min((i + 1) * width, size) - 1
            for attempt in range(6):
                done = parts[i].stat().st_size if parts[i].exists() else 0
                if done == last - first + 1:
                    return
                if done > last - first + 1:
                    raise RuntimeError('Oversized partial download')
                try:
                    start = first + done
                    with request(url, {'Range': f'bytes={start}-{last}', 'If-Match': etag}) as r:
                        if r.status != 206 or r.headers.get('Content-Range') != f'bytes {start}-{last}/{size}':
                            raise RuntimeError('Unexpected range response')
                        with parts[i].open('ab') as f:
                            shutil.copyfileobj(r, f, 1024 * 1024)
                    if parts[i].stat().st_size != last - first + 1:
                        raise IOError('Incomplete response')
                    print(f'{name} part {i + 1}/{count} downloaded', flush=True)
                    return
                except Exception as e:
                    print(f'{name} retry {attempt}: {e}', flush=True)
                    time.sleep(2 ** attempt)
            raise RuntimeError(f'{name}: download failed')
        with ThreadPoolExecutor(max_workers=count) as pool:
            list(pool.map(fetch, range(count)))
        merged = archive.with_suffix('.merging')
        with merged.open('wb') as out:
            for part in parts:
                with part.open('rb') as source:
                    shutil.copyfileobj(source, out, 4 * 1024 * 1024)
        assert merged.stat().st_size == size
        merged.replace(archive)
        for part in parts:
            part.unlink()
    assert archive.stat().st_size == size
    assert filehash(archive, 'md5') == md5, 'Vendor Content-MD5 mismatch'
    dest = ROOT / '.tools' / name
    dest.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        assert all((dest / n).resolve().is_relative_to(dest.resolve()) for n in z.namelist())
        z.extractall(dest)  # zipfile checks each decompressed member's CRC
    print(name + ' extracted and checksum verified', flush=True)
    return {'name': name, 'source': url, 'bytes': size, 'md5': md5, 'sha256': filehash(archive, 'sha256'), 'directory': str(dest)}

def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(install, ITEMS.items()))
    (ROOT / 'environment/native-tools-manifest.json').write_text(json.dumps(records, indent=2) + '\n')

if __name__ == '__main__':
    main()
