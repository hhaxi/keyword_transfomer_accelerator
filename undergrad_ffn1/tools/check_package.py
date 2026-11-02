"""Validate self-contained sources and frozen upload hashes, without a PDK."""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(root=ROOT,allow_modified_rtl=False):
    manifest=json.loads((root/'source_manifest.json').read_text())
    for item in manifest['snapshots']:
        p=root/item['package_path']
        if not p.is_file():raise ValueError('Missing source: '+str(p))
        if sha(p)!=item['sha256']:
            if not allow_modified_rtl:raise ValueError('Changed source: '+str(p)+'; intentional server edits: --allow-modified-rtl')
            print('FFN1_CHANGED_SOURCE_ALLOWED:',p,file=sys.stderr)
    for name,h in manifest['vendor_e203']['files'].items():
        if not (root/name).is_file() or sha(root/name)!=h:raise ValueError('Changed pinned vendor source: '+name)
    for scope in ('soc','accelerator'):
        lines=(root/f'filelists/{scope}.f').read_text().splitlines()
        if len(lines)!=len(set(lines)):raise ValueError('Duplicate source')
        for line in lines:
            if Path(line).is_absolute() or '..' in Path(line).parts or not (root/line).is_file():raise ValueError('Nonlocal/missing source: '+line)
            if re.search(r'kwt_(encoder|gelu|exp_negative|isqrt|udiv|vecmem|result_fifo)',line):raise ValueError('Optional hardware included: '+line)
        if lines.count('tech/kwt_sram16.sv')!=1:raise ValueError('Technology boundary must appear once')
    for p in list((root/'script').glob('*.tcl'))+[root/'run_dc.sh',root/'recover_reports.sh']:
        if b'\r' in p.read_bytes():raise ValueError('Server scripts require LF: '+str(p))
    return manifest
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--allow-modified-rtl',action='store_true');a=ap.parse_args()
    try:check(allow_modified_rtl=a.allow_modified_rtl)
    except Exception as e:print('FFN1_PACKAGE_FAILED:',e,file=sys.stderr);sys.exit(1)
    print('FFN1_PACKAGE_PASS')
