"""Repeatable local environment checks; no competition PPA claims are made."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/environment'
SMOKE = ROOT / 'environment/smoke'
MODEL_SRC = ROOT / 'assets/sources/keyword-transformer-237e4097afd4f6851e0b82f0a8d65c2dfe8eae30'
SDK_SRC = ROOT / 'assets/references/hbird-sdk-0e0e9083569721578c42f07a95b05a26c0760db6'
GCC_BIN = ROOT / '.tools/nuclei-gcc/gcc/bin'
BUILD_BIN = ROOT / '.tools/build-tools/win32-buildtools-1.2/bin'
CONFIG_FILE = ROOT / 'environment/local-tools.json'
CONFIG = json.loads(CONFIG_FILE.read_text(encoding='utf-8-sig')) if CONFIG_FILE.exists() else {}

def binary_directory(key, executable):
    configured = CONFIG.get(key)
    found = shutil.which(executable)
    return Path(configured) if configured else (Path(found).parent if found else ROOT / '.tools/missing')

MODELSIM = binary_directory('modelsim_bin', 'vsim.exe')
IVERILOG = binary_directory('iverilog_bin', 'iverilog.exe')
ENV = os.environ.copy()
ENV['PATH'] = os.pathsep.join(str(p) for p in [GCC_BIN, BUILD_BIN, IVERILOG, MODELSIM]) + os.pathsep + ENV['PATH']
ENV['PYTHONPATH'] = str(MODEL_SRC)
ENV['TF_CPP_MIN_LOG_LEVEL'] = '2'

def run(name, args, cwd=ROOT, expect=None, timeout=300):
    cwd.mkdir(parents=True, exist_ok=True)
    print('Running ' + name, flush=True)
    proc = subprocess.run([str(a) for a in args], cwd=str(cwd), env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    text = proc.stdout.decode('utf-8', errors='replace')
    (OUT / (name + '.log')).write_text(text, encoding='utf-8')
    if proc.returncode or (expect is not None and expect not in text):
        print(text[-8000:], flush=True)
        raise RuntimeError('{} failed: returncode={}; log={}'.format(name, proc.returncode, OUT / (name + '.log')))
    return text

def wsl_path(path):
    path = path.resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]

def linux(name, command, expect=None):
    # Skip user startup files: unrelated projects may have incompatible shell setup.
    return run(name, ['wsl.exe', '-d', CONFIG.get('wsl_distro', 'Ubuntu'), '--', 'bash', '--noprofile', '--norc', '-c', command], expect=expect)

def model():
    run('model', [sys.executable, ROOT / 'scripts/check_model_environment.py'], expect='MODEL_ENVIRONMENT_PASS')
    return json.loads((OUT / 'model-smoke.json').read_text())

def rtl():
    out = OUT / 'icarus'
    run('iverilog-compile', [IVERILOG / 'iverilog.exe', '-g2012', '-s', 'tb_mac_probe', '-o', out / 'mac_probe.vvp', SMOKE / 'mac_probe.sv', SMOKE / 'tb_mac_probe.sv'], cwd=out)
    run('iverilog-run', [IVERILOG / 'vvp.exe', 'mac_probe.vvp'], cwd=out, expect='RTL_ENVIRONMENT_PASS')
    out = OUT / 'modelsim'
    if not (out / 'work').exists():
        run('modelsim-library', [MODELSIM / 'vlib.exe', 'work'], cwd=out)
    run('modelsim-compile', [MODELSIM / 'vlog.exe', '-sv', SMOKE / 'mac_probe.sv', SMOKE / 'tb_mac_probe.sv'], cwd=out)
    run('modelsim-run', [MODELSIM / 'vsim.exe', '-c', '-onfinish', 'stop', 'work.tb_mac_probe', '-do', 'run -all; quit -code 0'], cwd=out, expect='RTL_ENVIRONMENT_PASS')
    return {'status': 'passed', 'simulators': ['Icarus', 'ModelSim'], 'checks': ['64 signed MACs', 'reset', 'enable hold'], 'vcd': str(OUT / 'icarus/mac_probe.vcd')}

def synth():
    out = OUT / 'yosys'
    out.mkdir(parents=True, exist_ok=True)
    script = 'read_verilog -sv environment/smoke/mac_probe.sv; synth -top mac_probe; check -assert; write_verilog -noattr output/environment/yosys/mac_probe_netlist.v; stat'
    linux('yosys-synthesis', 'cd ' + shlex.quote(wsl_path(ROOT)) + ' && ' + shlex.quote(CONFIG.get('wsl_yosys', 'yosys')) + ' -Q -T -p ' + shlex.quote(script))
    run('netlist-compile', [IVERILOG / 'iverilog.exe', '-g2012', '-s', 'tb_mac_probe', '-o', out / 'netlist_probe.vvp', out / 'mac_probe_netlist.v', SMOKE / 'tb_mac_probe.sv'], cwd=out)
    run('netlist-run', [IVERILOG / 'vvp.exe', 'netlist_probe.vvp'], cwd=out, expect='RTL_ENVIRONMENT_PASS')
    return {'status': 'passed', 'technology': 'generic gates only', 'post_synthesis_simulation': 'passed', 'official_area_timing_power': 'not evaluated; competition libraries absent'}

def sdk():
    dest = OUT / 'sdk' / SDK_SRC.name
    if not dest.exists():
        shutil.copytree(str(SDK_SRC), str(dest))
    app = dest / 'application/baremetal/helloworld'
    args = [BUILD_BIN / 'make.exe', '-C', app, '-j4', 'SOC=hbirdv2', 'BOARD=ddr200t', 'CORE=e203', 'DOWNLOAD=ilm', 'COMPILE_PREFIX=riscv64-unknown-elf-', 'RISCV_ARCH=rv32imac_zicsr_zifencei', 'all', 'dasm', 'bin']
    run('sdk-build', args)
    elf = app / 'helloworld.elf'
    header = run('sdk-elf', [GCC_BIN / 'riscv64-unknown-elf-readelf.exe', '-h', '-A', elf], expect='RISC-V')
    assert 'ELF32' in header and 'soft-float ABI' in header
    for suffix in ['elf', 'bin', 'hex', 'dasm', 'verilog']:
        assert (app / ('helloworld.' + suffix)).stat().st_size > 0
    return {'status': 'passed', 'elf': str(elf), 'architecture': 'rv32imac_zicsr_zifencei', 'abi': 'ilp32', 'board': 'upstream ddr200t reference; not competition platform', 'execution': 'compile/link only, no device or SoC execution'}

def lint():
    linux('verilator-lint', 'cd ' + shlex.quote(wsl_path(ROOT)) + ' && ' + shlex.quote(CONFIG.get('wsl_verilator', 'verilator')) + ' --lint-only -Wall --top-module mac_probe environment/smoke/mac_probe.sv')
    return {'status': 'passed'}

def sta():
    linux('opensta-startup', shlex.quote(CONFIG.get('wsl_opensta', 'sta')) + ' -exit ' + shlex.quote(wsl_path(SMOKE / 'opensta.tcl')), expect='OPENSTA_ENVIRONMENT_PASS')
    return {'status': 'startup passed', 'timing_analysis': 'pending competition standard-cell and SRAM libraries'}

def versions():
    result = {}
    for name, command in [
        ('riscv-gcc-version', [GCC_BIN / 'riscv64-unknown-elf-gcc.exe', '--version']),
        ('make-version', [BUILD_BIN / 'make.exe', '--version']),
        ('iverilog-version', [IVERILOG / 'iverilog.exe', '-V']),
        ('modelsim-version', [MODELSIM / 'vsim.exe', '-version'])]:
        result[name] = run(name, command).splitlines()[0]
    result['yosys'] = linux('yosys-version', shlex.quote(CONFIG.get('wsl_yosys', 'yosys')) + ' -V').strip()
    result['verilator'] = linux('verilator-version', shlex.quote(CONFIG.get('wsl_verilator', 'verilator')) + ' --version').strip()
    result['opensta'] = linux('opensta-version', shlex.quote(CONFIG.get('wsl_opensta', 'sta')) + ' -version').strip()
    return result

def main():
    choices = {'versions': versions, 'model': model, 'rtl': rtl, 'synth': synth, 'sdk': sdk, 'lint': lint, 'sta': sta}
    parser = argparse.ArgumentParser()
    parser.add_argument('task', nargs='?', default='all', choices=['all'] + list(choices))
    task = parser.parse_args().task
    OUT.mkdir(parents=True, exist_ok=True)
    results = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'workspace': str(ROOT), 'tasks': {}}
    failed = False
    for name in (choices if task == 'all' else [task]):
        try:
            results['tasks'][name] = choices[name]()
            print(name.upper() + '_PASS', flush=True)
        except Exception as exc:
            results['tasks'][name] = {'status': 'failed', 'error': str(exc)}
            failed = True
            print(name.upper() + '_FAIL: ' + str(exc), flush=True)
    report = OUT / ('environment-report.json' if task == 'all' else task + '-report.json')
    report.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print('Report: ' + str(report), flush=True)
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
