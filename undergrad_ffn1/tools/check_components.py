"""Independent four-state arithmetic, DMA backpressure/fault and abort checks."""
from pathlib import Path
import json,os
from verify import ROOT,OUT,settings,environment,run,sha
from options import configure

def main():
    opt=configure(ROOT);cfg=settings();env=environment(cfg);folder=ROOT/'tmp/components';folder.mkdir(parents=True,exist_ok=True)
    receipts=[]
    checks=[
        ('tb_mac',['rtl/kwt_mac40.sv','tests/tb_mac.sv'],'MAC_PASS'),
        ('tb_dma',['rtl/kwt_mac40.sv','tech/kwt_sram16.sv','rtl/kwt_ffn1_core.sv','rtl/kwt_ffn1_dma.sv','tests/macro_fixtures.sv','tests/tb_dma.sv'],'DMA_PASS')]
    if opt['small_x']:
        checks.append(('tb_stream',['rtl/kwt_mac40.sv','tech/kwt_sram16.sv','rtl/kwt_ffn1_core.sv','tests/macro_fixtures.sv','tests/tb_stream.sv'],'STREAM_PASS'))
    checks.append(('tb_dma_two_credit',['rtl/kwt_mac40.sv','tech/kwt_sram16.sv','rtl/kwt_ffn1_core.sv','rtl/kwt_ffn1_dma.sv','tests/macro_fixtures.sv','tests/tb_dma_two_credit.sv'],'TWO_CREDIT_PASS'))
    for top,sources,marker in checks:
        target=folder/(top+'.vvp')
        _,rec=run(top+'-compile',[cfg['iverilog'],'-g2012','-Itests','-Irtl','-s',top,'-o',target]+sources,env);receipts.append(rec)
        text,rec=run(top,[cfg['iverilog'].with_name('vvp.exe' if os.name=='nt' else 'vvp'),target],env);receipts.append(rec)
        assert marker in text
        if top=='tb_stream':
            text,rec=run('stream-overlap',[cfg['iverilog'].with_name('vvp.exe' if os.name=='nt' else 'vvp'),target,'+task=2','+early_next'],env)
            receipts.append(rec);assert 'STREAM_PASS' in text
    inputs=list((ROOT/'rtl').glob('*.sv'))+list((ROOT/'tech').glob('*.sv'))
    inputs += [ROOT/name for name in ('tests/tb_mac.sv','tests/tb_dma.sv','tests/macro_fixtures.sv',
        'tests/sram_config.vh','tests/tb_stream.sv','tests/tb_dma_two_credit.sv','rtl/kwt_options.vh','tools/options.py','tools/check_components.py','tools/verify.py')]
    (ROOT/'verification/components.json').write_text(json.dumps(dict(passed=True,four_state=True,
        sources={p.relative_to(ROOT).as_posix():sha(p) for p in inputs},
        receipts=receipts),indent=2)+'\n')
if __name__=='__main__':main()
