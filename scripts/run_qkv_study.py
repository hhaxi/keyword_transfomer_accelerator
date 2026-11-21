"""Profile f7a3a47 QKV without changing production RTL or frozen arithmetic.

run: single-layer observer on/off, twelve-layer profile, independent regressions.
collect: check provenance, cycle accounting, bit checks and baseline equivalence.
"""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from run_encoder import ROOT, OUT, DEST, firmware, soc, compatibility, linux

BASE = 'f7a3a47d48c5581319d580d98f7145515976ee06'
LABEL = 'tb_qkv_study'
RECEIPT = OUT / 'qkv-study-inputs.json'
REPORT = ROOT / 'docs/evidence/qkv-study-validation.json'


def sha(path, normalized=False):
    data = path.read_bytes()
    return hashlib.sha256(data.replace(b'\r\n', b'\n') if normalized else data).hexdigest()


def inputs():
    def git(*args):
        return subprocess.check_output(['git'] + list(args), cwd=str(ROOT))
    # This experiment is diagnostic. Refuse to silently profile modified RTL.
    production = git('ls-tree', '-r', '--name-only', BASE, 'rtl', 'integration', 'firmware', 'model').decode().splitlines()
    for name in production:
        if (ROOT/name).read_bytes().replace(b'\r\n', b'\n') != git('show', BASE+':'+name).replace(b'\r\n', b'\n'):
            raise RuntimeError('Production source differs from baseline: '+name)
    sources = {p.relative_to(ROOT).as_posix(): sha(p, True)
               for folder in ['rtl', 'integration', 'firmware', 'tests', 'model']
               for p in sorted((ROOT/folder).rglob('*'))
               if p.is_file() and p.suffix in ['.v', '.sv', '.svh', '.c', '.h', '.S', '.ld', '.py', '.json']}
    for name in ['run_qkv_study.py', 'run_encoder.py', 'run_design.py', 'build_soc.py']:
        sources['scripts/'+name] = sha(ROOT/'scripts'/name, True)
    vectors = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT/'output/encoder-vectors').rglob('*')) if p.is_file()}
    previous = json.loads((ROOT/'docs/evidence/input-stream-validation.json').read_text())
    if vectors != previous['inputs']['vectors'] or sha(DEST/'firmware/encoder.bin') != previous['inputs']['firmware_sha256']:
        raise RuntimeError('Vectors/firmware differ from verified v5 baseline')
    frozen = previous['frozen_numeric_sha256']
    if any(sha(ROOT/name) != value for name, value in frozen.items()):
        raise RuntimeError('Frozen numeric contract changed')
    archives = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT/'deliverables/f7a3a47-baseline').glob('*.zip'))}
    expected = {
        'deliverables/f7a3a47-baseline/source.zip': '684d64b3b9fd7b85fc0f8225b8bf1b5989165c32cfc6aecf5ebb9b551d5d09db',
        'deliverables/f7a3a47-baseline/verified-v5.zip': '48dbfe35f08c75a59dd9ac0acf7a8c7498505585ba2c878b8f33e126ba9d9a1c'}
    if archives != expected:
        raise RuntimeError('Missing or changed baseline archives')
    return dict(base_commit=BASE, sources=sources, vectors=vectors,
                firmware_sha256=sha(DEST/'firmware/encoder.bin'), baseline_archives=archives,
                frozen_numeric_sha256=frozen, production_matches_base=True)


def rows(text, tag):
    return [dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)', line))
            for line in text.splitlines() if line.startswith(tag+' ')]


def checked_log(name, marker):
    path = OUT/(name+'.log')
    text = path.read_text()
    if marker not in text or '%Error' in text or 'FATAL' in text:
        raise RuntimeError('Incomplete or failed log: '+name)
    return text


def collect():
    receipt = json.loads(RECEIPT.read_text())
    if receipt != inputs():
        raise RuntimeError('Study inputs changed since pre-build capture')
    experiments = {}
    for name, layers, enabled, expected in [
            (LABEL+'-run', 1, True, 1231235),
            ('qkv_observer_off-run', 1, False, 1231235),
            ('qkv_twelve-run', 12, True, 14315119)]:
        text = checked_log(name, 'ENC_SOC_PASS tasks=1')
        result = rows(text, 'ENC_SOC_TASK_PASS')
        if len(result) != 1 or any(result[0][k] != v for k, v in dict(task=0, cycles=expected, baseline=0, outputs=6336, transport=2, layers=layers, input_stream=1).items()):
            raise RuntimeError('Whole-task baseline mismatch: '+name)
        compute, loads = rows(text, 'QKV_COMPUTE'), rows(text, 'QKV_LOAD')
        accounting = rows(text, 'QKV_ACCOUNTING_PASS')
        if len(compute) != (3*layers if enabled else 0) or len(loads) != (6*layers if enabled else 0) or len(accounting) != (layers if enabled else 0):
            raise RuntimeError('Missing QKV samples: '+name)
        phase = rows(text, 'ENC_PHASE')
        stats = rows(text, 'ENC_LAYER_STATS')
        link = rows(text, 'INPUT_LINK')
        if len(phase)!=20*layers or len(stats)!=8*layers or len(link)!=layers:
            raise RuntimeError('Missing existing counters')
        for li in range(layers):
            for p in range(3) if enabled else []:
                c = [r for r in compute if r['layer']==li and r['projection']==p]
                expected_c = dict(task=0, mac=101376, prime=1, init=1, save=1584, wait=0,
                                  x_read32=101376, w_read32=405504, result_write32=6336,
                                  prefetch_mac=99792, prefetch_save=1583, final_row_w_idle=17)
                if len(c)!=1 or any(c[0][k]!=v for k,v in expected_c.items()):
                    raise RuntimeError('Compute accounting')
            layer_load = [r for r in loads if r['layer']==li]
            if enabled:
                if sorted(r['kind'] for r in layer_load)!=list(range(6)):
                    raise RuntimeError('Load kinds missing')
                for r in layer_load:
                    words = (6336 if li==0 else 0) if r['kind']==0 else 320 if r['kind']==1 else 4096
                    if r['write32']!=words or r['cycles']!=sum(r[k] for k in ['issue_only','retire_only','both','neither']) or r['issue_only']!=r['retire_only'] or r['write32']!=r['both']+r['retire_only']:
                        raise RuntimeError('Load partition')
                hw_load = [r['value'] for r in phase if r['layer']==li and r['op']==0 and r['index']==7]
                if hw_load != [sum(r['cycles'] for r in layer_load)]:
                    raise RuntimeError('Hardware load phase mismatch')
            if [r['value'] for r in stats if r['layer']==li and r['index']==7] != [0]:
                raise RuntimeError('Unexpected saturation')
        traffic = sum(r['value'] for r in stats if r['index'] in (3,4)) + sum(r['dma_reads'] for r in link)
        if traffic != (46080 if layers==1 else 413568):
            raise RuntimeError('Traffic regression')
        experiments[name] = dict(cycles=expected, layers=layers, observer=enabled,
                                 accelerator_dma_words32=traffic, qkv=compute, loads=loads,
                                 phases=phase, link=link, checked_qkv_values=19008*layers if enabled else 0)
    independent = {}
    for name, tag, expected in [('tb_soc_encoder_compat-run','SOC_TASK_PASS',167134),
                                ('tb_soc_ffn_encoder_compat-run','FFN_SOC_TASK_PASS',305708)]:
        text = checked_log(name, 'SOC_PASS tasks=12')
        cases = rows(text, tag)
        if [r['task'] for r in cases]!=list(range(12)) or any(r['cycles']!=expected for r in cases):
            raise RuntimeError('Independent regression: '+name)
        independent[name] = dict(tasks=12, cycles=expected, bit_exact=True)
    full = experiments['qkv_twelve-run']
    weight_load = sum(r['cycles'] for r in full['loads'] if r['kind'] in (2,3,4))
    overhead = 4758*12
    bounds = dict(mac_cycles_per_layer=304128, phase_cycles_per_layer=308886,
                  utilization_percent=304128/308886*100,
                  local_schedule_ceiling_cycles=overhead,
                  local_schedule_ceiling_percent=overhead/full['cycles']*100,
                  qkv_weight_load_cycles=weight_load,
                  ideal_one_word_per_clock_dma_excess_cycles=weight_load-12288*12,
                  optimistic_all_weight_load_hidden_plus_schedule_cycles=overhead+weight_load,
                  optimistic_all_weight_load_hidden_plus_schedule_percent=(overhead+weight_load)/full['cycles']*100,
                  caveat='Analytical hardware-window bounds, not measured task savings; host polling and overlap can change task deltas. All-weight hiding requires storage/schedule redesign.')
    lognames = list(experiments)+list(independent)+[LABEL+'-build']
    logs = {('output/design/'+n+'.log'):sha(OUT/(n+'.log')) for n in lognames}
    report = dict(base_commit=BASE, conclusion='Retain v5 RTL: local QKV scheduling ceiling below 0.4% of twelve-layer task; no RTL optimization or twelve-layer optimization rollout.',
                  experiments=experiments, independent=independent, bounds=bounds,
                  production_matches_base=True, frozen_numeric_sha256=receipt['frozen_numeric_sha256'],
                  inputs_receipt=dict(path=RECEIPT.relative_to(ROOT).as_posix(), sha256=sha(RECEIPT),
                                      vector_files=len(receipt['vectors']), firmware_sha256=receipt['firmware_sha256']),
                  baseline_archives=receipt['baseline_archives'], logs_sha256=logs,
                  not_measured=['new area','power','timing','synthesis'], passed=True)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(bounds,indent=2))
    return report


def package():
    report = collect()
    files = [ROOT/name for name in report['logs_sha256']]
    files += [RECEIPT, REPORT, ROOT/'docs/studies/qkv-study.md', ROOT/'README.md']
    receipt = json.loads(RECEIPT.read_text())
    files += [ROOT/name for name in receipt['sources']]
    target = ROOT/'deliverables/qkv-study-f7a3a47.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Archive CRC failed')
        for path in set(files):
            if archive.read(path.relative_to(ROOT).as_posix()) != path.read_bytes():
                raise RuntimeError('Archive content mismatch')
    (target.with_suffix('.sha256.txt')).write_text(sha(target)+'  '+target.name+'\n')
    print(str(target)+' SHA256='+sha(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task',choices=['run','collect','package'])
    args=parser.parse_args()
    if args.task=='run':
        firmware()
        RECEIPT.write_text(json.dumps(inputs(),indent=2)+'\n')
        soc(tasks=1,layers=1,input_stream=1,metrics=True,label=LABEL,
            extra_flags=['+define+ENCODER_QKV_METRICS'])
        exe='output/design/build_'+LABEL+'/Vtb_encoder_soc'
        linux('qkv_observer_off-run',exe+' +tasks=1 +layers=1 +input_stream=1 +transport=2 +qkv_stats=0',1800)
        linux('qkv_twelve-run',exe+' +tasks=1 +layers=12 +input_stream=1 +transport=2',14400)
        compatibility()
        collect()
    elif args.task=='collect':collect()
    else:package()


if __name__=='__main__':main()
