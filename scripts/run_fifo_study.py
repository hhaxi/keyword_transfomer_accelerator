"""Matched RTL FIFO study; same firmware/vectors, toggle output merge scheduling."""
import argparse
import hashlib
import json
from pathlib import Path
from run_encoder import ROOT, OUT, soc


def capture(label, baseline):
    files = [p for d in ['rtl', 'integration', 'firmware', 'tests']
             for p in (ROOT/d).rglob('*') if p.is_file() and p.suffix in ['.sv', '.svh', '.v', '.c', '.h', '.S', '.ld']]
    files += [ROOT/'scripts/run_encoder.py', ROOT/'scripts/run_fifo_study.py']
    data = dict(baseline=baseline,
                compile_defines=['ENCODER_FIFO_METRICS']+(['KWT_BASELINE_OUTPUT_MERGE'] if baseline else []),
                source_hash_method='LF-normalized text captured before build (initial baseline snapshot before candidate edit)',
                sources={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in files},
                firmware_sha256=hashlib.sha256((ROOT/'output/encoder-design/firmware/encoder.bin').read_bytes()).hexdigest(),
                vectors={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (ROOT/'output/encoder-vectors').rglob('*') if p.is_file() and p.suffix in ['.hex', '.vh', '.json']})
    (OUT/(label+'-inputs.json')).write_text(json.dumps(data, indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['baseline','candidate'])
    p.add_argument('--tasks',type=int,default=1)
    p.add_argument('--jobs',type=int,default=1)
    a=p.parse_args()
    if not 1<=a.jobs<=a.tasks<=12:p.error('Require 1 <= jobs <= tasks <= 12')
    baseline=a.mode=='baseline';label='tb_encoder_fifo_'+a.mode
    capture(label,baseline)
    soc(tasks=a.tasks,jobs=a.jobs,label=label,fifo_metrics=True,
        extra_flags=['+define+KWT_BASELINE_OUTPUT_MERGE'] if baseline else [])


if __name__=='__main__':main()
