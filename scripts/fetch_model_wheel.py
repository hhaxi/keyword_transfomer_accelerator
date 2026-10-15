"""Fetch the pinned TF wheel from PyPI with ranges and published SHA-256."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import shutil
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.tools/wheels'
DEST.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen('https://pypi.org/pypi/tensorflow/2.4.0/json', timeout=30) as r:
    metadata = json.load(r)
item = next(x for x in metadata['urls'] if x['filename'].endswith('cp38-cp38-win_amd64.whl'))
target = DEST / item['filename']
size = item['size']
count = 8
width = (size + count - 1) // count

def part(i):
    start, end = i * width, min((i + 1) * width, size) - 1
    path = target.with_name(target.name + '.part' + str(i))
    failures = 0
    while failures < 6:
        done = path.stat().st_size if path.exists() else 0
        if done == end - start + 1:
            return path
        try:
            first = start + done
            # Small requests avoid large-response buffering by network gateways.
            last = min(first + 2 * 1024 * 1024 - 1, end)
            req = urllib.request.Request(item['url'], headers={'Range': f'bytes={first}-{last}'})
            with urllib.request.urlopen(req, timeout=60) as r:
                assert r.status == 206 and r.headers['Content-Range'] == f'bytes {first}-{last}/{size}'
                with path.open('ab') as f:
                    shutil.copyfileobj(r, f, 1024 * 1024)
            assert path.stat().st_size == last - start + 1
            failures = 0
            if last == end:
                print('TF wheel part', i + 1, 'complete', flush=True)
                return path
        except Exception as e:
            print('Retry', i, str(e), flush=True)
            failures += 1
            time.sleep(min(2 ** failures, 16))
    raise RuntimeError('Wheel download failed')

if not target.exists():
    with ThreadPoolExecutor(max_workers=count) as pool:
        parts = list(pool.map(part, range(count)))
    partial = target.with_suffix('.merging')
    with partial.open('wb') as out:
        for p in parts:
            with p.open('rb') as source:
                shutil.copyfileobj(source, out, 1024 * 1024)
    partial.replace(target)
    for p in parts:
        p.unlink()
h = hashlib.sha256()
with target.open('rb') as f:
    for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
        h.update(block)
assert target.stat().st_size == size and h.hexdigest() == item['digests']['sha256']
(ROOT / 'environment/model-wheel-manifest.json').write_text(json.dumps(item, indent=2) + '\n')
print('Verified:', target, flush=True)
