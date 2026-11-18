"""Host loading study on d9dc461; preserve blocking driver and timing window."""
import argparse
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
import run_bus_study as bus

BASE='d9dc461becb97166fe7b89990b90c835d7710eea'
bus.BASE=BASE

def capture(label):
    data=bus.capture(label)
    data['runner_sha256']=bus.sha(bus.ROOT/'scripts/run_host_study.py')
    (bus.OUT/(label+'-inputs.json')).write_text(json.dumps(data,indent=2)+'\n')
    with zipfile.ZipFile(bus.ROOT/'deliverables'/(label+'-sources.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for name in data['sources']:z.write(bus.ROOT/name,name)
        z.write(bus.ROOT/'scripts/run_host_study.py','scripts/run_host_study.py')
        z.write(bus.OUT/(label+'-inputs.json'),label+'-inputs.json')
    return data

def setup():
    bus.firmware();bus.independent_firmware()
    (bus.DEST/'kwt_soc_bus_study.sv').write_text((bus.ROOT/'integration/kwt_encoder_soc.sv').read_text().replace('module kwt_encoder_soc','module kwt_soc'))

def build(kind,dma,label,layers=1,extra=None):
    flags=(['+define+BUS_BURST8'] if dma==8 else [])+(extra or [])
    return bus.build(kind,label,flags=flags,layers=layers)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['baseline','pilot','reference','protocol','full','off']);a=p.parse_args()
    if a.stage=='off':
        for dma in [1,8]:
            for k in ['linear','ffn','encoder']:
                label='host_base_d'+str(dma)+'_'+k
                bus.linux(label+'_off-run',bus.exe(k,label)+' +tasks=1 +profile +host_stats=0'+
                          (' +layers=1 +input_stream=1 +transport=2' if k=='encoder' else ''),14400)
        return
    if a.stage=='protocol':protocol();return
    if a.stage=='full':full();return
    setup();capture('host-'+a.stage)
    if a.stage=='reference':
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda k:build(k,8,'host_ref_d8_'+k),['linear','ffn','encoder']))
        return
    for dma in [1,8]:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda k:build(k,dma,('host_base_d' if a.stage=='baseline' else 'host_h2_d')+str(dma)+'_'+k,
                layers=12 if a.stage=='baseline' else 1,
                extra=['+define+HOST_BURST2'] if a.stage=='pilot' else []),['linear','ffn','encoder']))

def protocol():
    capture('host-protocol')
    for dma in [1,8]:
        for host in [0,2]:
            label='host_protocol_d'+str(dma)+'_h'+str(host)
            files=bus.BUS_TEST
            if 'BUS_PASS' not in bus.sim('tb_bus',files,['+define+DISABLE_SV_ASSERTION','-GDMA_BURST='+str(dma),'-GHOST_BURST='+str(host)],label=label,run_args=['+host_gaps']):raise RuntimeError(label)
            compiler=bus.Path(bus.CONFIG['iverilog_bin'])/'iverilog.exe';runtime=bus.Path(bus.CONFIG['iverilog_bin'])/'vvp.exe'
            bus.run(label+'-icarus-build',[compiler,'-g2012','-DDISABLE_SV_ASSERTION','-s','tb_bus','-Ptb_bus.DMA_BURST='+str(dma),'-Ptb_bus.HOST_BURST='+str(host),'-o',bus.OUT/(label+'.vvp')]+files)
            if 'BUS_PASS' not in bus.run(label+'-icarus',[runtime,bus.OUT/(label+'.vvp'),'+host_gaps']):raise RuntimeError(label)
            bus.linux(label+'-lint',bus.CONFIG['wsl_verilator']+' --lint-only -Wall -Wno-fatal +define+DISABLE_SV_ASSERTION --top-module kwt_extended_system_bus -GDMA_BURST='+str(dma)+' -GHOST_BURST='+str(host)+' '+
                      ' '.join(bus.SYSTEM_RTL+bus.ENC_RTL+bus.ENC_BUS+['integration/kwt_shared_sram.sv']))
    for dma in [1,8]:
        label='host_cancel_d'+str(dma)
        text=bus.sim('tb_input_link',bus.SYSTEM_RTL+bus.ENC_RTL+bus.ENC_BUS+['integration/kwt_shared_sram.sv','tests/tb_input_link.sv'],
                     ['-GDMA_BURST='+str(dma),'-GHOST_BURST=2','-GBACKGROUND_HOST=1'],label=label)
        if text.count('INPUT_LINK_CANCEL_PASS')!=3 or 'INPUT_LINK_PASS' not in text or 'HOST_BACKGROUND_PASS' not in text:raise RuntimeError(label)

def full():
    from collect_host_study import parse
    for dma in [1,8]:
        for k in ['linear','ffn','encoder']:
            r=parse(bus.OUT/('host_h2_d'+str(dma)+'_'+k+'-run.log'))[0]
            limit=(1231235 if dma==1 else 1225034) if k=='encoder' else parse(bus.OUT/('host_base_d'+str(dma)+'_'+k+'-run.log'))[0]['cycles']
            if r['cycles']>=limit:raise RuntimeError('Pilot did not improve '+k)
    current=capture('host-full');pilot=json.loads((bus.OUT/'host-pilot-inputs.json').read_text())
    for name,h in pilot['sources'].items():
        if name.startswith(('rtl/','integration/','tests/')) and current['sources'].get(name)!=h:raise RuntimeError('Pilot source changed '+name)
    if current['vectors']!=pilot['vectors'] or current['firmware']!=pilot['firmware']:raise RuntimeError('Input drift')
    for stage in ['reference','protocol']:
        receipt=json.loads((bus.OUT/('host-'+stage+'-inputs.json')).read_text())
        if receipt['vectors']!=current['vectors'] or receipt['firmware']!=current['firmware']:raise RuntimeError('Input drift '+stage)
        for name,h in current['sources'].items():
            if name.startswith(('rtl/','integration/','tests/')) and receipt['sources'].get(name)!=h:raise RuntimeError('Stale compiled '+stage+' '+name)
    for k in ['linear','ffn','encoder']:
        r=parse(bus.OUT/('host_ref_d8_'+k+'-run.log'))
        expected={'linear':165003,'ffn':301408,'encoder':1225034}[k]
        if len(r)!=1 or r[0]['cycles']!=expected:raise RuntimeError('Disabled-feature reference drift '+k)
    for dma in [1,8]:
        if 'HOST_BACKGROUND_PASS' not in (bus.OUT/('host_cancel_d'+str(dma)+'-run.log')).read_text():raise RuntimeError('Protocol gate')
    jobs=[]
    # Same DMA=8 for the full selected host comparison; no attribution to DMA changes.
    for variant in ['base','h2']:
        for k in ['linear','ffn']:
            jobs.append((variant,k,0,12))
        for first in [0,3,6,9]:jobs.append((variant,'encoder',first,3))
    def work(job):
        variant,k,first,count=job
        label='host_full_'+variant+'_'+k+('_'+str(first) if k=='encoder' else '')
        args=' +tasks='+str(count)+' +profile'
        if k=='encoder':args+=' +first='+str(first)+' +layers=12 +input_stream=1 +transport=2 +qkv_stats=0'
        return bus.linux(label+'-run',bus.exe(k,'host_'+('ref' if variant=='base' else variant)+'_d8_'+k)+args,14400)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(work,jobs))

if __name__=='__main__':main()
