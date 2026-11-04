"""Run fresh four-state VCS activity capture, then the existing DC power flow.

Python 3.6; no server RISC-V compiler, Verilator execution, or waveform upload.
"""
from __future__ import print_function
import argparse
import datetime
import os
from pathlib import Path
import re
import shutil
import sys

import power_server
import power_vcd
from capture_power import parse_windows
from optional_options import read as read_options, ENGINES

ROOT = Path(__file__).resolve().parents[1]
CLOCK_FS = 6666667
sha = power_server.sha
signature = power_server.signature
load = power_server.load
save = power_server.save
confined = power_server.confined


def tool_path(value, label):
    resolved = shutil.which(str(value))
    if not resolved:
        raise ValueError('%s executable not found: %s; source the server tool environment' % (label, value))
    return str(Path(resolved).resolve())


def make_overlay(original):
    if '`timescale 1ns/1fs' not in original or 'reg clk=0;always begin #3.333333 clk=1; #3.333334 clk=0; end' not in original:
        raise ValueError('seed TB lacks exact fs clock')
    if any(original.count('POWER_' + kind + ' task=') != 1 for kind in ('BEGIN', 'END')):
        raise ValueError('seed TB lacks unique strict activity markers')
    pattern = r'if\(\$test\$plusargs\("fst"\)\) \$dumpfile\("output/soc.fst"\);\s*else \$dumpfile\("output/soc.vcd"\);'
    replacement = ('if(!$value$plusargs("vcd_path=%s",vcs_power_vcd_path)) '
                   '$fatal(1,"Missing vcd_path");\n            $dumpfile(vcs_power_vcd_path);')
    result, count = re.subn(pattern, lambda unused: replacement, original)
    if count != 1 or original.count('module tb_soc;') != 1:
        raise ValueError('seed TB dump destination template changed')
    return result.replace('module tb_soc;', 'module tb_soc;\n    string vcs_power_vcd_path;')


def verify_seed(case):
    seed = load(case / 'vcs_seed.json')
    sources = seed.get('source_sha256')
    if not isinstance(sources, dict) or not sources:
        raise ValueError('missing qualified seed source hashes')
    for relative, digest in sources.items():
        if sha(confined(case, relative)) != digest:
            raise ValueError('qualified seed source mismatch: %s' % relative)
    expected = {'vectors/task_%02d/%s.hex' % (task, name) for task in range(12)
                for name in ('x', 'w', 'b', 'expected', 'x_packed', 'w_packed')}
    vectors = seed.get('vector_sha256')
    actual = {p.relative_to(case).as_posix() for p in (case / 'vectors').rglob('*.hex')}
    if not isinstance(vectors, dict) or set(vectors) != expected or actual != expected:
        raise ValueError('need exactly 72 qualified vector files for twelve tasks')
    for relative, digest in vectors.items():
        path = confined(case, relative)
        if not path.stat().st_size or sha(path) != digest:
            raise ValueError('qualified vector mismatch: %s' % relative)
    firmware = case / 'output/firmware/kwt.hex'
    if not seed.get('firmware_sha256') or sha(firmware) != seed['firmware_sha256']:
        raise ValueError('qualified firmware hex mismatch')
    return seed


def prepare_case(case, check_only=False):
    case = Path(case).resolve()
    seed = verify_seed(case)
    words = (case / 'output/firmware/kwt.hex').read_text().splitlines()
    if not words or any(not re.fullmatch(r'[0-9a-fA-F]{8}', word) for word in words):
        raise ValueError('firmware must contain one flat eight-hex-digit word per line')
    generated = {'output/firmware/size.vh': '`define FW_WORDS %d\n' % len(words),
                 'tests/tb_soc_vcs_power.sv': make_overlay((case / 'tests/tb_soc_power.sv').read_text())}
    for relative, text in generated.items():
        path = case / relative
        if check_only:
            if not path.is_file() or path.read_bytes() != text.encode('utf-8'):
                raise ValueError('generated VCS input changed: %s' % relative)
        else:
            path.write_bytes(text.encode('utf-8'))
    return seed


def source_hashes(case):
    files = {}
    for folder in ('rtl', 'tech', 'vendor', 'firmware', 'filelists', 'config', 'tests'):
        for path in sorted((case / folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                files[path.relative_to(case).as_posix()] = sha(path)
    for relative in ('case.json', 'vcs_seed.json', 'output/firmware/kwt.hex', 'output/firmware/size.vh'):
        files[relative] = sha(case / relative)
    # Seed source keys can include provenance drivers outside the source folders.
    for relative in load(case / 'vcs_seed.json')['source_sha256']:
        files[relative] = sha(confined(case, relative))
    return files


def input_binding(case, vcs, cxx):
    seed = verify_seed(case)
    sources = source_hashes(case)
    config = {name: digest for name, digest in sources.items() if name.startswith('config/') or name == 'case.json'}
    tools = {name: sha(ROOT / 'tools' / name) for name in
             ('vcs_power.py', 'capture_power.py', 'optional_options.py', 'power_server.py',
              'ppa_metrics.py', 'power_vcd.py', 'power_vcd_fast.cpp')}
    return dict(source_sha256=sources, config_sha256=config, vector_sha256=seed['vector_sha256'],
                firmware_sha256=seed['firmware_sha256'], tools_sha256=tools,
                vcs={'path': vcs, 'sha256': sha(vcs)}, cxx={'path': cxx, 'sha256': sha(cxx)})


def compile_command(case, build, simv, vcs):
    return [str(vcs), '-full64', '-sverilog', '-debug_access+all', '-timescale=1ns/1fs', '+define+DISABLE_SV_ASSERTION',
            '+incdir+vendor/e203/rtl/e203/core+output/firmware+tests+rtl',
            '-f', 'filelists/soc.f', 'tests/macro_fixtures.sv', 'tests/tb_soc_vcs_power.sv',
            '-top', 'tb_soc', '-o', str(Path(simv).resolve()), '-Mdir=' + str(Path(build).resolve())]


def simulation_command(simv, raw):
    return [str(simv), '+tasks=12', '+profile', '+fast_checks', '+host_continuous', '+vcd',
            '+vcd_path=' + str(Path(raw).resolve())]


def validate_simulation(text, options):
    whole = re.findall(r'^SOC_PASS tasks=(\d+)\s', text, re.M)
    outputs = re.findall(r'^SOC_TASK_PASS task=(\d+) cycles=(\d+) outputs=(\d+)\s*$', text, re.M)
    if whole != ['12'] or len(outputs) != 12 or sorted(int(t) for t, unused, unused2 in outputs) != list(range(12)) or any(n != '25344' for t, c, n in outputs):
        raise ValueError('VCS did not verify exactly twelve complete output tasks')
    windows = parse_windows(text, 12)
    profiles = {}
    for task, index, value in re.findall(r'^SOC_PROFILE task=(\d+) index=(\d+) value=(\d+)\s*$', text, re.M):
        group = profiles.setdefault(int(task), {})
        if int(index) in group:
            raise ValueError('duplicate VCS profile counter')
        group[int(index)] = int(value)
    rows, columns, kparallel = ENGINES[options['engine']]
    mac = ((99+rows-1)//rows)*(256//columns)*(64//kparallel)
    if set(profiles) != set(range(12)):
        raise ValueError('missing VCS task profiles')
    for task, counters in profiles.items():
        if set(counters) != set(range(15)) or counters[4] != mac or counters[9] != 11616 or counters[10] != (31680 if options['packed40'] else 50688):
            raise ValueError('VCS profile contract mismatch: task %s' % task)
    return windows, profiles


def execute(command, log, case):
    power_server.run_logged(command, log, cwd=case, stream=True)
    return Path(log).read_text(errors='replace')


def runtime_artifacts(case, simv):
    paths = [Path(simv)]
    directory = Path(str(simv) + '.daidir')
    if directory.exists():
        paths.extend(p for p in sorted(directory.rglob('*')) if p.is_file())
    return {path.relative_to(case).as_posix(): sha(path) for path in paths}


def validate_resume(case, binding):
    path, receipt = power_server.validate_capture(case)
    if receipt.get('simulator') != 'VCS' or receipt.get('vcs_input_binding') != binding:
        raise ValueError('capture is not a current, bound VCS result; run a fresh simulation')
    for relative, digest in receipt.get('provenance_sha256', {}).items():
        if sha(confined(case, relative)) != digest:
            raise ValueError('VCS executable/log/exporter provenance changed: %s' % relative)
    provenance = receipt.get('provenance_sha256')
    if not provenance or not all(receipt.get(field) for field in ('compile_log', 'simulation_log', 'simv', 'native_exporter')):
        raise ValueError('incomplete VCS provenance')
    for field in ('compile_log', 'simulation_log', 'simv', 'native_exporter'):
        if receipt[field] not in provenance:
            raise ValueError('unbound VCS provenance: %s' % field)
    # Revalidate original successful output/profile evidence, not just a passed flag.
    windows, profiles = validate_simulation((case / receipt['simulation_log']).read_text(errors='replace'), read_options(case))
    if len(receipt['tasks']) != len(windows):
        raise ValueError('VCS receipt task timing differs from simulation log')
    for logged, saved in zip(windows, sorted(receipt['tasks'], key=lambda item: item['task'])):
        if any(saved.get(key) != value for key, value in logged.items()):
            raise ValueError('VCS receipt task timing differs from simulation log')
    actual_runtime = runtime_artifacts(case, case / receipt['simv'])
    if actual_runtime != receipt.get('runtime_sha256') or any(provenance.get(name) != digest for name, digest in actual_runtime.items()):
        raise ValueError('VCS runtime executable/libraries changed')
    return receipt


def simulate_case(case, args):
    case = Path(case).resolve()
    vcs = tool_path(args.vcs, 'VCS')
    cxx = tool_path(args.cxx, 'C++')
    current = case / 'output/activity/capture.json'
    if args.resume and current.is_file() and load(current).get('stage') == 'complete':
        prepare_case(case, check_only=True)
        receipt = validate_resume(case, input_binding(case, vcs, cxx))
        print('%s: reusing verified VCS capture' % case.name, flush=True)
        return receipt
    stamp = datetime.datetime.utcnow().strftime('attempt_%Y%m%dT%H%M%S_%f')
    activity = case / 'output/activity' / stamp
    build = case / 'tmp/vcs_power' / stamp
    activity.mkdir(parents=True)
    build.mkdir(parents=True)
    if current.is_file():
        shutil.copyfile(str(current), str(activity / 'previous_capture.json'))
    save(current, dict(passed=False, functional_passed=False, stage='running', simulator='VCS', attempt=stamp, tasks=[]))
    print('%s: fresh VCS attempt %s' % (case.name, stamp), flush=True)
    prepare_case(case)
    binding = input_binding(case, vcs, cxx)
    save(activity / 'inputs.json', binding)
    def unchanged(stage):
        if input_binding(case, vcs, cxx) != binding:
            raise ValueError('VCS inputs changed during %s' % stage)
    simv = build / 'simv'
    compile_log = activity / 'compile.log'
    command = compile_command(case, build, simv, vcs)
    execute(command, compile_log, case)
    if not simv.is_file():
        raise ValueError('VCS returned without a simv executable')
    unchanged('build')
    executable_hash = sha(simv)
    runtime_hashes = runtime_artifacts(case, simv)
    raw = activity / 'soc.vcd'
    sim_log = activity / 'simulation.log'
    runtime = simulation_command(simv, raw)
    text = execute(runtime, sim_log, case)
    windows, profiles = validate_simulation(text, read_options(case))
    unchanged('simulation')
    if runtime_artifacts(case, simv) != runtime_hashes:
        raise ValueError('VCS simv/runtime libraries changed during simulation')
    if not raw.is_file() or not raw.stat().st_size:
        raise ValueError('VCS simulation produced no VCD')
    raw_hash, raw_bytes = sha(raw), raw.stat().st_size
    print('%s: exporting twelve strict VCD windows' % case.name, flush=True)
    native = power_vcd.build_native_exporter(cxx, ROOT / 'tmp/vcs_power_exporter')
    native_hash = sha(native)
    exported = power_vcd.export_windows(raw, windows, activity, native_executable=native)
    if len(exported) != 12:
        raise ValueError('VCD exporter did not return twelve tasks')
    for window, row in zip(windows, exported):
        if row['task'] != window['task'] or row['duration_fs'] != window['duration_fs']:
            raise ValueError('VCD exporter timing/task mismatch')
        window.update(row)
        window['file'] = stamp + '/' + row['file']
    unchanged('VCD export')
    if sha(raw) != raw_hash or sha(native) != native_hash or runtime_artifacts(case, simv) != runtime_hashes:
        raise ValueError('VCS/exporter executable or raw waveform changed during export')
    # Retain a case-local provenance copy, so resume remains portable and strict.
    native_copy = build / ('native_exporter' + ('.exe' if os.name == 'nt' else ''))
    shutil.copyfile(str(native), str(native_copy))
    names = dict(compile_log=compile_log.relative_to(case).as_posix(),
                 simulation_log=sim_log.relative_to(case).as_posix(), simv=simv.relative_to(case).as_posix(),
                 native_exporter=native_copy.relative_to(case).as_posix())
    receipt = dict(schema_version=1, passed=True, functional_passed=True, stage='complete',
                   simulator='VCS', real_cpu=True, rtl_activity=True, gate_level=False,
                   task_count=12, clock_period_fs=CLOCK_FS, dut_instance='tb_soc/dut', tasks=windows,
                   source_sha256=binding['source_sha256'], source_signature=signature(binding['source_sha256']),
                   config_sha256=binding['config_sha256'], config_signature=signature(binding['config_sha256']),
                   vector_sha256=binding['vector_sha256'], firmware_sha256=binding['firmware_sha256'],
                   vcs_input_binding=binding, compile_command=command, simulation_command=runtime,
                   profiles=profiles, raw_vcd_sha256=raw_hash, raw_vcd_bytes=raw_bytes,
                   executable_sha256=executable_hash, native_exporter_sha256=native_hash,
                   runtime_sha256=runtime_hashes,
                   timing_boundary='Host load start to final DMA write response; reset/readback excluded',
                   trace_note='VCS standard DUT VCD; no blanket MDA/memory dumping; inspect actual coverage',
                   provenance_sha256=dict(runtime_hashes, **{relative: sha(case / relative) for relative in names.values()}), **names)
    # Validate through the same consumer that will launch DC, before publishing.
    save(activity / 'capture.json', receipt)
    save(current, receipt)
    try:
        validate_resume(case, binding)
    except Exception:
        save(current, dict(passed=False, functional_passed=False, stage='validation_failed', simulator='VCS', attempt=stamp, tasks=[]))
        raise
    raw.unlink()
    print('%s: VCS functional/profile/export checks passed for 12 tasks' % case.name, flush=True)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=ROOT / 'vcs_power_study')
    parser.add_argument('--all', action='store_true', help='simulate, export and run DC (default)')
    parser.add_argument('--sim', action='store_true', help='VCS simulation/export only')
    parser.add_argument('--dc', action='store_true', help='DC only; requires verified current VCS capture')
    parser.add_argument('--resume', action='store_true', help='reuse only fully verified current VCS captures')
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--vcs', default=os.environ.get('VCS', 'vcs'))
    parser.add_argument('--cxx', default=os.environ.get('CXX', 'g++'))
    args = parser.parse_args(argv)
    study = args.study.resolve()
    manifest = load(study / 'activity_manifest.json')
    entries = manifest['cases']
    names = [item['name'] for item in entries]
    if len(names) != len(set(names)) or set(args.case)-set(names):
        raise ValueError('duplicate manifest or unknown selected VCS case')
    run_all = args.all or not (args.sim or args.dc)
    selected = []
    for item in entries:
        if args.case and item['name'] not in args.case:
            continue
        case = confined(study, item['path'])
        if case.name != item['name']:
            raise ValueError('VCS case name/path mismatch')
        selected.append(case)
        if run_all or args.sim:
            simulate_case(case, args)
        elif args.dc:
            vcs, cxx = tool_path(args.vcs, 'VCS'), tool_path(args.cxx, 'C++')
            prepare_case(case, check_only=True)
            validate_resume(case, input_binding(case, vcs, cxx))
    if not selected:
        raise ValueError('no selected VCS cases')
    if run_all or args.dc:
        command = ['--study', str(study), '--dc', '--collect']
        for case in selected:
            command += ['--case', case.name]
        return power_server.main(command)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print('VCS_POWER_FAILED: %s' % error, file=sys.stderr, flush=True)
        sys.exit(1)
