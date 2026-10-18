"""Shared-bus attribution on the real E203 SoC; no synthesis required."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from run_encoder import ROOT,OUT,DEST,SOC,CONFIG,SYSTEM_RTL,ENC_RTL,ENC_BUS,source_files,sim,linux,run,firmware
from build_soc import firmware as independent_firmware

BASE='c0724ce0150b0b9441659f3e2b1c69c064293c85'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(label):
    sources=set(source_files())
    for folder in ['rtl','integration','tests','firmware','model']:
        sources.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*')
                       if p.is_file() and p.suffix in ('.sv','.svh','.v','.py','.json','.c','.h','.S','.ld'))
    sources.update('scripts/'+s for s in ['run_bus_study.py','run_encoder.py','run_design.py','build_soc.py'])
    vectors={p.relative_to(ROOT).as_posix():sha(p) for folder in ['vectors','ffn-vectors','encoder-vectors']
             for p in sorted((ROOT/'output'/folder).rglob('*')) if p.is_file()}
    data=dict(base_commit=BASE,sources={n:hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in sorted(sources)},
              vectors=vectors,firmware={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [OUT/'firmware/kwt.bin',DEST/'firmware/encoder.bin']})
    receipt=OUT/(label+'-inputs.json')
    receipt.write_text(json.dumps(data,indent=2)+'\n')
    with zipfile.ZipFile(ROOT/'deliverables'/(label+'-sources.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for n in data['sources']:z.write(ROOT/n,n)
        z.write(receipt,receipt.name)
    return data


def exe(kind,label):
    top='tb_encoder_soc' if kind=='encoder' else 'tb_soc_ffn' if kind=='ffn' else 'tb_soc'
    return 'output/design/build_'+label+'/V'+top


def result(label):
    text=(OUT/(label+'-run.log')).read_text()
    if 'SOC_PASS tasks=' not in text:raise RuntimeError('Incomplete '+label)
    return [int(x) for x in re.findall(r'(?:ENC_|FFN_)?SOC_TASK_PASS task=\d+ cycles=(\d+)',text)]


def gate():
    for k,base in [('linear',167134),('ffn',305708),('encoder',1231235)]:
        r=result('bus_burst8_'+k)
        if len(r)!=1 or r[0]>=base:raise RuntimeError('No pilot benefit '+k)


def cancel_source(b):
    source=(ROOT/'tests/tb_input_link.sv').read_text()
    if 'module tb_input_link #(parameter integer DMA_BURST=1' in source:
        return source.replace('module tb_input_link #(parameter integer DMA_BURST=1',
                              'module tb_input_link #(parameter integer DMA_BURST='+str(b))
    return source.replace('kwt_extended_system_bus dut(',
                          'kwt_extended_system_bus #(.DMA_BURST('+str(b)+')) dut(')


def protocol():
    for b in [1,8]:
        generated=DEST/('bus_cancel_'+str(b)+'.sv')
        generated.write_text(cancel_source(b))
    capture('bus-protocol')
    for b in [1,8]:
        files=['integration/kwt_bus_fabric.sv','integration/kwt_shared_sram.sv','tests/tb_bus.sv']
        label='bus_protocol_'+str(b)
        if 'BUS_PASS' not in sim('tb_bus',files,['-GDMA_BURST='+str(b)],label=label):raise RuntimeError(label)
        compiler=Path(CONFIG['iverilog_bin'])/'iverilog.exe';runtime=Path(CONFIG['iverilog_bin'])/'vvp.exe'
        run(label+'-icarus-build',[compiler,'-g2012','-s','tb_bus','-Ptb_bus.DMA_BURST='+str(b),'-o',OUT/(label+'.vvp')]+files)
        if 'BUS_PASS' not in run(label+'-icarus',[runtime,OUT/(label+'.vvp')]):raise RuntimeError(label)
        linux('bus-lint-'+str(b),CONFIG['wsl_verilator']+' --lint-only -Wall --top-module kwt_extended_system_bus -GDMA_BURST='+str(b)+' '+
              ' '.join(SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv']))
        generated=DEST/('bus_cancel_'+str(b)+'.sv')
        text=sim('tb_input_link',SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv',generated.relative_to(ROOT).as_posix()],label='bus_cancel_'+str(b))
        if 'INPUT_LINK_PASS' not in text or text.count('INPUT_LINK_CANCEL_PASS')!=3:raise RuntimeError('Cancel recovery incomplete')


def build(kind,label,tasks=1,flags=None,layers=12):
    encoder=kind=='encoder'
    top='tb_encoder_soc' if encoder else 'tb_soc_ffn' if kind=='ffn' else 'tb_soc'
    wrapper=DEST/'kwt_soc_bus_study.sv'
    files=source_files()+SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv',
          'integration/kwt_encoder_soc.sv' if encoder else wrapper.relative_to(ROOT).as_posix(),'tests/'+top+'.sv']
    includes=['+incdir+'+(SOC/'rtl/e203/core').relative_to(ROOT).as_posix(),
              '+incdir+output/'+('encoder-design' if encoder else 'design')+'/firmware',
              '+incdir+tests','+define+DISABLE_SV_ASSERTION','+define+BUS_STUDY']
    if encoder:includes+=['+define+ENCODER_PHASE_METRICS','+define+ENCODER_QKV_METRICS','+define+HOST_ENCODER']
    return sim(top,files,includes+(flags or []),label=label,
               run_args=['+tasks='+str(tasks),'+profile']+(['+layers='+str(layers),'+input_stream=1','+transport=2'] if encoder else []))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('task',choices=['baseline','pilot','protocol','reference','full']);a=p.parse_args()
    if a.task=='protocol':protocol();return
    if a.task=='full':
        gate()
        for b in [1,8]:
            if 'INPUT_LINK_PASS' not in (OUT/('bus_cancel_'+str(b)+'-run.log')).read_text():raise RuntimeError('Run protocols first')
        current=capture('bus-full');pilot=json.loads((OUT/'bus-pilot-inputs.json').read_text())
        for n,h in pilot['sources'].items():
            if not n.startswith('scripts/') and current['sources'].get(n)!=h:raise RuntimeError('Compiled pilot source changed '+n)
        if current['vectors']!=pilot['vectors'] or current['firmware']!=pilot['firmware']:raise RuntimeError('Pilot inputs changed')
        def expand(k):
            return linux('bus_full_'+k+'-run',exe(k,'bus_burst8_'+k)+' +profile '+
                         ('+tasks=1 +layers=12 +input_stream=1 +transport=2' if k=='encoder' else '+tasks=12'),14400)
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(expand,['linear','ffn','encoder']))
        return
    firmware();independent_firmware()
    (DEST/'kwt_soc_bus_study.sv').write_text((ROOT/'integration/kwt_encoder_soc.sv').read_text().replace('module kwt_encoder_soc', 'module kwt_soc'))
    capture('bus-'+a.task)
    if a.task=='reference':
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda k:build(k,'bus_reference_'+k,tasks=1 if k=='encoder' else 12),['linear','ffn','encoder']))
        linux('bus_reference_encoder_single-run',exe('encoder','bus_reference_encoder')+' +tasks=1 +layers=1 +input_stream=1 +transport=2',1800)
        return
    if a.task=='pilot':
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda k:build(k,'bus_burst8_'+k,flags=['+define+BUS_BURST8'],layers=1),['linear','ffn','encoder']))
        return
    def case(kind):
        label='bus_baseline_'+kind
        build(kind,label)
        top='tb_encoder_soc' if kind=='encoder' else 'tb_soc_ffn' if kind=='ffn' else 'tb_soc'
        # The observer switch changes no simulated timing or firmware.
        linux(label+'_off-run','output/design/build_'+label+'/V'+top+' +tasks=1 +profile +bus_stats=0'+
              (' +layers=12 +input_stream=1 +transport=2' if kind=='encoder' else ''),14400)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(case,['linear','ffn','encoder']))


if __name__=='__main__':main()
