"""Optional complete 12-layer gate activity handoff; large FST, no power claim."""
import argparse
import hashlib
import json
from run_encoder import ROOT,DEST,firmware,soc


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtl',action='store_true',help='Use RTL rather than the generic synthesized netlist')
    a=p.parse_args();firmware()
    soc(netlist=not a.rtl,tasks=1,label='tb_encoder_activity',activity=True)
    wave=DEST/'encoder-soc.fst'
    if not wave.exists() or wave.stat().st_size==0:raise RuntimeError('No activity emitted')
    h=hashlib.sha256()
    with wave.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    report=dict(file=wave.relative_to(ROOT).as_posix(),bytes=wave.stat().st_size,sha256=h.hexdigest(),
                scope='One input, all 12 layers; ENC_MEASURE_BEGIN/END include input and parameter loads plus final acknowledgement',
                representation='rtl' if a.rtl else 'generic zero-delay netlist',
                official_mapping_coverage_checked=False,sram_power_model_available=False,
                measured_power_mw=None,measured_energy_mj=None)
    (DEST/'activity-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
