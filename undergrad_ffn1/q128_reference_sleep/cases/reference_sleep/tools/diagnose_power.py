"""Inspect a saved DC run; prepare/replay read-only fanout, gating and power diagnostics.

Default prepares evidence and a replay command without requiring DC. No synthesis,
constraint changes, artificial activity or modification of the original run.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^()\s]+')
SIGNAL = re.compile(r'^(?:clk|clock|macro_clk|gated_clk|gclk|cen|cs|gwen|enable_latched|en_latched|gate_en|latched_enable|enable_q)$', re.I)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def tcl_string(value):
    value = str(value)
    if any(char in value for char in '\x00\n\r'):
        raise ValueError('Tcl input must not contain NUL or newlines')
    return '"' + ''.join('\\' + char if char in '\\$[]"' else char for char in value) + '"'


def inspect_saif(path):
    """Stream S-expression frames; retain clock/control records, not the entire SAIF.

    Raw SAIF presence proves capture only. DC reports must prove the annotation.
    Rates are transitions per ns (a clock has two transitions per period).
    """
    stack, rows = [], []
    duration, timescale = None, None
    with Path(path).open(encoding='utf-8', errors='replace') as source:
        for line in source:
            for token in TOKEN.findall(line):
                if token == '(':
                    parent = stack[-1] if stack else None
                    stack.append(dict(key=None, values=[], selected=False, metrics={},
                                      signal=bool(parent and parent['key'] in ('NET', 'PORT'))))
                elif token == ')':
                    if not stack:
                        raise ValueError('unbalanced SAIF closing parenthesis')
                    frame = stack.pop()
                    key, values = frame['key'], frame['values']
                    if key == 'DURATION' and values:
                        duration = float(values[0])
                    if key == 'TIMESCALE' and len(values) == 2:
                        timescale = (float(values[0]), values[1])
                    if stack and stack[-1]['selected'] and key in ('T0', 'T1', 'TX', 'TZ', 'TC', 'IG') and values:
                        stack[-1]['metrics'][key] = float(values[0])
                    if frame['selected']:
                        instances = [f['values'][0] for f in stack if f['key'] == 'INSTANCE' and f['values']]
                        row = dict(path='/'.join(instances + [key]), evidence='present_in_raw_saif_not_proof_of_dc_mapping')
                        row.update(frame['metrics'])
                        rows.append(row)
                else:
                    if not stack:
                        continue
                    frame = stack[-1]
                    if frame['key'] is None:
                        frame['key'] = token.strip('"')
                        frame['selected'] = frame['signal'] and bool(SIGNAL.fullmatch(frame['key'].lstrip('\\')))
                    elif len(frame['values']) < 2:
                        frame['values'].append(token.strip('"'))
    if stack:
        raise ValueError('unbalanced/truncated SAIF')
    scale = {'s': 1e9, 'ms': 1e6, 'us': 1e3, 'ns': 1., 'ps': 1e-3, 'fs': 1e-6}
    duration_ns = duration * timescale[0] * scale[timescale[1]] if duration and timescale and timescale[1] in scale else None
    for row in rows:
        row['toggles_per_ns'] = row['TC'] / duration_ns if duration_ns and 'TC' in row else None
        row['unknown_fraction'] = (row['TX'] + row.get('TZ', 0)) / duration if duration and 'TX' in row else None
    return dict(duration_raw=duration, timescale=timescale, duration_ns=duration_ns, signals=rows,
                limitation='Raw capture presence is not mapped annotation; compare DC pin raw activity and source before/after report_power.')


def settings_and_libraries(run, explicit):
    path = run / 'report/run_settings.txt'
    settings = dict(re.findall(r'^([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$', path.read_text(errors='replace'), re.M))
    target = settings.get('std_db')
    if not target:
        raise ValueError('saved run_settings.txt does not record std_db')
    libraries = [Path(target)]
    if explicit:
        libraries += [Path(item).resolve() for item in explicit]
    else:
        inventory = run / 'report/sram_inventory.rpt'
        if not inventory.is_file():
            raise ValueError('saved SRAM inventory missing; provide each original SRAM DB with --library')
        for words, count in re.findall(r'^RAMSP(128|1024|4096)X16\s+count=(\d+)\b', inventory.read_text(errors='replace'), re.M):
            if int(count):
                key = 'sram_db_' + words
                if not settings.get(key):
                    raise ValueError('saved run_settings.txt lacks ' + key)
                libraries.append(Path(settings[key]))
    return settings, list(dict.fromkeys(libraries))


def input_hashes(paths):
    return {str(path): sha(path) if path.is_file() else 'MISSING' for path in paths}


def warning_context(run, output):
    lines = []
    pattern = re.compile(r'fan.?out|TIM-134|PWR-\d+|switching activity.*conflict|unannotated|not annotated|ideal|wire.?load', re.I)
    candidates = list((run / 'log').glob('*.log')) + [run / 'launch.log', run / 'report/run_settings.txt']
    for path in candidates:
        if not path.is_file():
            continue
        with path.open(encoding='utf-8', errors='replace') as source:
            for number, line in enumerate(source, 1):
                if pattern.search(line):
                    lines.append('{}:{}: {}'.format(path, number, line.rstrip()))
    (output / 'original_warnings.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def prepare(args):
    run = args.run.resolve()
    if not run.is_dir():
        raise ValueError('saved DC run directory does not exist: ' + str(run))
    settings, libraries = settings_and_libraries(run, args.library)
    top = settings.get('top_design', 'kwt_ffn1_soc')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top):
        raise ValueError('invalid saved top_design')
    ddc = (args.ddc or run / ('netlist/' + top + '.ddc')).resolve()
    if not ddc.is_file() and not args.ddc:
        ddc = run / ('netlist/' + top + '_compiled.ddc')
    if not ddc.is_file():
        raise ValueError('saved DDC missing: ' + str(ddc))
    sdc = (args.sdc or run / ('sdc/' + top + ('_compiled' if ddc.stem.endswith('_compiled') else '') + '.sdc')).resolve()
    saif = args.saif.resolve() if args.saif else None
    if saif and not saif.is_file():
        raise ValueError('SAIF missing: ' + str(saif))
    parent = (args.output_root or ROOT / 'run/power_diagnostics').resolve()
    # The helper must never place reports inside or overwrite the original run.
    if parent == run or run in parent.parents:
        raise ValueError('--output-root must be outside the original saved run')
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='attempt_', dir=str(parent)))
    for name in ('power_diagnostics.tcl', 'diagnostic_replay.tcl'):
        shutil.copyfile(str(ROOT / 'script' / name), str(output / name))
    evidence = output / 'original'
    evidence.mkdir()
    for name in ('run_settings.txt', 'sram_inventory.rpt', 'clock_gating.rpt', 'clock_gating_elements.rpt',
                 'constraints.rpt', 'units.rpt', 'clocks.rpt'):
        source = run / 'report' / name
        if source.is_file():
            shutil.copyfile(str(source), str(evidence / name))
    warning_context(run, output)
    paths = [ddc, sdc, run / 'report/run_settings.txt'] + libraries + ([saif] if saif else [])
    signatures = input_hashes(paths)
    write_json(output / 'input_signatures.json', signatures)
    raw = inspect_saif(saif) if saif else dict(signals=[], limitation='NO_SAIF: vectorless diagnostics only')
    write_json(output / 'raw_saif_controls.json', raw)
    with (output / 'raw_saif_controls.tsv').open('w', newline='', encoding='utf-8') as target:
        columns = ('path', 'T0', 'T1', 'TX', 'TZ', 'TC', 'IG', 'toggles_per_ns', 'unknown_fraction', 'evidence')
        writer = csv.DictWriter(target, fieldnames=columns, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(raw['signals'])
    values = dict(saved_ddc=ddc, saved_sdc=sdc, saved_saif=saif or '', saved_top=top,
                  saved_saif_kind=args.saif_kind, saved_instance=args.instance,
                  diagnostic_dir=output, diagnostic_target_library=libraries[0])
    script = ''.join('set {} {}\n'.format(name, tcl_string(value)) for name, value in values.items())
    script += 'set diagnostic_libraries [list {}]\n'.format(' '.join(tcl_string(value) for value in libraries))
    (output / 'inputs.tcl').write_text(script, encoding='utf-8')
    notes = ['Saved-run diagnostics; original files remain unchanged.',
             'DDC=' + str(ddc), 'SAIF=' + (str(saif) if saif else 'NONE: VECTORLESS ONLY'),
             'Seq SAIF annotation coverage and gated-register coverage are different metrics.',
             'Fresh DDC replay may lack original RTL name mapping; compare original same-process reports.',
             'No power improvement or physical fanout/timing signoff is implied.',
             'Unsupported reports and attributes are explicitly UNAVAILABLE in each availability.tsv.',
             'DC inspect: mapped/high_fanout_loads.tsv, mapped/top_net_*.rpt, mapped/clock_gating*.rpt.',
             'Activity inspect: annotated_before_power versus annotated_after_power clock_macro_activity.tsv and raw_activity/*.rpt.',
             'Power inspect: annotated_after_power/power_hierarchy.rpt plus disjoint-root group reports.',
             'Raw SAIF controls prove capture only; inspect DC raw activity sources for user/propagated/default.',
             'Run from this folder (Bash):', 'export KWT_DIAGNOSTIC_INPUTS="$PWD/inputs.tcl"',
             'dc_shell -f diagnostic_replay.tcl 2>&1 | tee launch.log']
    missing = [path for path, digest in signatures.items() if digest == 'MISSING']
    if missing:
        notes += ['MISSING INPUT (replay will refuse): ' + path for path in missing]
    (output / 'READ_FIRST.txt').write_text('\n'.join(notes) + '\n', encoding='utf-8')
    return output, signatures, paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', required=True, type=Path, help='Original run containing report/, netlist/, sdc/')
    parser.add_argument('--ddc', type=Path)
    parser.add_argument('--sdc', type=Path)
    parser.add_argument('--saif', type=Path)
    parser.add_argument('--saif-kind', choices=('rtl', 'gate'), default='rtl')
    parser.add_argument('--instance', default='tb_soc/dut')
    parser.add_argument('--library', action='append', help='Original SRAM DB; explicit list replaces inventory-derived SRAM list')
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--replay', action='store_true', help='Run read-only DC analysis after preparing evidence')
    parser.add_argument('--dc-shell', default='dc_shell')
    args = parser.parse_args(argv)
    output, signatures, paths = prepare(args)
    print('KWT_POWER_DIAGNOSTICS_PREPARED: ' + str(output), flush=True)
    status = 0
    if args.replay:
        missing = [path for path, digest in signatures.items() if digest == 'MISSING']
        if missing:
            raise ValueError('replay inputs missing: ' + ', '.join(missing))
        executable = shutil.which(args.dc_shell)
        if not executable:
            raise ValueError('dc_shell unavailable; source the original EDA environment; prepared ' + str(output))
        environment = dict(os.environ, KWT_DIAGNOSTIC_INPUTS=str(output / 'inputs.tcl'))
        with (output / 'launch.log').open('w', encoding='utf-8') as log:
            status = subprocess.call([executable, '-f', str(output / 'diagnostic_replay.tcl')],
                                     cwd=str(output), env=environment, stdout=log, stderr=subprocess.STDOUT)
        if not (output / 'diagnostics_complete.ok').is_file():
            status = status or 1
        print('KWT_POWER_DIAGNOSTICS_REPLAY_STATUS: ' + str(status), flush=True)
    unchanged = input_hashes(paths) == signatures
    write_json(output / 'diagnostic_summary.json', dict(replay_requested=args.replay, replay_exit_status=status if args.replay else None,
        saved_inputs_unchanged=unchanged, power_acceptance='NOT_CERTIFIED', output=str(output)))
    if not unchanged:
        raise ValueError('saved inputs changed during diagnostics; investigate before using any result')
    return status


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        print('KWT_POWER_DIAGNOSTICS_FAILED: ' + str(error), file=sys.stderr)
        sys.exit(1)