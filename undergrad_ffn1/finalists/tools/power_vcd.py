"""Streaming standard VCD task-window export (Python 3.6+, stdlib only).

Windows are half-open fs intervals. A #0 dumpvars snapshot records the state
immediately before start-time events; those events then appear at #0. Dump-on
snapshots are initialization, never transitions from artificial dump-off Xs.
Memory scales with declarations/current values, not source trace length.
"""
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path


UNITS = {'s': 10**15, 'ms': 10**12, 'us': 10**9,
         'ns': 10**6, 'ps': 1000, 'fs': 1}


def _open(path):
    path = Path(path)
    with path.open('rb') as handle:
        compressed = handle.read(2) == b'\x1f\x8b'
    return (gzip.open(str(path), 'rt', encoding='ascii', newline='') if compressed
            else path.open('r', encoding='ascii', newline=''))


def _header(handle):
    text = ''
    while True:
        chunk = handle.read(65536)
        if not chunk:
            raise ValueError('truncated VCD header: missing $enddefinitions $end')
        text += chunk
        match = re.search(r'\$enddefinitions\s+\$end\b', text)
        if match:
            end = match.end()
            while end < len(text) and text[end].isspace():
                end += 1
            header, rest = text[:end], text[end:]
            break
    widths = OrderedDict()
    scale = None
    scopes = 0
    position = 0
    for match in re.finditer(r'\$(\w+)\b(.*?)\$end\b', header, re.S):
        if header[position:match.start()].strip():
            raise ValueError('malformed VCD header')
        position = match.end()
        kind, value = match.group(1), match.group(2).strip()
        if kind == 'timescale':
            parsed = re.fullmatch(r'(1|10|100)\s*(s|ms|us|ns|ps|fs)', value)
            if not parsed or scale is not None:
                raise ValueError('invalid or duplicate VCD timescale')
            scale = int(parsed.group(1)) * UNITS[parsed.group(2)]
        elif kind == 'var':
            fields = value.split()
            if len(fields) < 4 or not fields[1].isdigit() or int(fields[1]) < 1:
                raise ValueError('malformed VCD $var')
            if fields[0] in ('real', 'realtime', 'string'):
                raise ValueError('non-bit VCD variables are unsupported')
            width, identifier = int(fields[1]), fields[2]
            if identifier in widths and widths[identifier] != width:
                raise ValueError('aliased identifier has conflicting widths')
            widths[identifier] = width
        elif kind == 'scope':
            scopes += 1
        elif kind == 'upscope':
            scopes -= 1
            if scopes < 0:
                raise ValueError('unbalanced VCD scope')
        elif kind not in ('date', 'version', 'comment', 'enddefinitions'):
            raise ValueError('unsupported VCD header directive: ' + kind)
    if scale is None or not widths or scopes or header[position:].strip():
        raise ValueError('incomplete VCD declarations/timescale/scope')
    return header, widths, scale, rest


def _tokens(handle, initial):
    chunk, pending = initial, ''
    while True:
        data = pending + chunk
        complete = data.split()
        # Preserve an unfinished token, never its terminating whitespace.
        # Regex '$' also matches before LF, which would drop that separator
        # and incorrectly join adjacent tokens across a 64 KiB boundary.
        pending = complete.pop() if data and not data[-1].isspace() else ''
        if len(pending) > 1048576:
            raise ValueError('VCD token exceeds 1 MiB')
        for token in complete:
            yield token
        chunk = handle.read(65536)
        if not chunk:
            if pending:
                yield pending
            return


def _change(token, tokens, widths):
    if token[:1].lower() == 'b':
        bits = token[1:].lower()
        try:
            identifier = next(tokens)
        except StopIteration:
            raise ValueError('truncated VCD vector')
        if not bits or re.search('[^01xz]', bits):
            raise ValueError('malformed VCD vector')
    elif token[:1].lower() in ('0', '1', 'x', 'z'):
        bits, identifier = token[0].lower(), token[1:]
        if widths.get(identifier) != 1:
            raise ValueError('scalar VCD value width mismatch or unknown identifier')
    else:
        raise ValueError('malformed VCD value: ' + token[:80])
    if identifier not in widths or len(bits) > widths[identifier]:
        raise ValueError('VCD vector width mismatch or unknown identifier')
    fill = bits[0] if bits[0] in 'xz' else '0'
    return identifier, bits.rjust(widths[identifier], fill)


def _format(identifier, bits):
    return (bits + identifier if len(bits) == 1 else 'b' + bits + ' ' + identifier) + '\n'


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


class _Exporter:
    def __init__(self, header, widths, scale, windows, output_dir):
        self.header, self.widths, self.scale = header, widths, scale
        self.windows, self.output_dir = windows, output_dir
        self.values = OrderedDict((key, 'x' * width) for key, width in widths.items())
        self.index, self.time, self.last_written = 0, 0, 0
        self.enabled, self.active = True, None
        self.results, self.paths = [], []

    def ensure_open(self):
        if self.active or self.index == len(self.windows):
            return
        window = self.windows[self.index]
        if window['start'] <= self.time < window['end']:
            if not self.enabled:
                raise ValueError('selected interval intersects disabled VCD dumping')
            path = self.output_dir / ('task_%02d.vcd.gz' % self.index)
            if path.exists():
                raise ValueError('refusing to overwrite VCD output: ' + str(path))
            self.paths.append(path)
            self.active = gzip.open(str(path), 'wt', encoding='ascii', newline='\n', compresslevel=1)
            self.active.write(self.header)
            if not self.header.endswith('\n'):
                self.active.write('\n')
            self.active.write('#0\n$dumpvars\n')
            for identifier, bits in self.values.items():
                self.active.write(_format(identifier, bits))
            self.active.write('$end\n')
            self.last_written = 0

    def close(self):
        window = self.windows[self.index]
        self.active.write('#%d\n' % (window['end'] - window['start']))
        self.active.close()
        self.active = None
        path = self.paths[-1]
        self.results.append(dict(task=window['task'], file=path.name,
                                 sha256=_digest(path), bytes=path.stat().st_size,
                                 duration_fs=(window['end'] - window['start']) * self.scale,
                                 source_timescale_fs=self.scale))
        self.index += 1

    def advance(self, timestamp):
        if timestamp < self.time:
            raise ValueError('VCD timestamps are not monotonic')
        # Fill residence intervals with no source events, using their true state.
        while self.index < len(self.windows):
            window = self.windows[self.index]
            if window['start'] >= timestamp:
                break
            self.time = max(self.time, window['start'])
            self.ensure_open()
            if window['end'] > timestamp:
                break
            self.close()
        self.time = timestamp

    def change(self, identifier, bits, snapshot=False):
        if not snapshot:
            self.ensure_open()
        self.values[identifier] = bits
        if self.active:
            offset = self.time - self.windows[self.index]['start']
            if offset != self.last_written:
                self.active.write('#%d\n' % offset)
                self.last_written = offset
            self.active.write(_format(identifier, bits))


def export_windows(input_vcd, windows, output_dir, native_executable=None):
    """Return per-window gzip receipts; reject invalid or incomplete activity.

    ``windows`` must be ordered, nonoverlapping dictionaries containing task,
    start_fs and end_fs integers. Any positive number of windows is supported.
    The whole source is validated, including data after the selected intervals.
    New outputs from a failed export are removed; existing files are preserved.
    An explicit native_executable uses the optional C++ body parser for raw
    input. Gzip input always uses this canonical Python parser.
    """
    if native_executable is not None:
        with Path(input_vcd).open('rb') as source:
            if source.read(2) != b'\x1f\x8b':
                return _export_native(input_vcd, windows, output_dir, native_executable)
    output_dir = Path(output_dir)
    exporter = None
    succeeded = False
    try:
        with _open(input_vcd) as handle:
            header, widths, scale, rest = _header(handle)
            checked = _checked_windows(windows, scale)
            output_dir.mkdir(parents=True, exist_ok=True)
            exporter = _Exporter(header, widths, scale, checked, output_dir)
            tokens = iter(_tokens(handle, rest))
            section = None
            saw_timestamp = False
            saw_initial_values = False
            for token in tokens:
                if token == '$comment':
                    for word in tokens:
                        if word == '$end':
                            break
                    else:
                        raise ValueError('truncated VCD comment')
                elif token in ('$dumpvars', '$dumpon', '$dumpoff', '$dumpall'):
                    if section is not None:
                        raise ValueError('nested VCD dump section')
                    section = token
                    if token == '$dumpon':
                        # Changes while disabled are unknowable. A partial
                        # snapshot must never reuse a stale pre-gap value.
                        for key, width in widths.items():
                            exporter.values[key] = 'x' * width
                    if token == '$dumpoff':
                        exporter.ensure_open()
                        if exporter.active:
                            raise ValueError('dump disabled during selected window')
                        exporter.enabled = False
                elif token == '$end':
                    if section is None:
                        raise ValueError('unexpected VCD $end')
                    if section == '$dumpon':
                        exporter.enabled = True
                    section = None
                elif token.startswith('#'):
                    if section or not re.fullmatch(r'#[0-9]+', token):
                        raise ValueError('invalid VCD timestamp/dump section')
                    timestamp = int(token[1:])
                    if (not saw_timestamp and not saw_initial_values and
                            timestamp > checked[0]['start']):
                        raise ValueError('selected window precedes source activity')
                    exporter.advance(timestamp)
                    saw_timestamp = True
                else:
                    identifier, bits = _change(token, tokens, widths)
                    if not saw_timestamp:
                        saw_initial_values = True
                    if section == '$dumpoff':
                        continue
                    if not exporter.enabled and section != '$dumpon':
                        raise ValueError('value while VCD dumping is disabled')
                    exporter.change(identifier, bits, snapshot=section in ('$dumpvars', '$dumpon'))
            if section:
                raise ValueError('truncated VCD dump section')
            if not saw_timestamp or exporter.index != len(checked):
                raise ValueError('source EOF does not cover selected intervals')
            succeeded = True
            return exporter.results
    except (EOFError, OSError, UnicodeError) as error:
        raise ValueError('unreadable or truncated VCD: ' + str(error))
    finally:
        if exporter and not succeeded:
            if exporter.active:
                exporter.active.close()
            for path in exporter.paths:
                path.unlink()


def _checked_windows(windows, scale):
    checked = []
    if not windows:
        raise ValueError('no selected intervals')
    for item in windows:
        if not isinstance(item, dict) or not all(k in item for k in ('task', 'start_fs', 'end_fs')):
            raise ValueError('missing task window markers')
        start, end = item['start_fs'], item['end_fs']
        if (type(start) is not int or type(end) is not int or start < 0 or
                end <= start or start % scale or end % scale):
            raise ValueError('invalid window or noninteger VCD tick boundary')
        if checked and start < checked[-1]['end'] * scale:
            raise ValueError('overlapping or unordered task windows')
        checked.append(dict(task=item['task'], start=start // scale, end=end // scale))
    return checked


def build_native_exporter(compiler, build_dir):
    """Build the optional backend in an explicitly supplied workspace directory.

    No compiler lookup, install, or outside-workspace writes are performed.
    Executable names contain the source hash so changed sources rebuild.
    """
    compiler, build_dir = Path(compiler).resolve(), Path(build_dir).resolve()
    workspace = Path(__file__).resolve().parents[1]
    try:
        build_dir.relative_to(workspace)
    except ValueError:
        raise ValueError('native build directory must be inside optional_lab')
    source = Path(__file__).with_name('power_vcd_fast.cpp')
    build_dir.mkdir(parents=True, exist_ok=True)
    output = build_dir / ('power_vcd_fast_' + _digest(source)[:16] + ('.exe' if os.name == 'nt' else ''))
    if not output.is_file():
        environment = os.environ.copy()
        environment.update(TMP=str(build_dir), TEMP=str(build_dir), TMPDIR=str(build_dir))
        result = subprocess.run([str(compiler), '-O3', '-std=c++11'] + (['-static'] if os.name == 'nt' else []) + [
                                 str(source), '-o', str(output)], cwd=str(build_dir),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        if result.returncode:
            raise ValueError('native VCD compile failed: ' + result.stderr.decode('utf-8', 'replace'))
    return output


def _export_native(input_vcd, windows, output_dir, executable):
    output_dir = Path(output_dir)
    created = []
    succeeded = False
    try:
        with _open(input_vcd) as source:
            header, widths, scale, rest = _header(source)
        checked = _checked_windows(windows, scale)
        if any(w['end'] > 2**64 - 1 for w in checked):
            raise ValueError('native VCD tick exceeds uint64 range; use canonical parser')
        output_dir.mkdir(parents=True, exist_ok=True)
        for index in range(len(checked)):
            if (output_dir / ('task_%02d.vcd.gz' % index)).exists():
                raise ValueError('refusing to overwrite VCD output')
        with tempfile.TemporaryDirectory(prefix='vcd_native_', dir=str(output_dir)) as folder:
            temporary = Path(folder)
            prepared_header = temporary / 'header.txt'
            prepared_header.write_bytes(header.encode('ascii'))
            manifest = temporary / 'manifest.txt'
            with manifest.open('w', encoding='ascii', newline='\n') as handle:
                handle.write('%d %d %d\n' % (len(header), len(widths), len(checked)))
                for identifier, width in widths.items():
                    handle.write('%d %s\n' % (width, identifier))
                for window in checked:
                    handle.write('%d %d\n' % (window['start'], window['end']))
            result = subprocess.run([str(Path(executable).resolve()), str(Path(input_vcd).resolve()),
                                     str(prepared_header.resolve()), str(manifest.resolve()),
                                     str(temporary.resolve())], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                raise ValueError('native VCD export failed: ' + result.stderr.decode('utf-8', 'replace'))
            rows = []
            for index, window in enumerate(checked):
                plain = temporary / ('task_%02d.vcd' % index)
                target = output_dir / ('task_%02d.vcd.gz' % index)
                with target.open('xb') as raw:
                    created.append(target)
                    with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=1, mtime=0) as compressed:
                        with plain.open('rb') as source:
                            shutil.copyfileobj(source, compressed, 1048576)
                rows.append(dict(task=window['task'], file=target.name, sha256=_digest(target),
                                 bytes=target.stat().st_size, duration_fs=(window['end'] - window['start']) * scale,
                                 source_timescale_fs=scale))
                plain.unlink()
            succeeded = True
            return rows
    except (EOFError, OSError, UnicodeError, ValueError) as error:
        raise ValueError(str(error))
    finally:
        if not succeeded:
            for path in created:
                path.unlink()


def read_vcd_metadata(input_vcd):
    """Validate raw/gzip VCD syntax and return timescale and marker duration.

    Consumes the entire stream, checking the gzip checksum as well. It does not
    retain events or infer task activity from header comments.
    """
    try:
        with _open(input_vcd) as handle:
            header, widths, scale, rest = _header(handle)
            tokens = iter(_tokens(handle, rest))
            first, last, section = None, None, None
            for token in tokens:
                if token == '$comment':
                    for word in tokens:
                        if word == '$end':
                            break
                    else:
                        raise ValueError('truncated VCD comment')
                elif token in ('$dumpvars', '$dumpon', '$dumpoff', '$dumpall'):
                    if section is not None:
                        raise ValueError('nested VCD dump section')
                    section = token
                elif token == '$end':
                    if section is None:
                        raise ValueError('unexpected VCD $end')
                    section = None
                elif token.startswith('#'):
                    if section or not re.fullmatch(r'#[0-9]+', token):
                        raise ValueError('invalid VCD timestamp')
                    timestamp = int(token[1:])
                    if last is not None and timestamp < last:
                        raise ValueError('VCD timestamps are not monotonic')
                    first = timestamp if first is None else first
                    last = timestamp
                else:
                    _change(token, tokens, widths)
            if section or last is None:
                raise ValueError('truncated VCD or missing timestamps')
            return dict(source_timescale_fs=scale, start_tick=first, end_tick=last,
                        duration_ticks=last - first, duration_fs=(last - first) * scale)
    except (EOFError, OSError, UnicodeError) as error:
        raise ValueError('unreadable or truncated VCD: ' + str(error))
