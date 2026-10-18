"""Parse and cross-check host loading, bus accounting and numerical regressions."""
import json
import re
import argparse
import hashlib
import zipfile
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/design'
CAUSES=['slot_target','slot_sink','target','dma_slot','dma_peer','grant_ifu','grant_poll','grant_cpu','grant_host','grant_ffn','grant_enc','other']

def rows(text,tag):
    return [{k:(v if k=='ordered_hash' else int(v)) for k,v in re.findall(r'(\w+)=([0-9a-f]+)',line)}
            for line in text.splitlines() if line.startswith(tag+' ')]

def parse(path,complete_file=True):
    text=path.read_text()
    assert ('SOC_PASS tasks=' if complete_file else 'SOC_TASK_PASS task=') in text,path
    completed=[]
    for line in text.splitlines():
        if re.match(r'(?:ENC_|FFN_)?SOC_TASK_PASS ',line):
            completed+=rows(line,line.split()[0])
    result=[]
    for done in completed:
        task=done['task']
        def taskrows(tag):return [r for r in rows(text,tag) if r['task']==task]
        h=taskrows('HOST_CLASS');b=taskrows('BUS_SOURCE');w=taskrows('BUS_WINDOW')
        account=taskrows('HOST_ACCOUNTING_PASS')[0];ba=taskrows('BUS_ACCOUNTING_PASS')[0]
        assert len(h)==5 and len(b)==8 and len(w)==11
        assert sum(r['accepted'] for r in h)==b[3]['accepted']==account['calls']
        assert sum(r['wait'] for r in h)==sum(b[3][c] for c in CAUSES)
        assert sum(r['call_cycles'] for r in h)+account['outside_calls']==done['cycles']==ba['cycles']
        assert all(r['call_cycles']==3*r['accepted']+r['wait'] and r['accepted']==r['retired'] for r in h)
        phases=taskrows('ENC_PHASE');profiles=taskrows('SOC_PROFILE') or taskrows('FFN_SOC_PROFILE')
        poll_interval=1024 if phases else 512
        assert account['outside_calls']==poll_interval*h[3]['accepted']
        hardware=sum(r['value'] for r in phases) if phases else next(r['value'] for r in profiles if r['index']==0)
        if phases:
            assert hardware==sum(r['value'] for r in taskrows('ENC_LAYER_STATS') if r['index'] in [0,1])
        else:
            assert sum(sum(s[c] for c in CAUSES) for s in b[4:])==next(r['value'] for r in profiles if r['index']==7)
        assert all(s['other']==0 for s in b)
        load=sum(r['call_cycles'] for r in h[:2]);budget=sum(r['wait']-r['wait_overlap'] for r in h[:2])
        result.append(dict(task=task,cycles=done['cycles'],hardware_cycles=hardware,host=h,bus=b,windows=w,
                           host_account=account,bus_account=ba,load_cycles=load,
                           unhidden_host_wait_budget=budget,load_words=sum(r['accepted'] for r in h[:2]),
                           poll_interval=poll_interval,
                           dma_words=sum(r['accepted'] for r in b[4:]),
                           checked_layers=len(taskrows('INPUT_LINK')),
                           ln2_checks=taskrows('HOST_LN2_PASS'),layer_stats=taskrows('ENC_LAYER_STATS'),
                           qkv_checks=taskrows('QKV_ACCOUNTING_PASS'),
                           phases=phases,profiles=profiles))
    assert result,path
    return result

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def validate(data):
    receipts={name:json.loads((OUT/('host-'+name+'-inputs.json')).read_text()) for name in ['baseline','pilot','reference','protocol','full']}
    baseline=receipts['baseline']
    for name,r in receipts.items():
        assert r['vectors']==baseline['vectors'] and r['firmware']==baseline['firmware'],name
        if name!='baseline':
            for n,h in receipts['pilot']['sources'].items():
                if n.startswith(('rtl/','integration/','tests/')):assert r['sources'][n]==h,(name,n)
    for n,h in receipts['full']['sources'].items():
        if n.startswith(('rtl/','integration/','tests/','model/','firmware/')):
            assert hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==h,n
    allowed=['integration/kwt_bus_fabric.sv','integration/kwt_extended_system_bus.sv','integration/kwt_encoder_soc.sv']
    changed=subprocess.check_output(['git','diff','d9dc461','--name-only','--','rtl','integration','firmware','model'],cwd=str(ROOT),text=True).splitlines()
    assert sorted(changed)==sorted(allowed),changed
    original_baseline=True
    for n,h in baseline['sources'].items():
        if n.startswith(('rtl/','integration/')):
            original=subprocess.check_output(['git','show','d9dc461:'+n],cwd=str(ROOT)).replace(b'\r\n',b'\n')
            matches=hashlib.sha256(original).hexdigest()==h
            original_baseline &= matches
            if not matches:assert n in allowed and h==receipts['full']['sources'][n],n
    frozen=json.loads((ROOT/'docs/qkv-study-validation.json').read_text())['frozen_numeric_sha256']
    for n,h in frozen.items():assert sha(ROOT/n)==h,n
    for name,h in baseline['vectors'].items():assert sha(ROOT/name)==h,name
    for name,h in baseline['firmware'].items():assert sha(ROOT/name)==h,name
    archives={}
    for stage,r in receipts.items():
        path=ROOT/'deliverables'/('host-'+stage+'-sources.zip')
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None,path
            for n,h in r['sources'].items():assert hashlib.sha256(z.read(n).replace(b'\r\n',b'\n')).hexdigest()==h,(stage,n)
        archives[path.relative_to(ROOT).as_posix()]=sha(path)
    for path in (ROOT/'deliverables/d9dc461-baseline').glob('*.zip'):
        with zipfile.ZipFile(path) as z:assert z.testzip() is None,path
        archives[path.relative_to(ROOT).as_posix()]=sha(path)
    comparison={}
    for dma in [1,8]:
        for kind in ['linear','ffn','encoder']:
            pilot=data['host_h2_d%d_%s-run'%(dma,kind)][0]
            reference=(1231235 if dma==1 else 1225034) if kind=='encoder' else data['host_base_d%d_%s-run'%(dma,kind)][0]['cycles']
            assert pilot['cycles']<reference
            if kind=='encoder':assert len(pilot['qkv_checks'])==1 and pilot['qkv_checks'][0]['checked_values']==19008
        assert len(data['host_base_d%d_encoder-run'%dma][0]['qkv_checks'])==12
    for kind,words,dma_words in [('linear',11616,62304),('ffn',19872,32544),('encoder',407232,413568)]:
        sides={}
        for variant in ['base','h2']:
            prefix='host_full_'+variant+'_'+kind
            tests=sum((v for k,v in data.items() if k.startswith(prefix)),[])
            tests=sorted(tests,key=lambda r:r['task']);assert [r['task'] for r in tests]==list(range(12)),prefix
            for t in tests:
                assert t['load_words']==words and t['dma_words']==dma_words
                assert sum(r['active_overlap'] for r in t['host'][:2])==0
                if variant=='h2':assert t['unhidden_host_wait_budget']==0
                if kind=='encoder':
                    assert t['checked_layers']==12 and [r['layer'] for r in t['ln2_checks']]==list(range(12))
                    assert all(r['values']==6336 for r in t['ln2_checks'])
                    sat=[r for r in t['layer_stats'] if r['index']==7];assert len(sat)==12 and all(r['value']==0 for r in sat)
            sides[variant]=tests
        comparisons=[]
        for a,b in zip(sides['base'],sides['h2']):
            assert a['host_account']['ordered_hash']==b['host_account']['ordered_hash']
            assert b['cycles']<a['cycles']
            saved=a['cycles']-b['cycles'];load_saved=a['load_cycles']-b['load_cycles'];hw_saved=a['hardware_cycles']-b['hardware_cycles']
            control_saved=a['host'][2]['call_cycles']-b['host'][2]['call_cycles']
            poll_wait_saved=a['host'][3]['wait']-b['host'][3]['wait']
            poll_count_delta=a['host'][3]['accepted']-b['host'][3]['accepted']
            poll_sampling_delta=(a['poll_interval']+3)*poll_count_delta
            assert saved==load_saved+control_saved+poll_wait_saved+poll_sampling_delta
            comparisons.append(dict(task=a['task'],baseline=a['cycles'],candidate=b['cycles'],saved=saved,
                percent=100*saved/a['cycles'],load_saved=load_saved,hardware_saved=hw_saved,
                control_saved=control_saved,poll_wait_saved=poll_wait_saved,poll_count_delta=poll_count_delta,
                poll_sampling_delta=poll_sampling_delta,
                other_interval_saved=saved-load_saved-hw_saved))
        comparison[kind]=dict(tasks=comparisons,baseline_total=sum(t['cycles'] for t in sides['base']),
            candidate_total=sum(t['cycles'] for t in sides['h2']),
            max_wait_baseline=[max(t['bus'][s]['max_wait'] for t in sides['base']) for s in range(8)],
            max_wait_candidate=[max(t['bus'][s]['max_wait'] for t in sides['h2']) for s in range(8)])
        assert sides['base'][0]['cycles']==data['host_base_d8_'+kind+'-run'][0]['cycles']
        assert sides['base'][0]['bus']==data['host_base_d8_'+kind+'-run'][0]['bus']
        assert sides['base'][0]['windows']==data['host_base_d8_'+kind+'-run'][0]['windows']
        if kind!='encoder':assert sides['h2'][0]['bus']==data['host_h2_d8_'+kind+'-run'][0]['bus']
    protocol={}
    for d in [1,8]:
        for h in [0,2]:
            label='host_protocol_d%d_h%d'%(d,h)
            a=(OUT/(label+'-run.log')).read_text();b=(OUT/(label+'-icarus.log')).read_text()
            assert 'BUS_PASS' in a and 'BUS_PASS' in b
            fair=rows(a,'BUS_FAIR_PASS');assert len(fair)==15 and fair==rows(b,'BUS_FAIR_PASS')
            assert not (OUT/(label+'-lint.log')).read_text().strip()
            protocol[label]=fair
        text=(OUT/('host_cancel_d%d-run.log'%d)).read_text();cancel=rows(text,'INPUT_LINK_CANCEL_PASS');bg=rows(text,'HOST_BACKGROUND_PASS')[0]
        assert [c['phase'] for c in cancel]==[0,1,2] and 'INPUT_LINK_PASS' in text
        assert bg['requests']==bg['responses'] and bg['response_stalls']>0
        protocol['cancel_d'+str(d)]=dict(cancel=cancel,background=bg)
        for kind,expect in [('linear',167134 if d==1 else 165003),('ffn',305708 if d==1 else 301408),('encoder',1231235 if d==1 else 1225034)]:
            text=(OUT/('host_base_d%d_%s_off-run.log'%(d,kind))).read_text()
            assert 'SOC_PASS tasks=1' in text and re.search(r'SOC_TASK_PASS task=0 cycles='+str(expect)+r'\b',text)
            assert 'HOST_ACCOUNTING_PASS' not in text
    checks={p.relative_to(ROOT).as_posix():sha(p) for p in OUT.glob('host_*.log') if not p.name.startswith('host_debug')}
    for label in ['host_'+prefix+'_d'+str(d)+'_'+k for prefix,ds in [('base',[1,8]),('h2',[1,8]),('ref',[8])] for d in ds for k in ['linear','ffn','encoder']]:
        build=(OUT/(label+'-build.log')).read_text()
        assert 'make: Leaving directory' in build and not re.search(r'(?im)^%Error|fatal error:|^make(?:\[\d+\])?: \*\*\*|\berror:',build),label
    return dict(base_commit=baseline['base_commit'],actual_comparison=dict(DMA_BURST=8,HOST_BURST=[0,2],input_stream=1,transport=2),
                defaults=dict(DMA_BURST=1,HOST_BURST=0),comparison=comparison,protocol=protocol,
                frozen_numeric_sha256=frozen,receipts_sha256={n:sha(OUT/('host-'+n+'-inputs.json')) for n in receipts},
                original_baseline_production_matches_commit=original_baseline,
                tools=dict(verilator='5.020',cpu='pinned E203 RTL',synthesis_used=False),
                source_archives_sha256=archives,evidence_sha256=checks,experiments=data)

def package(report):
    paths=set()
    receipt=json.loads((OUT/'host-full-inputs.json').read_text())
    paths.update(ROOT/n for n in receipt['sources']);paths.update(ROOT/n for n in receipt['vectors']);paths.update(ROOT/n for n in receipt['firmware'])
    paths.update(p for p in OUT.glob('host_*.log') if not p.name.startswith('host_debug'));paths.update(OUT.glob('host-*-inputs.json'))
    paths.update(ROOT/n for n in ['scripts/run_host_study.py','scripts/collect_host_study.py','scripts/collect_bus_study.py',
                                 'docs/host-study.md','docs/host-study-validation.json','docs/qkv-study-validation.json','README.md'])
    paths.update((ROOT/'deliverables/d9dc461-baseline').glob('*'))
    paths.update((ROOT/'deliverables').glob('host-*-sources.zip'))
    paths.update((OUT/'firmware').glob('*'));paths.update((ROOT/'output/encoder-design/firmware').glob('*'))
    target=ROOT/'deliverables/host-study-d9dc461.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths) if p.is_file()}
        for n in manifest:z.write(ROOT/n,n)
        z.writestr('manifest.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(target) as z:assert z.testzip() is None
    target.with_suffix('.sha256.txt').write_text(sha(target)+'  '+target.name+'\n')
    print('PACKAGE',target,sha(target))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--partial',action='store_true');p.add_argument('--package',action='store_true');args=p.parse_args()
    data={p.stem:parse(p) for p in sorted(OUT.glob('host_*-run.log'))
          if 'SOC_PASS tasks=' in p.read_text() and 'HOST_ACCOUNTING_PASS' in p.read_text()}
    report=data if args.partial else validate(data)
    (ROOT/'docs/host-study-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    for label,tests in data.items():
        t=tests[0]
        print(label,len(tests),'cycles',t['cycles'],'load',t['load_cycles'],'wait budget',t['unhidden_host_wait_budget'])
    if args.package:
        assert not args.partial
        package(report)

if __name__=='__main__':main()
