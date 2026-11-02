"""Independent four-state arithmetic, DMA backpressure/fault and abort checks."""
from pathlib import Path
import json,os
from verify import ROOT,OUT,settings,environment,run,sha

def main():
    cfg=settings();env=environment(cfg);folder=ROOT/'tmp/components';folder.mkdir(parents=True,exist_ok=True)
    receipts=[]
    for top,sources,marker in [
        ('tb_mac',['rtl/kwt_mac40.sv','tests/tb_mac.sv'],'MAC_PASS'),
        ('tb_dma',['rtl/kwt_mac40.sv','tech/kwt_sram16.sv','rtl/kwt_ffn1_core.sv','rtl/kwt_ffn1_dma.sv','tests/macro_fixtures.sv','tests/tb_dma.sv'],'DMA_PASS')]:
        target=folder/(top+'.vvp')
        _,rec=run(top+'-compile',[cfg['iverilog'],'-g2012','-Itests','-s',top,'-o',target]+sources,env);receipts.append(rec)
        text,rec=run(top,[cfg['iverilog'].with_name('vvp.exe' if os.name=='nt' else 'vvp'),target],env);receipts.append(rec)
        assert marker in text
    inputs=list((ROOT/'rtl').glob('*.sv'))+list((ROOT/'tech').glob('*.sv'))
    inputs += [ROOT/name for name in ('tests/tb_mac.sv','tests/tb_dma.sv','tests/macro_fixtures.sv',
        'tests/sram_config.vh','tools/check_components.py','tools/verify.py')]
    (ROOT/'verification/components.json').write_text(json.dumps(dict(passed=True,four_state=True,
        sources={p.relative_to(ROOT).as_posix():sha(p) for p in inputs},
        receipts=receipts),indent=2)+'\n')
if __name__=='__main__':main()
