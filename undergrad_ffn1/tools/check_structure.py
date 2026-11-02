"""Yosys hierarchy/process checks and exact native macro inventory, not PDK mapping."""
import json
from verify import ROOT,OUT,settings,environment,run,sha
from options import configure,inventory

def main():
    opt=configure(ROOT);cfg=settings();env=environment(cfg);folder=OUT/'structure';folder.mkdir(exist_ok=True)
    all_results={}
    for scope,top in [('accelerator','kwt_ffn1_top'),('soc','kwt_ffn1_soc')]:
        expected=inventory(opt,scope)
        sources=(ROOT/f'filelists/{scope}.f').read_text().splitlines()
        script='read_verilog -sv -lib tests/sram_blackboxes.sv\n'
        script+='read_verilog -sv -defer -DSYNTHESIS -DDISABLE_SV_ASSERTION -Ivendor/e203/rtl/e203/core -Itests -Irtl '+' '.join(sources)+'\n'
        script+=f'hierarchy -check -top {top}\nproc\nopt_clean\nflatten\nopt\ncheck -assert\n'
        script+=f'tee -o output/structure/{scope}.json stat -json\n'
        path=folder/(scope+'.ys');path.write_text(script)
        _,receipt=run('structure-'+scope,[cfg['yosys'],'-s',path],env)
        stats=json.loads((folder/(scope+'.json')).read_text());module=stats['modules']['\\'+top]
        counts=module['num_cells_by_type']
        for name,n in expected.items():assert counts.get(name,0)==n,(scope,name,counts.get(name))
        for name in ('RAMSP128X16','RAMSP1024X16','RAMSP4096X16'):
            assert counts.get(name,0)==expected.get(name,0),(scope,name,counts.get(name))
        if scope=='accelerator':assert counts.get('$mul')==16,counts.get('$mul')
        assert not any(x in str(counts) for x in ('kwt_gelu','kwt_encoder','kwt_ffn2'))
        all_results[scope]=dict(macros=expected,total_macros=sum(expected.values()),
            sources={s:sha(ROOT/s) for s in sources+['rtl/kwt_options.vh','tests/sram_config.vh','tests/sram_blackboxes.sv','tools/check_structure.py','tools/options.py']},receipt=receipt)
    (ROOT/'verification/structure.json').write_text(json.dumps(dict(passed=True,pdk_mapping=False,results=all_results),indent=2)+'\n')
    print('FFN1_STRUCTURE_PASS',flush=True)
if __name__=='__main__':main()
