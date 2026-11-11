"""Frontend elaboration/RTL checks only: no mapping, cell area or timing estimate."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from simulate import sha,save,run
from optional_options import read as read_options,inventory,ENGINES

def check(name):
    case=ROOT/'study/cases'/name
    out=case/'tmp/structure';out.mkdir(parents=True,exist_ok=True)
    blackboxes=ROOT/'tests/sram_blackboxes.sv'
    sources=(case/'filelists/soc.f').read_text().splitlines()
    script='read_verilog -sv -lib "'+blackboxes.as_posix()+'"\n'
    script+='read_verilog -sv -defer -DSYNTHESIS -DDISABLE_SV_ASSERTION -Ivendor/e203/rtl/e203/core -Itests -Irtl '+' '.join(sources)+'\n'
    script+='hierarchy -check -top kwt_ffn1_soc\nproc\nopt_clean\nflatten\nopt\ncheck -assert\n'
    script+='tee -o tmp/structure/stat.json stat -json\n'
    (out/'check.ys').write_text(script)
    receipt=run(case,['yosys','-s','tmp/structure/check.ys'],ROOT/'reports/logs'/name/'structure.log')
    stats=json.loads((out/'stat.json').read_text())['modules']['\\kwt_ffn1_soc']
    counts=stats['num_cells_by_type'];opt=read_options(case)
    expected=inventory(opt,scope='soc')
    for macro in ('RAMSP128X16','RAMSP1024X16','RAMSP4096X16'):
        if counts.get(macro,0)!=expected.get(macro,0):raise ValueError((name,macro,counts.get(macro),expected.get(macro)))
    # CPU arithmetic is independent of the accelerator MAC count. Elaborate
    # accelerator alone to count only its signed multipliers.
    acc=(case/'filelists/accelerator.f').read_text().splitlines()
    script=script.replace(' '.join(sources),' '.join(acc)).replace('kwt_ffn1_soc','kwt_ffn1_top').replace('stat.json','accelerator.json')
    script+='write_json tmp/structure/accelerator_netlist.json\n'
    (out/'accelerator.ys').write_text(script)
    acc_receipt=run(case,['yosys','-s','tmp/structure/accelerator.ys'],ROOT/'reports/logs'/name/'structure_accelerator.log')
    ac=json.loads((out/'accelerator.json').read_text())['modules']['\\kwt_ffn1_top']['num_cells_by_type']
    r,c,k=ENGINES[opt['engine']]
    cells=json.loads((out/'accelerator_netlist.json').read_text())['modules']['kwt_ffn1_top']['cells']
    signed16=[]
    for cell_name,cell in cells.items():
        p=cell['parameters']
        if cell['type']=='$mul' and all(int(p[k],2)==v for k,v in
            [('A_WIDTH',16),('B_WIDTH',16),('A_SIGNED',1),('B_SIGNED',1)]):signed16.append(cell_name)
    if len(signed16)!=r*c*k:raise ValueError(('unexpected MAC structure',name,len(signed16),r*c*k))
    sequential_bits=sum(len(c['connections'].get('Q',[])) for c in cells.values() if 'dff' in c['type'].lower())
    mux_output_bits=sum(len(c['connections'].get('Y',[])) for c in cells.values() if c['type'] in ('$mux','$pmux'))
    result=dict(passed=True,pdk_mapping=False,area_tested=False,generic_sequential_bits=sequential_bits,
                generic_mux_output_bits=mux_output_bits,macs=len(signed16),soc_macros=expected,
                accelerator_macros=inventory(opt),generic_rtl_cell_counts=ac,receipt=receipt,accelerator_receipt=acc_receipt,
                inputs={s:sha(case/s) for s in sources+['rtl/kwt_optional.vh','rtl/kwt_options.vh']},
                blackbox_sha256=sha(blackboxes),checker_sha256=sha(__file__))
    save(ROOT/'reports'/('structure_'+name+'.json'),result)
    print('STRUCTURE_PASS',name,'MAC',len(signed16),'macros',expected,flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--case',action='append',default=[]);args=ap.parse_args()
    names=args.case or [x['name'] for x in json.loads((ROOT/'study/activity_manifest.json').read_text())['cases']]
    for name in names:check(name)
