"""Verify every packaged byte without commercial tools or local build artifacts."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'package_manifest.json').read_text(encoding='utf-8'))
    for rel,digest in manifest.items():
        p=(ROOT/rel).resolve();p.relative_to(ROOT.resolve())
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise ValueError('Package file missing or modified: '+rel)
    sys.path.insert(0,str(ROOT/'study/tools'))
    import vcs_power
    cases=json.loads((ROOT/'study/activity_manifest.json').read_text())['cases']
    for entry in cases:
        case=ROOT/'study'/entry['path']
        vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
    print('PACKAGE_VERIFIED',len(manifest),'files;',len(cases),'qualified cases')

if __name__=='__main__':main()
