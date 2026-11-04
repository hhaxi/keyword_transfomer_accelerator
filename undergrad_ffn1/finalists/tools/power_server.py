"""Portable, fail-closed RTL activity conversion and fresh DC analysis (Python 3.6)."""
from __future__ import print_function
import argparse
import csv
import datetime
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from ppa_metrics import hierarchy_power, power_value, parse_reports

ROOT = Path(__file__).resolve().parents[1]
UNITS = {'s': 10**15, 'ms': 10**12, 'us': 10**9, 'ns': 10**6, 'ps': 1000, 'fs': 1}
POWER_FIELDS = ('dynamic_power_w', 'leakage_power_w', 'total_power_w')


def sha(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def load(path):
    with open(str(path), encoding='utf-8') as handle:
        return json.load(handle)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp.%s' % os.getpid())
    with open(str(temp), 'w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    os.replace(str(temp), str(path))


def confined(base, relative):
    path = (Path(base) / relative).resolve()
    try:
        path.relative_to(Path(base).resolve())
    except ValueError:
        raise ValueError('path escapes root: %s' % relative)
    return path


def check_vcd(path, task):
    """Stream the entire VCD; no timestamps/duration are inferred from cycles."""
    opener = gzip.open if str(path).endswith('.gz') else open
    header = []
    header_bytes = 0
    first = last = None
    with opener(str(path), 'rt', encoding='ascii') as handle:
        for line in handle:
            if first is None and header_bytes < 1024 * 1024:
                header.append(line)
                header_bytes += len(line)
            if line.startswith('#'):
                stamp = int(line[1:].strip())
                if last is not None and stamp < last:
                    raise ValueError('nonmonotonic VCD timestamp')
                if first is None:
                    first = stamp
                last = stamp
    match = re.search(r'\$timescale\s+(\d+)\s*(fs|ps|ns|us|ms|s)\s*\$end', ''.join(header))
    if not match or first != 0 or last is None:
        raise ValueError('VCD requires explicit timescale and rebased timestamp zero')
    scale = int(match.group(1)) * UNITS[match.group(2)]
    if task.get('source_timescale_fs', scale) != scale:
        raise ValueError('VCD timescale differs from capture receipt')
    if last * scale != task['duration_fs']:
        raise ValueError('VCD duration differs from capture receipt')
    return {'timescale_fs': scale, 'duration_fs': last * scale}


def check_saif(path, duration_fs):
    # vcd2saif header precedes instance activity; do not load huge SAIF into RAM.
    with open(str(path), encoding='ascii') as handle:
        header = handle.read(1024 * 1024)
    scale = re.search(r'\(TIMESCALE\s+(\d+)\s+(fs|ps|ns|us|ms|s)\s*\)', header)
    duration = re.search(r'\(DURATION\s+(\d+)\s*\)', header)
    if not scale or not duration:
        raise ValueError('SAIF lacks explicit duration/timescale')
    actual = int(duration.group(1)) * int(scale.group(1)) * UNITS[scale.group(2)]
    if actual != duration_fs:
        raise ValueError('SAIF duration differs from VCD/capture: %s != %s fs' % (actual, duration_fs))
    if not re.search(r'\(INSTANCE\s+tb_soc\b', header) or not re.search(r'\(INSTANCE\s+dut\b', header):
        raise ValueError('SAIF does not contain tb_soc/dut scope in header')
    return {'duration_fs': actual}


def validate_capture(case):
    receipt_path = case / 'output/activity/capture.json'
    receipt = load(receipt_path)
    if receipt.get('passed') is not True or receipt.get('functional_passed') is not True or receipt.get('stage') != 'complete':
        raise ValueError('capture is not functionally passed with complete verified export')
    if receipt.get('real_cpu') is not True or receipt.get('task_count') != 12 or receipt.get('clock_period_fs') != 6666667:
        raise ValueError('capture requires real CPU, twelve tasks, and 6666667 fs clock')
    for field in ('source_signature', 'config_signature', 'source_sha256', 'config_sha256'):
        if not receipt.get(field):
            raise ValueError('capture receipt missing %s' % field)
    for field in ('source_sha256', 'config_sha256'):
        if signature(receipt[field]) != receipt[field.replace('_sha256', '_signature')]:
            raise ValueError('capture %s signature mismatch' % field)
        for relative, expected in receipt[field].items():
            if sha(confined(case, relative)) != expected:
                raise ValueError('capture source/config mismatch: %s' % relative)
    vectors = receipt.get('vector_sha256')
    if not isinstance(vectors, dict) or not vectors:
        raise ValueError('capture requires nonempty vector_sha256 map')
    for relative, expected in vectors.items():
        if sha(confined(case, relative)) != expected:
            raise ValueError('capture vector mismatch: %s' % relative)
    firmware = case / 'output/firmware/kwt.hex'
    if not receipt.get('firmware_sha256') or sha(firmware) != receipt['firmware_sha256']:
        raise ValueError('capture firmware mismatch: output/firmware/kwt.hex')
    tasks = receipt['tasks']
    if sorted(t['task'] for t in tasks) != list(range(12)):
        raise ValueError('capture must contain exactly tasks 0..11')
    for task in tasks:
        duration = task['duration_fs']
        if not isinstance(task['source_timescale_fs'], int) or task['source_timescale_fs'] <= 0:
            raise ValueError('invalid capture VCD timescale')
        if not isinstance(duration, int) or duration <= 0 or task['end_fs'] - task['start_fs'] != duration:
            raise ValueError('invalid capture timing interval')
        path = confined(receipt_path.parent, task['file'])
        if sha(path) != task['sha256']:
            raise ValueError('VCD hash mismatch: %s' % path)
        task['_path'] = str(path)
    return receipt_path, receipt


def run_logged(command, log, env=None, cwd=None, stream=False):
    with open(str(log), 'w', encoding='utf-8') as output:
        process = subprocess.Popen(command, stdout=subprocess.PIPE if stream else output,
                                   stderr=subprocess.STDOUT, env=env, cwd=str(cwd) if cwd else None,
                                   universal_newlines=stream, bufsize=1 if stream else -1)
        if stream:
            for line in process.stdout:
                output.write(line)
                output.flush()
                print(line, end='', flush=True)
        code = process.wait()
    if code:
        raise RuntimeError('command failed (%s), inspect %s' % (code, log))


def convert(task, output, executable):
    target = output / ('task_%02d.saif' % task['task'])
    receipt = target.with_suffix('.json')
    binding = {'vcd_sha256': task['sha256'], 'duration_fs': task['duration_fs'],
               'converter': executable, 'converter_sha256': sha(executable), 'tool_sha256': sha(__file__)}
    if sha(task['_path']) != task['sha256']:
        raise ValueError('VCD changed before conversion')
    check_vcd(task['_path'], task)
    if receipt.is_file() and target.is_file():
        old = load(receipt)
        if old.get('binding') == binding and old.get('saif_sha256') == sha(target):
            check_saif(target, task['duration_fs'])
            return target
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vcd2saif_', dir=str(output)) as temporary:
        plain = Path(temporary) / 'input.vcd'
        source = Path(task['_path'])
        opener = gzip.open if str(source).endswith('.gz') else open
        with opener(str(source), 'rb') as inp, open(str(plain), 'wb') as out:
            shutil.copyfileobj(inp, out)
        generated = Path(temporary) / 'output.saif'
        run_logged([executable, '-input', str(plain), '-output', str(generated)],
                   output / ('task_%02d.convert.log' % task['task']))
        check_saif(generated, task['duration_fs'])
        if sha(task['_path']) != task['sha256']:
            raise ValueError('VCD changed during conversion')
        os.replace(str(generated), str(target))
    save(receipt, {'binding': binding, 'saif_sha256': sha(target)})
    return target


def parse_power(text):
    result = hierarchy_power(text)
    for key, label, kind in [('dynamic_power_w', 'Total Dynamic Power', 'Dynamic'),
                             ('leakage_power_w', 'Cell Leakage Power', 'Leakage')]:
        if result.get(key) is None:
            result[key] = power_value(label, text, kind)
    # Dynamic + leakage avoids mixing separately scaled leakage with table total.
    result['total_power_w'] = (result['dynamic_power_w'] + result['leakage_power_w']
                              if all(result.get(k) is not None for k in ('dynamic_power_w', 'leakage_power_w')) else None)
    return result


def aggregate(tasks):
    result = {'task_count': len(tasks), 'coverage_review': 'required',
              'method': 'postcompile_RTL_SAIF_NOT_OFFICIAL', 'mean_task_energy_j': None}
    complete = sorted(t.get('task', -1) for t in tasks) == list(range(12)) and all(
        t.get('tool_status') == 'complete' and isinstance(t.get('duration_fs'), int) and
        t['duration_fs'] > 0 and all(t.get(k) is not None and math.isfinite(t[k]) and t[k] >= 0
                                  for k in POWER_FIELDS) for t in tasks)
    energies = {}
    if complete:
        for field in POWER_FIELDS:
            energies[field] = sum(t[field] * (t['duration_fs'] * 1e-15) for t in tasks)
        complete = all(math.isfinite(v) for v in energies.values())
    result['data_status'] = 'complete' if complete else 'incomplete'
    for field in POWER_FIELDS:
        result['weighted_' + field] = None
        result['mean_task_' + field.replace('power_w', 'energy_j')] = None
        if complete:
            energy = energies[field]
            result['weighted_' + field] = energy / (sum(t['duration_fs'] for t in tasks) * 1e-15)
            result['mean_task_' + field.replace('power_w', 'energy_j')] = energy / 12
    if complete:
        result['mean_task_energy_j'] = result['mean_task_total_energy_j']
    return result


def collect(attempt, receipt):
    tasks = []
    for item in sorted(receipt['tasks'], key=lambda t: t['task']):
        folder = attempt / 'report/activity' / ('task_%02d' % item['task'])
        power = folder / 'power.rpt'
        coverage = folder / 'coverage.rpt'
        complete = all((folder / name).is_file() and (folder / name).stat().st_size > 0
                       for name in ('power.rpt', 'coverage.rpt', 'annotation.rpt', 'annotated.ok'))
        annotation = folder / 'annotation.rpt'
        annotation_text = annotation.read_text(errors='replace') if annotation.is_file() else ''
        coverage_text = coverage.read_text(errors='replace') if coverage.is_file() else ''
        power_text = power.read_text(errors='replace') if power.is_file() else ''
        if re.search(r'no\s+(?:switching\s+)?activity\s+(?:has been\s+)?annotated|'
                     r'total\s+annotated\s*(?:objects?|nets?|pins?|signals?)?\s*[:=]\s*0\b|'
                     r'\bError:', annotation_text + '\n' + coverage_text + '\n' + power_text, re.I):
            raise ValueError('annotation/mapping failed for task %s; inspect %s' % (item['task'], folder))
        entry = {'task': item['task'], 'duration_fs': item['duration_fs'], 'coverage_review': 'required',
                 'tool_status': 'complete' if complete else 'incomplete',
                 'power_report': str(power), 'coverage_report': str(coverage)}
        entry.update(parse_power(power_text))
        # Preserve all coverage output verbatim; annotation return success is not coverage acceptance.
        tasks.append(entry)
    result = aggregate(tasks)
    result['tasks'] = tasks
    total_fs = sum(t['duration_fs'] for t in tasks)
    clock_fs = receipt.get('clock_period_fs')
    result['strict_mean_cycles_per_task'] = (total_fs / clock_fs / len(tasks)
        if isinstance(clock_fs, (int, float)) and math.isfinite(clock_fs) and clock_fs > 0 and tasks else None)
    result['strict_throughput_tasks_per_s'] = len(tasks) / (total_fs * 1e-15) if tasks and total_fs > 0 else None
    result['timing'] = parse_reports(attempt / 'report', 'soc')
    result['sram_activity_status'] = 'requires_macro_pin_and_library_review'
    save(attempt / 'activity_summary.json', result)
    return result


def save_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp.%s' % os.getpid())
    with open(str(temporary), 'w', encoding='utf-8', newline='') as handle:
        handle.write(value)
    os.replace(str(temporary), str(path))


def write_comparison(folder, results):
    """Human-readable views of existing metrics; missing values stay unknown."""
    columns = ['Case', 'Added area (library units)', 'SoC area (library units)',
               'Strict cycles/task', 'Throughput (task/s)', 'Dynamic (mW)',
               'Leakage (mW)', 'Total (mW)', 'Energy (uJ/task)',
               'Setup WNS (ns)', 'Hold WNS SS only (ns)', 'Coverage']
    rows = []
    def scaled(value, factor=1):
        return value * factor if value is not None and math.isfinite(value) else None
    for name, result in results.items():
        timing = result.get('timing', {})
        rows.append([name, scaled(timing.get('added_area')), scaled(timing.get('cell_area')),
                     scaled(result.get('strict_mean_cycles_per_task')),
                     scaled(result.get('strict_throughput_tasks_per_s')),
                     scaled(result.get('weighted_dynamic_power_w'), 1000),
                     scaled(result.get('weighted_leakage_power_w'), 1000),
                     scaled(result.get('weighted_total_power_w'), 1000),
                     scaled(result.get('mean_task_energy_j'), 1e6),
                     scaled(timing.get('setup_wns_ns')), scaled(timing.get('hold_wns_ss_only_ns')),
                     'required'])
    def cell(value, unknown=''):
        return unknown if value is None else ('%.8g' % value if isinstance(value, (int, float)) else str(value))
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(columns)
    writer.writerows([[cell(value) for value in row] for row in rows])
    save_text(folder / 'comparison.csv', stream.getvalue())
    lines = ['Postcompile RTL SAIF estimates; coverage review required; no official score.', '',
             '| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    lines += ['| ' + ' | '.join(cell(value, 'unknown').replace('|', '\\|') for value in row) + ' |' for row in rows]
    lines += ['', 'Cycles and throughput use strict measured intervals, ending at the final DMA write response. '
              'Area uses linked library units. Hold WNS is SS only; it is not fast-corner signoff. '
              'Blank CSV cells and unknown table cells have no verified metric.', '']
    save_text(folder / 'comparison.md', '\n'.join(lines))


def verify_libraries(attempt):
    path = attempt / 'library_signatures.tsv'
    if not path.is_file():
        raise ValueError('missing resolved library signatures')
    rows = path.read_text().splitlines()
    if not rows:
        raise ValueError('empty resolved library signatures')
    for row in rows:
        digest, library = row.split('\t', 1)
        if sha(library) != digest:
            raise ValueError('library changed since DC: %s' % library)


def report_hashes(attempt):
    files = [p for p in sorted((attempt / 'report').rglob('*')) if p.is_file()]
    files += [attempt / name for name in ('library_signatures.tsv', 'binding.json', 'dc_complete.ok')]
    return {str(p.relative_to(attempt)).replace('\\', '/'): sha(p) for p in files}


def tcl_string(value):
    return '"' + str(value).replace('\\', '/').replace('$', '\\$').replace('[', '\\[').replace('"', '\\"') + '"'


def case_inputs(case, receipt_path):
    files = {}
    for directory in ('rtl', 'vendor', 'tech', 'filelists', 'config', 'script'):
        for path in sorted((case / directory).rglob('*')):
            if path.is_file():
                files[str(path.relative_to(case)).replace('\\', '/')] = sha(path)
    extra = os.environ.get('KWT_GLOBAL_LOCAL_CONFIG')
    return {'capture_sha256': sha(receipt_path), 'case_files': files,
            'global_local_config': {'path': extra, 'sha256': sha(extra)} if extra else None,
            'server_tcl': sha(ROOT / 'script/power_run.tcl'), 'server_python': sha(__file__),
            'power_parser': sha(ROOT / 'tools/ppa_metrics.py')}


def analyze_case(case, study, args):
    print('%s: validating qualified capture and source hashes' % case.name, flush=True)
    receipt_path, receipt = validate_capture(case)
    inputs = case_inputs(case, receipt_path)
    folder = study / 'server' / case.name / signature(inputs)
    folder.mkdir(parents=True, exist_ok=True)
    save(folder / 'inputs.json', inputs)
    saifs = []
    executable = shutil.which(args.vcd2saif)
    if args.convert or args.dc:
        if not executable:
            raise RuntimeError('vcd2saif not on PATH: %s' % args.vcd2saif)
        for task in sorted(receipt['tasks'], key=lambda t: t['task']):
            print('%s: converting/verifying task %02d of 12' % (case.name, task['task']), flush=True)
            saifs.append(convert(task, folder / 'saif', executable))
    attempt = None
    if args.dc:
        dc = shutil.which(args.dc_shell)
        if not dc:
            raise RuntimeError('dc_shell not on PATH: %s' % args.dc_shell)
        # Every DC invocation is fresh. Old successful and failed attempts remain reviewable.
        name = datetime.datetime.utcnow().strftime('attempt_%Y%m%dT%H%M%S_%f')
        attempt = folder / name
        attempt.mkdir()
        task_tcl = attempt / 'tasks.tcl'
        with open(str(task_tcl), 'w', encoding='utf-8') as handle:
            handle.write('set power_tasks [list %s]\n' % ' '.join('[list %s %s]' % (i, tcl_string(p)) for i, p in enumerate(saifs)))
        env = os.environ.copy()
        env.update(KWT_POWER_CASE_ROOT=str(case), KWT_POWER_RUN_DIR=str(attempt), KWT_POWER_TASKS=str(task_tcl), KWT_POWER_PYTHON=sys.executable, KWT_SYNTHESIS_SCOPE='soc')
        save(attempt / 'binding.json', {'inputs_signature': signature(inputs), 'saifs': [sha(p) for p in saifs], 'dc_shell': dc, 'dc_shell_sha256': sha(dc)})
        print('%s: fresh DC synthesis/activity run; log=%s' % (case.name, attempt / 'launch.log'), flush=True)
        run_logged([dc, '-f', str(ROOT / 'script/power_run.tcl')], attempt / 'launch.log', env, case, stream=True)
        if not (attempt / 'dc_complete.ok').is_file():
            raise RuntimeError('DC returned without completion marker; inspect %s' % attempt)
        if case_inputs(case, receipt_path) != inputs:
            raise RuntimeError('sources changed during DC; results invalid')
        verify_libraries(attempt)
        save(attempt / 'report_signatures.json', report_hashes(attempt))
        save(folder / 'latest.json', {'attempt': name, 'inputs_signature': signature(inputs)})
    elif args.collect:
        latest = load(folder / 'latest.json')
        if latest['inputs_signature'] != signature(inputs):
            raise ValueError('stale run binding')
        attempt = confined(folder, latest['attempt'])
        binding = load(attempt / 'binding.json')
        if binding['inputs_signature'] != signature(inputs):
            raise ValueError('stale DC binding')
        paths = [folder / 'saif' / ('task_%02d.saif' % i) for i in range(12)]
        if [sha(p) for p in paths] != binding['saifs']:
            raise ValueError('SAIF changed after DC')
        verify_libraries(attempt)
        if load(attempt / 'report_signatures.json') != report_hashes(attempt):
            raise ValueError('reports changed after DC')
    if attempt is not None:
        summary = collect(attempt, receipt)
        print('%s: data=%s coverage=required timing=%s (%s)' % (case.name, summary['data_status'], summary['timing']['setup_meets_target'], attempt), flush=True)
        return summary
    print('%s: converted 12 verified task SAIFs' % case.name, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=ROOT / 'power_study')
    parser.add_argument('--convert', action='store_true')
    parser.add_argument('--dc', action='store_true', help='includes conversion; always starts fresh synthesis')
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--vcd2saif', default='vcd2saif')
    parser.add_argument('--dc-shell', default='dc_shell')
    args = parser.parse_args(argv)
    if not any((args.convert, args.dc, args.collect)):
        parser.error('choose --convert, --dc and/or --collect')
    study = args.study.resolve()
    manifest = load(study / 'activity_manifest.json')
    names = [item if isinstance(item, str) else item['name'] for item in manifest['cases']]
    if len(set(names)) != len(names) or set(args.case) - set(names):
        raise ValueError('duplicate manifest case or unknown selected case')
    results = {}
    for item in manifest['cases']:
        if isinstance(item, str):
            item = {'name': item, 'path': 'cases/' + item}
        if args.case and item['name'] not in args.case:
            continue
        case = confined(study, item['path'])
        if case.name != item['name']:
            raise ValueError('case name/path mismatch')
        results[item['name']] = analyze_case(case, study, args)
    if not results:
        raise ValueError('no selected cases')
    if args.collect or args.dc:
        save(study / 'server/comparison.json', {'cases': results, 'official_score': None,
             'coverage_review': 'required', 'method': 'postcompile_RTL_SAIF_NOT_OFFICIAL'})
        write_comparison(study / 'server', results)
        if any(result['data_status'] != 'complete' for result in results.values()):
            raise ValueError('activity power data incomplete; inspect comparison and raw reports')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print('POWER_SERVER_FAILED: %s' % error, file=sys.stderr)
        sys.exit(1)
