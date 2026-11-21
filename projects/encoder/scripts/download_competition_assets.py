"""Fetch the exact public inputs specified by the competition guide (stdlib only)."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
import shutil
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
SHA = '237e4097afd4f6851e0b82f0a8d65c2dfe8eae30'
REPO = 'ARM-software/keyword-transformer'
DATA_URL = 'https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz'
DATA_SHA256 = 'af14739ee7dc311471de98f5f9d2c9191b18aedfe957f4a6ff791c709868ff58'
HARDWARE = [
    ('riscv-mcu/e203_hbirdv2', '9f3e34f337f5d0a1236a285871ffa2032491617a'),
    ('riscv-mcu/hbird-sdk', '0e0e9083569721578c42f07a95b05a26c0760db6'),
]

def log(message):
    print(time.strftime('%H:%M:%S'), message, flush=True)

def request(url, headers=None, method='GET'):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'competition-assets/1.0', **(headers or {})}, method=method), timeout=90)

def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def download(url, target):
    if target.exists():
        return
    partial = target.with_suffix(target.suffix + '.part')
    for attempt in range(5):
        try:
            with request(url) as response, partial.open('wb') as out:
                shutil.copyfileobj(response, out, 1024 * 1024)
                expected = response.headers.get('Content-Length')
            if expected and partial.stat().st_size != int(expected):
                raise IOError('Incomplete download')
            partial.replace(target)
            log(f'Downloaded {target.name}: {target.stat().st_size:,} bytes')
            return
        except Exception as exc:
            log(f'Retry {attempt + 1}: {target.name}: {exc}')
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f'Download failed: {url}')

def fetch_dataset():
    target = ASSETS / 'downloads/speech_commands_v0.02.tar.gz'
    with request(DATA_URL, method='HEAD') as response:
        headers = dict(response.headers)
        size = int(response.headers['Content-Length'])
        etag = response.headers['ETag']
    save_json(ASSETS / 'metadata/speech_commands_http_headers.json', headers)
    if not target.exists():
        count = 8
        width = (size + count - 1) // count
        parts = [target.with_name(target.name + f'.part{i:02d}') for i in range(count)]
        state_path = target.with_name(target.name + '.resume.json')
        state = {'url': DATA_URL, 'size': size, 'etag': etag, 'parts': count}
        if state_path.exists() and json.loads(state_path.read_text()) != state:
            raise RuntimeError('Remote dataset changed; retained partial files need review')
        save_json(state_path, state)

        def part(i):
            start, end = i * width, min((i + 1) * width, size) - 1
            path = parts[i]
            for attempt in range(8):
                done = path.stat().st_size if path.exists() else 0
                if done == end - start + 1:
                    return
                if done > end - start + 1:
                    raise RuntimeError('Oversized partial file')
                try:
                    first = start + done
                    with request(DATA_URL, {'Range': f'bytes={first}-{end}', 'If-Match': etag}) as response:
                        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {first}-{end}/{size}':
                            raise IOError('Server did not honor requested byte range')
                        with path.open('ab') as out:
                            shutil.copyfileobj(response, out, 1024 * 1024)
                    if path.stat().st_size != end - start + 1:
                        raise IOError('Incomplete range')
                    log(f'Dataset part {i + 1}/{count} complete')
                    return
                except Exception as exc:
                    log(f'Dataset part {i + 1} retry: {exc}')
                    time.sleep(min(2 ** attempt, 16))
            raise RuntimeError(f'Dataset part {i} failed')

        with ThreadPoolExecutor(max_workers=count) as pool:
            list(pool.map(part, range(count)))
        merged = target.with_suffix('.merging')
        with merged.open('wb') as out:
            for path in parts:
                with path.open('rb') as source:
                    shutil.copyfileobj(source, out, 4 * 1024 * 1024)
        if merged.stat().st_size != size:
            raise RuntimeError('Dataset size mismatch')
        merged.replace(target)
        for path in parts:
            path.unlink()
    if target.stat().st_size != size:
        raise RuntimeError('Dataset size mismatch')
    # Google object ETag is recorded; compare its 32-hex MD5 representation here.
    md5 = digest(target, 'md5')
    if md5 != etag.strip('"'):
        raise RuntimeError(f'Dataset MD5 mismatch: {md5} != {etag}')
    sha256 = digest(target)
    if sha256 != DATA_SHA256:
        raise RuntimeError('Dataset SHA-256 differs from TensorFlow Datasets checksum')
    log(f'Dataset checksum verified: {sha256}')
    return {'url': DATA_URL, 'archive': str(target.relative_to(ROOT)), 'bytes': size, 'sha256': sha256, 'md5': md5, 'remote_etag_verified': True}

def fetch_repo(repository=REPO, commit=SHA, folder='sources'):
    name = repository.rsplit('/', 1)[-1]
    url = f'https://codeload.github.com/{repository}/zip/{commit}'
    target = ASSETS / f'downloads/{name}-{commit}.zip'
    download(url, target)
    destination = ASSETS / folder / f'{name}-{commit}'
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Repository ZIP CRC check failed')
        for member_name in archive.namelist():
            if not (ASSETS / folder / member_name).resolve().is_relative_to((ASSETS / folder).resolve()):
                raise RuntimeError('Unsafe ZIP member')
        archive.extractall(ASSETS / folder)
    with request(f'https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1') as response:
        tree = json.load(response)
    if tree.get('truncated'):
        raise RuntimeError('Incomplete Git tree')
    save_json(ASSETS / 'metadata' / f'{name}_git_tree.json', tree)
    verified = 0
    for entry in tree['tree']:
        if entry['type'] == 'commit':
            raise RuntimeError(f"Submodule requires explicit download: {entry['path']}")
        if entry['type'] != 'blob':
            continue
        data = (destination / entry['path']).read_bytes()
        actual = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if actual != entry['sha']:
            raise RuntimeError(f"Git blob mismatch: {entry['path']}")
        verified += 1
    log(f'Repository verified against Git tree: {verified} files')
    record = {'repository': repository, 'url': url, 'commit': commit, 'archive': target.relative_to(ROOT).as_posix(), 'sha256': digest(target), 'source_directory': destination.relative_to(ROOT).as_posix(), 'git_blobs_verified': verified}
    if repository != REPO:
        return record
    model = destination / 'models_data_v2_12_labels/kwt1'
    key_files = {}
    for name in ['best_weights.data-00000-of-00001', 'best_weights.index', 'flags.json', 'flags.txt', 'labels.txt']:
        key_files[name] = {'bytes': (model / name).stat().st_size, 'sha256': digest(model / name)}
    record['kwt1_files'] = key_files
    return record

def extract_dataset():
    destination = ASSETS / 'datasets/speech_commands_v0.02'
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    log('Extracting Speech Commands V2')
    with tarfile.open(ASSETS / 'downloads/speech_commands_v0.02.tar.gz', 'r|gz') as archive:
        for member in archive:
            if not (destination / member.name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe TAR path')
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise RuntimeError('Unexpected TAR member')
            archive.extract(member, destination, filter='data')
            count += 1
            if count % 20000 == 0:
                log(f'Extracted {count:,} entries')
    wav_counts = {p.name: len(list(p.glob('*.wav'))) for p in sorted(destination.iterdir()) if p.is_dir()}
    split_counts = {}
    for name in ['validation_list.txt', 'testing_list.txt']:
        lines = (destination / name).read_text().splitlines()
        if not all((destination / name).is_file() for name in lines):
            raise RuntimeError('Split references missing file')
        split_counts[name] = len(lines)
    return {'directory': str(destination.relative_to(ROOT)), 'archive_entries': count, 'wav_files': sum(wav_counts.values()), 'wav_counts_by_directory': wav_counts, 'official_split_list_counts': split_counts}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', nargs='+', choices=['model', 'dataset', 'hardware'], default=['model', 'dataset', 'hardware'])
    args = parser.parse_args()
    for name in ['downloads', 'sources', 'datasets', 'metadata', 'references']:
        (ASSETS / name).mkdir(parents=True, exist_ok=True)
    manifest_path = ASSETS / 'metadata/assets_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    manifest['downloaded_at_utc'] = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {}
        if 'dataset' in args.components:
            futures['dataset'] = pool.submit(fetch_dataset)
        if 'model' in args.components:
            futures['model'] = pool.submit(fetch_repo)
        for key, future in futures.items():
            record = future.result()
            save_json(ASSETS / 'metadata' / ('model_manifest.json' if key == 'model' else 'dataset_archive_manifest.json'), record)
            if key == 'dataset':
                record.update(extract_dataset())
            manifest[key] = record
            save_json(manifest_path, manifest)
    if 'hardware' in args.components:
        records = [fetch_repo(repo, sha, 'references') for repo, sha in HARDWARE]
        manifest['hardware_references'] = records
        save_json(ASSETS / 'metadata/hardware_reference_manifest.json', records)
    save_json(manifest_path, manifest)
    log('COMPLETE: ' + ', '.join(args.components))

if __name__ == '__main__':
    main()
