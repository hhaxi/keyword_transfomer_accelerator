"""Run selected PPA candidates, or read existing results without launching tools.

Python 3.6+, standard library only. candidates.json is a list of name/case_dir
objects (also accepts {"candidates": [...]}). Results are keyed by candidate name.
"""
from __future__ import print_function
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
COMMAND = ['bash', 'run_vcs_rtl_power.sh', 'clock_gate']
CLOCK_HZ = 150000000.0


def read_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def save_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp.'+str(os.getpid()))
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    os.replace(str(temporary), str(path))


def candidates(root):
    items = read_json(root/'candidates.json')
    if isinstance(items, dict):
        items = items.get('candidates')
    if not isinstance(items, list) or not items:
        raise ValueError('candidates.json must contain a nonempty candidate list')
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('candidate must be a name/case_dir object')
        name = item.get('name', '')
        if not isinstance(name, str) or not re.match(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$', name) or name in seen:
            raise ValueError('invalid or duplicate candidate name: '+str(name))
        if not isinstance(item.get('case_dir'), str) or not item['case_dir']:
            raise ValueError('missing case_dir for '+name)
        case = (root/item['case_dir']).resolve()
        try:
            case.relative_to(root)
        except ValueError:
            raise ValueError('case_dir escapes study: '+item['case_dir'])
        seen.add(name)
    return items


def existing_results(root, items):
    saved = read_json(root/'results.json') if (root/'results.json').is_file() else {}
    if not isinstance(saved, dict) or any(not isinstance(row, dict) for row in saved.values()):
        raise ValueError('results.json must be a mapping of candidate names to result objects')
    for item in items:
        saved.setdefault(item['name'], dict(name=item['name'], case_dir=item['case_dir'],
            status='not_run', reason='No completed server attempt has been recorded.', attempts=[]))
    return saved


def load_parsers(case):
    # Load this case's parsers, even when consecutive candidates have independent
    # snapshots. power_server imports ppa_metrics by its normal module name.
    tools = case/'tools'
    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, str(tools/filename))
        module = importlib.util.module_from_spec(spec)
        # exec_module may write __pycache__, including during --report-only.
        source = tools/filename
        exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
        return module
    ppa = load('_candidate_ppa_metrics', 'ppa_metrics.py')
    previous = sys.modules.get('ppa_metrics')
    sys.modules['ppa_metrics'] = ppa
    try:
        power = load('_candidate_power_server', 'power_server.py')
    finally:
        if previous is None:
            sys.modules.pop('ppa_metrics', None)
        else:
            sys.modules['ppa_metrics'] = previous
    return ppa.parse_reports, power.parse_power


def finite(value, minimum=None):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and (minimum is None or value >= minimum) else None


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def binding_for_files(files):
    hashes = {name:file_hash(path) for name,path in sorted(files.items()) if path.is_file()}
    signature = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return dict(version=1, sha256=hashlib.sha256(signature).hexdigest(), files=hashes)


def case_binding(case):
    """Bind consumed inputs, excluding run/results/logs and generated tests.

    Missing files are allowed in small test fixtures; additions/removals still
    change the inventory hash. Package acceptance verifies required artifacts.
    """
    files = {}
    def add(path):
        if path.is_file() and '__pycache__' not in path.parts:
            files[path.relative_to(case).as_posix()] = path
    for folder in ('rtl','tech','firmware','filelists','vendor','config','constraints','script'):
        for path in (case/folder).rglob('*'):
            add(path)
    # Server flow/analysis source is also part of the invocation contract.
    for path in (case/'tools').rglob('*'):
        if path.suffix.lower() in ('.py','.cpp','.tcl','.sh','.json'):
            add(path)
    for pattern in ('case.json','*transport*.json','*.sh','*.tcl'):
        for path in case.glob(pattern):
            add(path)
    for name in ('kwt.hex','size.vh'):
        add(case/'output/firmware'/name)
    for path in (case/'output/expected_q16').glob('*.hex'):
        add(path)
    for path in (case/'vectors').rglob('*.hex'):
        add(path)
    for path in (case/'tests').glob('*'):
        if path.suffix.lower() in ('.sv','.svh','.vh'):
            add(path)
    return binding_for_files(files)


def report_binding(case, attempt, report):
    files = {'comparison.md':attempt/'comparison.md',
             'local/functional.json':case/'output/verification/functional.json'}
    for name in ('area.rpt','area_scope.rpt','units.rpt','timing_setup.rpt',
                 'timing_hold_ss_only.rpt','clock_gating.rpt',
                 'rtl_activity/task_00/power.rpt','rtl_activity/task_00/coverage.rpt'):
        files['report/'+name] = report/name
    for path in (report/'diagnostics/mapped').rglob('*'):
        if path.suffix.lower() in ('.rpt','.json','.txt'):
            files['report/'+path.relative_to(report).as_posix()] = path
    return binding_for_files(files)


def binding_difference(old, current):
    previous = old.get('files', {})
    observed = current.get('files', {})
    changed = sorted(name for name in set(previous)|set(observed)
                     if previous.get(name) != observed.get(name))
    return ', '.join(changed[:8])+(' (and more)' if len(changed)>8 else '') or 'binding version/signature'


def resolve_report_path(text, case):
    path = Path(text.strip())
    return path.resolve() if path.is_absolute() else (case/path).resolve()


def collect(case, attempt):
    comparison = attempt/'comparison.md'
    rows = [line for line in comparison.read_text(errors='replace').splitlines()
            if re.match(r'^\s*clock_gate\s*\|', line)]
    if len(rows) != 1:
        raise ValueError('missing unique clock_gate row: '+str(comparison))
    fields = [field.strip() for field in rows[0].split('|')]
    cycles = finite(fields[1], 0)
    if cycles == 0:
        cycles = None
    report = resolve_report_path(fields[-1], case)/'report'
    parse_reports, parse_power = load_parsers(case)
    metrics = parse_reports(report, 'soc')
    activity = report/'rtl_activity/task_00'
    power_path = activity/'power.rpt'
    power = parse_power(power_path.read_text(errors='replace') if power_path.is_file() else '')
    dynamic = finite(power.get('dynamic_power_w'), 0)
    leakage = finite(power.get('leakage_power_w'), 0)
    total = finite(power.get('total_power_w'), 0)
    coverage = activity/'coverage.rpt'
    coverage_text = coverage.read_text(errors='replace') if coverage.is_file() else ''
    seq = re.search(r'^\s*Seq Cells\s+\d+\s*\(([0-9.]+)%\)', coverage_text, re.M)
    seq_percent = finite(seq.group(1), 0) if seq else None
    if seq_percent is not None and seq_percent > 100:
        seq_percent = None
    worst = None
    functional = case/'output/verification/functional.json'
    if functional.is_file():
        local = read_json(functional)
        clocks = [finite(row.get('cycles'), 0) for mode in local.get('modes', {}).values()
                  for row in mode.get('records', [])]
        if clocks and all(value is not None for value in clocks):
            worst = max(clocks)
    gating = report/'clock_gating.rpt'
    fanout = report/'diagnostics/mapped'
    result = dict(added_area=finite(metrics.get('added_area'), 0),
        soc_area=finite(metrics.get('cell_area'), 0),
        dynamic_mw=dynamic*1000 if dynamic is not None else None,
        leakage_mw=leakage*1000 if leakage is not None else None,
        total_mw=total*1000 if total is not None else None,
        energy_uj=total*cycles/CLOCK_HZ*1e6 if total is not None and cycles is not None else None,
        server_cycles=cycles, tasks_per_second=CLOCK_HZ/cycles if cycles is not None else None,
        local_worst_cycles=worst,
        throughput_pass=max(cycles, worst)<=37500 if cycles is not None and worst is not None else None,
        setup_wns_ns=finite(metrics.get('setup_wns_ns')),
        hold_wns_ss_ns=finite(metrics.get('hold_wns_ss_only_ns')),
        setup_pass=metrics.get('setup_meets_target'), hold_pass_ss=metrics.get('hold_meets_target_ss_only'),
        rtl_seq_coverage_pct=seq_percent, report_dir=str(report), attempt_dir=str(attempt),
        gating_report=str(gating), gating_report_exists=gating.is_file(),
        fanout_dir=str(fanout), fanout_dir_exists=fanout.is_dir(),
        activity_diagnostics=str(activity/'diagnostics'), timing_closed=False,
        sample='task_00_only',
        note='Seq SAIF coverage is not clock-gating coverage. SS-only hold and pre-layout setup are not physical signoff.')
    result['report_binding'] = report_binding(case, attempt, report)
    missing = [key for key in ('added_area', 'soc_area', 'dynamic_mw', 'leakage_mw',
        'energy_uj', 'server_cycles', 'setup_wns_ns', 'hold_wns_ss_ns', 'rtl_seq_coverage_pct')
        if result[key] is None]
    if metrics.get('area_scope_complete') is not True:
        missing.append('complete area scope')
    if dynamic is None or leakage is None or total is None:
        missing.append('power report')
    if not gating.is_file():
        missing.append('clock-gating report')
    if not fanout.is_dir():
        missing.append('mapped fanout diagnostics')
    result['status'] = 'incomplete' if missing else 'completed'
    result['reason'] = 'Missing or invalid: '+', '.join(missing) if missing else ''
    return result


def markdown(items, results):
    lines = ['Real nonzero task00; 150 MHz; unchanged INT16/INT40 arithmetic and single32-bit shared-memory boundary.',
        'Seq SAIF coverage is not clock-gating coverage. Missing values remain unknown. SS hold is not fast-corner signoff.', '',
        '| Candidate | Status | Added area | SoC area | Cycles | task/s | Dynamic mW | Leakage mW | uJ/task | Setup WNS ns | SS hold WNS ns | Seq SAIF % |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    def number(row, key):
        value = finite(row.get(key))
        return 'unknown' if value is None else '{:.5g}'.format(value)
    keys = ('added_area', 'soc_area', 'server_cycles', 'tasks_per_second', 'dynamic_mw',
            'leakage_mw', 'energy_uj', 'setup_wns_ns', 'hold_wns_ss_ns', 'rtl_seq_coverage_pct')
    for item in items:
        name = item['name']
        row = results[name]
        lines.append('| '+' | '.join([name, row['status']]+[number(row,key) for key in keys])+' |')
    for item in items:
        row = results[item['name']]
        lines.extend(['', item['name']+': '+(row.get('reason') or row.get('note') or 'Results recorded.')])
        for key, label in (('launch_log','Launch log'), ('report_dir','Reports'),
                           ('gating_report','Clock-gating coverage'), ('fanout_dir','Macro gates and fanout'),
                           ('activity_diagnostics','Activity diagnostics')):
            if row.get(key):
                lines.append(label+': '+str(row[key]))
    return '\n'.join(lines)+'\n'


def publish(root, items, results):
    save_text(root/'results.json', json.dumps(results, indent=2, sort_keys=True, allow_nan=False)+'\n')
    save_text(root/'comparison.md', markdown(items, results))


def report_existing(root, items, results):
    # Read-only reconstruction works even if the outer runner was never used.
    # A nonzero tool exit must stay failed even if it left some plausible reports.
    for item in items:
        row = results[item['name']]
        case = (root/item['case_dir']).resolve()
        recorded = row.get('binding')
        if recorded is not None:
            try:
                current = case_binding(case)
            except Exception as error:
                row.update(status='incomplete', reason='Cannot verify current case binding: '+str(error))
                continue
            if recorded != current or row.get('case_dir') != item['case_dir']:
                row.update(status='stale', reason='Current case binding differs from the recorded attempt: '+
                           binding_difference(recorded, current))
                continue
        if row.get('status') == 'failed':
            continue
        recorded_reports = row.get('report_binding')
        attempt = Path(row['attempt_dir']) if row.get('attempt_dir') else None
        if attempt is None or not (attempt/'comparison.md').is_file():
            # Unbound legacy reports may be inspected, but cannot be certified
            # against today's inputs. A bound result must use its own attempt.
            found = list((case/'run/vcs_rtl_power').glob('attempt_*/comparison.md')) if recorded is None else []
            attempt = max(found, key=lambda p:(p.stat().st_mtime, str(p))).parent if found else None
        if attempt is not None:
            try:
                row.update(collect(case, attempt))
                if recorded is None:
                    row.update(status='incomplete', reason='Reports are unbound: no recorded source/config/firmware/vector binding.')
                elif recorded_reports != row.get('report_binding'):
                    row.update(status='incomplete', reason='Recorded report binding differs: reports changed or cannot be verified.')
            except Exception as error:
                row.update(status='incomplete', reason='Existing report could not be read: '+str(error))
        elif row.get('status') == 'completed':
            row.update(status='incomplete', reason='Saved metrics exist, but their reports are unavailable.')
        elif row.get('status') == 'running':
            row.update(status='incomplete', reason='Previous launch has no completed report yet.')


def resumable(case, item, row, current):
    if (row.get('status') != 'completed' or row.get('case_dir') != item['case_dir'] or
            row.get('binding') != current or not row.get('report_binding')):
        return False
    try:
        verified = collect(case, Path(row['attempt_dir']))
        return verified['status'] == 'completed' and verified['report_binding'] == row['report_binding']
    except Exception:
        return False


def run_study(root, names=None, report_only=False, resume=False):
    root = Path(root).resolve()
    items = candidates(root)
    known = {item['name'] for item in items}
    chosen = known if names is None else set(names)
    unknown = chosen-known
    if unknown:
        raise ValueError('unknown candidates: '+', '.join(sorted(unknown)))
    results = existing_results(root, items)
    if report_only:
        report_existing(root, items, results)
        print(markdown(items, results), end='')
        return 0
    for item in items:
        name = item['name']
        if name not in chosen:
            continue
        case = (root/item['case_dir']).resolve()
        binding_error = None
        try:
            current = case_binding(case)
        except Exception as error:
            current = None
            binding_error = str(error)
        if binding_error is None and resume and resumable(case, item, results[name], current):
            continue
        parent = root/'run/candidates'/name
        parent.mkdir(parents=True, exist_ok=True)
        outer = Path(tempfile.mkdtemp(prefix='attempt_', dir=str(parent)))
        log_path = outer/'launch.log'
        history = list(results[name].get('attempts', []))
        attempt_row = dict(status='running', launch_log=str(log_path), command=list(COMMAND),
                           binding=current,
                           started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        history.append(attempt_row)
        row = dict(name=name, case_dir=item['case_dir'], attempts=history, **attempt_row)
        results[name] = row
        publish(root, items, results)
        code = None
        try:
            if binding_error is not None:
                raise ValueError('Cannot hash case inputs: '+binding_error)
            if not (case/'run_vcs_rtl_power.sh').is_file():
                raise ValueError('missing case or run_vcs_rtl_power.sh: '+str(case))
            print('Q128_CANDIDATE_START', name, log_path, flush=True)
            with log_path.open('wb') as log:
                code = subprocess.call(list(COMMAND), cwd=str(case), stdout=log, stderr=subprocess.STDOUT)
            row['returncode'] = code
            launches = re.findall(r'^Q128_VCS_RTL_POWER_RUN (.+)$',
                                  log_path.read_text(errors='replace'), re.M)
            if len(launches) == 1:
                row['attempt_dir'] = str(resolve_report_path(launches[0], case))
            if code:
                row.update(status='failed', reason='VCS/DC exited {}: {}'.format(code, log_path))
            elif len(launches) != 1:
                row.update(status='incomplete', reason='Missing unique VCS attempt marker: '+str(log_path))
            else:
                row.update(collect(case, Path(row['attempt_dir'])))
        except Exception as error:
            row.update(status='incomplete' if code == 0 else 'failed', reason=str(error))
            with log_path.open('ab') as log:
                log.write(('RUNNER_ERROR: '+str(error)+'\n').encode('utf-8'))
        if current is not None:
            try:
                observed = case_binding(case)
                if observed != current:
                    row.update(status='stale', reason='Case binding changed during launch: '+
                               binding_difference(current, observed), observed_binding_after=observed)
            except Exception as error:
                row['binding_verification_error'] = str(error)
                if row['status'] == 'completed':
                    row.update(status='incomplete', reason='Cannot verify case binding after launch: '+str(error))
        row['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        attempt_row.update({key:value for key,value in row.items() if key != 'attempts'})
        publish(root, items, results)
        print('Q128_CANDIDATE_RESULT', name, row['status'], flush=True)
    print(markdown(items, results), end='')
    return 1 if any(results[name].get('status') != 'completed' for name in chosen) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', help='Candidate names, separated by spaces or commas')
    parser.add_argument('--report-only', action='store_true', help='Read existing results/reports; never launch tools or write files')
    parser.add_argument('--resume', action='store_true', help='Skip completed candidates only when input and report bindings still match')
    args = parser.parse_args(argv)
    names = [name for value in args.cases for name in value.split(',') if name] if args.cases else None
    return run_study(ROOT, names=names, report_only=args.report_only, resume=args.resume)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        print('Q128_COMBINED_FAILED', error, file=sys.stderr)
        sys.exit(1)
