"""LN1 input experiment: single-layer gate, protocol stress, then twelve layers."""
import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from run_encoder import ROOT, OUT, DEST, CONFIG, RTL, SYSTEM_RTL, ENC_RTL, ENC_BUS, run, linux, sim, soc, firmware

LABEL='tb_input_final'

def capture(stage,name="input-study-inputs.json"):
    files=[p for folder in ['rtl','integration','firmware','tests'] for p in (ROOT/folder).rglob('*')
           if p.is_file() and p.suffix in ['.sv','.svh','.v','.c','.h','.S','.ld']]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    data={'base_commit':'b71631230c868b6f1f8e8d3e1a9afdb986280512','capture_stage':stage,
          'sources':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in files},
          'firmware_sha256':digest(DEST/'firmware/encoder.bin'),
          'vectors':{p.relative_to(ROOT).as_posix():digest(p) for p in (ROOT/'output/encoder-vectors').rglob('*') if p.is_file()},
          'baseline_archives':{p.relative_to(ROOT).as_posix():digest(p) for p in (ROOT/'deliverables/b716312-baseline').glob('*.zip')}}
    (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
    return data


def single():
    firmware();capture('before single-layer build; both modes use one executable and firmware','input-single-pending.json')
    soc(tasks=1,label=LABEL,layers=1,input_stream=0,metrics=True)
    linux(LABEL+'_direct-run','output/design/build_'+LABEL+'/Vtb_encoder_soc +tasks=1 +layers=1 +input_stream=1 +transport=2',1800)
    gate(False)
    (OUT/'input-single-pending.json').replace(OUT/'input-study-inputs.json')


def protocol():
    capture('before protocol builds','input-protocol-pending.json')
    compiler=Path(CONFIG['iverilog_bin'])/'iverilog.exe';runtime=Path(CONFIG['iverilog_bin'])/'vvp.exe'
    cases=[('tb_ffn_input',RTL+['rtl/kwt_dma.sv'],[],[], 'FFN_INPUT_PASS'),
           ('tb_encoder',['rtl/kwt_sram16.sv']+ENC_RTL,['+define+ENCODER_TRACE'],['+layers=1','+transport=2','+input_stream=1'],'ENCODER_PASS layers=1'),
           ('tb_input_link',SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv'],[],[],'INPUT_LINK_PASS')]
    for top,files,flags,args,marker in cases:
        label='encoder_input' if top=='tb_encoder' else top
        files=files+['tests/'+top+'.sv']
        if marker not in sim(top,files,flags,label=label,run_args=args):raise RuntimeError(marker)
        run('icarus-'+label+'-build',[compiler,'-g2012','-s',top,'-o',DEST/(label+'.vvp')]+(['-DENCODER_TRACE'] if flags else [])+files)
        if marker not in run('icarus-'+label,[runtime,DEST/(label+'.vvp')]+args,1800):raise RuntimeError(marker)

    (OUT/'input-protocol-pending.json').replace(OUT/'input-protocol-inputs.json')


def gate(protocol_required=True):
    values=[]
    for suffix,mode in [('',0),('_direct',1)]:
        text=(OUT/(LABEL+suffix+'-run.log')).read_text()
        match=re.search(r'ENC_SOC_TASK_PASS task=0 cycles=(\d+) baseline=0 outputs=6336 transport=2 layers=1 input_stream='+str(mode),text)
        if not match or 'ENC_SOC_PASS tasks=1' not in text:raise RuntimeError('Single-layer result missing')
        if 'INPUT_LINK task=0 layer=0 mode='+str(mode) not in text:raise RuntimeError('Missing per-layer checks')
        values.append(int(match[1]))
    if values[1]>=values[0]:raise RuntimeError('No single-layer cycle benefit; do not expand')
    if protocol_required:
        inputs=json.loads((OUT/'input-study-inputs.json').read_text())
        protocol_inputs=json.loads((OUT/'input-protocol-inputs.json').read_text())
        if any(inputs[k]!=protocol_inputs[k] for k in ['sources','firmware_sha256','vectors']):raise RuntimeError('Protocol inputs differ from single-layer experiment')
        for label,marker in [('tb_ffn_input','FFN_INPUT_PASS'),('encoder_input','ENCODER_PASS layers=1'),('tb_input_link','INPUT_LINK_PASS')]:
            for name in [label+'-run','icarus-'+label]:
                if marker not in (OUT/(name+'.log')).read_text():raise RuntimeError('Protocol gate incomplete: '+name)
    print('Single-layer gate:',values,'saved',values[0]-values[1])


def full(tasks=12,jobs=4):
    gate();original=json.loads((OUT/'input-study-inputs.json').read_text())
    current=capture('before twelve-layer run; single-layer gate already passed','input-full-inputs.json')
    if original['sources']!=current['sources'] or original['firmware_sha256']!=current['firmware_sha256'] or original['vectors']!=current['vectors']:
        raise RuntimeError('Inputs changed since captured single-layer result')
    exe='output/design/build_'+LABEL+'/Vtb_encoder_soc'
    baseline_log=OUT/'input_full_sram-run.log';baseline_inputs=OUT/'input-full-sram-inputs.json'
    reusable=False
    if baseline_log.exists() and baseline_inputs.exists():
        previous=json.loads(baseline_inputs.read_text())
        reusable=all(previous[k]==current[k] for k in ['sources','firmware_sha256','vectors']) and 'ENC_SOC_PASS tasks=1' in baseline_log.read_text() and 'transport=2 layers=12 input_stream=0' in baseline_log.read_text()
    if not reusable:
        capture('before twelve-layer SRAM reference run','input-full-sram-inputs.json')
        linux('input_full_sram-run',exe+' +tasks=1 +layers=12 +input_stream=0 +transport=2',14400)
    def shard(i):
        first=i*tasks//jobs;count=(i+1)*tasks//jobs-first
        return linux('input_full_direct_shard'+str(first)+'-run',exe+' +tasks='+str(count)+' +first='+str(first)+' +layers=12 +input_stream=1 +transport=2',14400)
    with ThreadPoolExecutor(max_workers=jobs) as pool:logs=list(pool.map(shard,range(jobs)))
    (OUT/'input_full_direct-run.log').write_text('\n'.join(logs))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task',choices=['single','protocol','full'])
    parser.add_argument('--tasks',type=int,default=12);parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.jobs<=args.tasks<=12:parser.error('Require 1 <= jobs <= tasks <= 12')
    if args.task=='single':single()
    elif args.task=='protocol':protocol()
    else:full(args.tasks,args.jobs)

if __name__=='__main__':main()
