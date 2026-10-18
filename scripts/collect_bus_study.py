"""Verify bus attribution, bounded arbitration, regression and input provenance."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from run_bus_study import ROOT,OUT,DEST,BASE,sha

CAUSES=['accepted','slot_target','slot_sink','target','dma_slot','dma_peer',
        'grant_ifu','grant_poll','grant_cpu','grant_host','grant_ffn','grant_enc','other']
SOURCES=['cpu_ifetch','cpu_status_read','cpu_other','host','ffn_read','ffn_write','encoder_read','encoder_write']
WINDOWS=['ffn_initial_or_preload','ffn_overlapped_read','ffn_write','encoder_x','encoder_parameters',
         'encoder_q_weights','encoder_k_weights','encoder_v_weights','encoder_o_weights','encoder_output','encoder_tail_read']


def rows(text,tag):
    return [dict((k,int(v)) for k,v in re.findall(r'(\w+)=(\d+)',line)) for line in text.splitlines() if line.startswith(tag+' ')]


def require(ok,message):
    if not ok:raise RuntimeError(message)


def collect():
    checks={}
    def log(name,marker):
        p=OUT/(name+'.log');t=p.read_text()
        require(marker in t and '%Error' not in t and 'FATAL' not in t,'Failed/missing log '+name)
        checks[p.relative_to(ROOT).as_posix()]=sha(p)
        return t
    receipts={n:json.loads((OUT/('bus-'+n+'-inputs.json')).read_text()) for n in ['baseline','pilot','reference','protocol','full']}
    target=receipts['pilot']
    for stage,r in receipts.items():
        require(r['vectors']==target['vectors'] and r['firmware']==target['firmware'],'Data changed '+stage)
        if stage!='baseline':
            require({n:h for n,h in r['sources'].items() if not n.startswith('scripts/')}==
                    {n:h for n,h in target['sources'].items() if not n.startswith('scripts/')},'Compiled sources changed '+stage)
        path=OUT/('bus-'+stage+'-inputs.json');checks[path.relative_to(ROOT).as_posix()]=sha(path)
    for n,h in target['sources'].items():
        if not n.startswith('scripts/'):
            require(hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==h,'Current source changed '+n)
    for n,h in dict(target['vectors'],**target['firmware']).items():require(sha(ROOT/n)==h,'Current data changed '+n)
    frozen=json.loads((ROOT/'docs/qkv-study-validation.json').read_text())['frozen_numeric_sha256']
    for n,h in frozen.items():require(sha(ROOT/n)==h,'Frozen arithmetic changed '+n)
    changed=subprocess.check_output(['git','diff',BASE,'--name-only','--','rtl','integration','firmware','model'],cwd=str(ROOT)).decode().splitlines()
    require(set(changed)=={'integration/kwt_bus_fabric.sv','integration/kwt_extended_system_bus.sv','integration/kwt_encoder_soc.sv'},'Unexpected production changes')
    baseline_files=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'rtl','integration','firmware','model'],cwd=str(ROOT)).decode().splitlines()
    original_production=True
    for n in baseline_files:
        if n in receipts['baseline']['sources']:
            content=subprocess.check_output(['git','show',BASE+':'+n],cwd=str(ROOT))
            original=hashlib.sha256(content.replace(b'\r\n',b'\n')).hexdigest()
            actual=receipts['baseline']['sources'][n]
            original_production &= original==actual
            # A later reproduction may rebuild the default parameter from the
            # updated source. Distinguish that from the archived original run.
            require(actual==original or (n in changed and actual==target['sources'][n]),'Unexpected baseline source '+n)

    def experiment(label,kind,tasks,layers=12,observer=True):
        text=log(label+'-run','SOC_PASS tasks='+str(tasks))
        tag='ENC_SOC_TASK_PASS' if kind=='encoder' else 'FFN_SOC_TASK_PASS' if kind=='ffn' else 'SOC_TASK_PASS'
        result=rows(text,tag)
        require([r['task'] for r in result]==list(range(tasks)),'Missing task result '+label)
        src=rows(text,'BUS_SOURCE');slot=rows(text,'BUS_SLOT');windows=rows(text,'BUS_WINDOW');account=rows(text,'BUS_ACCOUNTING_PASS')
        if not observer:
            require(not src and not slot and not windows and not account,'Observer did not disable')
            return dict(cycles=[r['cycles'] for r in result],observer=False)
        require(len(src)==tasks*8 and len(slot)==tasks*8 and len(windows)==tasks*11 and len(account)==tasks,'Incomplete bus census '+label)
        case_metrics=[]
        for task in range(tasks):
            s=[r for r in src if r['task']==task];p=[r for r in slot if r['task']==task];w=[r for r in windows if r['task']==task];a=[r for r in account if r['task']==task]
            require([r['source'] for r in s]==list(range(8)) and [r['source'] for r in p]==list(range(8)) and [r['window'] for r in w]==list(range(11)),'Duplicate census rows')
            require(len(a)==1 and a[0]['cycles']==result[task]['cycles'],'Clock window mismatch')
            require(a[0]['slot_idle']+sum(r[k] for r in p for k in ['target','sink','retire'])==a[0]['cycles'],'Slot partition does not close')
            require(all(r['other']==0 for r in s+w),'Unclassified stalls')
            for k in CAUSES:require(sum(r[k] for r in s[4:])==sum(r[k] for r in w),'DMA window totals differ')
            traffic=sum(r['accepted'] for r in s[4:])
            expected=46080 if kind=='encoder' and layers==1 else 413568 if kind=='encoder' else 62304 if kind=='linear' else 32544
            require(traffic==expected,'DMA traffic changed')
            require(max(r['max_wait'] for r in s[:4])<=9,'Other master wait exceeded arbitration allowance')
            case_metrics.append(dict(task=task,cycles=result[task]['cycles'],dma_words32=traffic,
                                     max_wait=[r['max_wait'] for r in s],dma_request_stalls=sum(r[k] for r in s[4:] for k in CAUSES[1:]),
                                     serial_dma_stall_union=a[0]['serial_dma_stall_union'],all_request_stall_union=a[0]['stall_union']))
        if kind=='encoder':
            q=rows(text,'QKV_ACCOUNTING_PASS');phase=rows(text,'ENC_PHASE');layerstats=rows(text,'ENC_LAYER_STATS');link=rows(text,'INPUT_LINK')
            require(len(q)==tasks*layers and len(link)==tasks*layers and len(layerstats)==8*tasks*layers,'Missing per-layer checks')
            require(all(r['checked_values']==19008 and r['phase']==308886 for r in q),'QKV arithmetic changed')
            require(all(r['value']==0 for r in layerstats if r['index']==7),'Encoder saturated')
            require(len(phase)==20*tasks*layers,'Missing stage counters')
            for task in range(tasks):
                encoder_stalls=sum(r[k] for r in src if r['task']==task and r['source']>=6 for k in CAUSES[1:])
                require(encoder_stalls==sum(r['request'] for r in rows(text,'ENC_DMA_WAIT') if r['task']==task),'Encoder hardware request counter differs')
            profile=[];overlap=[]
        else:
            phase=[];link=[]
            profile=rows(text,'SOC_PROFILE' if kind=='linear' else 'FFN_SOC_PROFILE')
            overlap=rows(text,'FFN_OVERLAP')
            require(len(profile)==15*tasks,'Missing hardware DMA profile')
            for task in range(tasks):
                require([r['value'] for r in profile if r['task']==task and r['index']==7]==[case_metrics[task]['dma_request_stalls']],'FFN hardware request counter differs')
        return dict(cycles=[r['cycles'] for r in result],observer=True,cases=case_metrics,
                    task0=dict(sources=[r for r in src if r['task']==0],slots=[r for r in slot if r['task']==0],
                               windows=[r for r in windows if r['task']==0],account=account[0]),phases=phase,link=link,
                    hardware_profile=profile,ffn_overlap=overlap)

    experiments={};comparison={}
    for kind,expected in [('linear',167134),('ffn',305708),('encoder',14315119)]:
        base=experiment('bus_baseline_'+kind,kind,1)
        off=experiment('bus_baseline_'+kind+'_off',kind,1,observer=False)
        ref=experiment('bus_reference_'+kind,kind,1 if kind=='encoder' else 12)
        opt=experiment('bus_full_'+kind,kind,1 if kind=='encoder' else 12)
        require(base['cycles']==off['cycles']==[expected] and all(c==expected for c in ref['cycles']),'Baseline/default regression '+kind)
        require(ref['task0']==base['task0'],'Default parameter changed attribution '+kind)
        require(all(c<expected for c in opt['cycles']),'No full-task benefit '+kind)
        experiments[kind]=dict(original=base,observer_off=off,reference=ref,burst8=opt)
        saved=expected-opt['cycles'][0]
        comparison[kind]=dict(reference=expected,burst8=opt['cycles'][0],saved=saved,reduction_percent=saved/expected*100,
                              reference_max_wait=ref['cases'][0]['max_wait'],burst8_max_wait=opt['cases'][0]['max_wait'])
    single_ref=experiment('bus_reference_encoder_single','encoder',1,layers=1)
    single_opt=experiment('bus_burst8_encoder','encoder',1,layers=1)
    require(single_ref['cycles']==[1231235] and single_opt['cycles'][0]<1231235,'Single-layer gate')
    experiments['encoder_single']=dict(reference=single_ref,burst8=single_opt)
    for kind in ['linear','ffn']:
        pilot=experiment('bus_burst8_'+kind,kind,1)
        require(pilot['cycles'][0]==comparison[kind]['burst8'],'Pilot/expanded mismatch')

    critical_path={}
    for kind,data_words in [('linear',11616),('ffn',19872),('encoder',407232)]:
        ref=experiments[kind]['reference'];opt=experiments[kind]['burst8']
        def hw(x):
            if kind=='encoder':return sum(p['value'] for p in x['phases'])
            return next(p['value'] for p in x['hardware_profile'] if p['task']==0 and p['index']==0)
        host=ref['task0']['sources'][3];host_wait=sum(host[c] for c in CAUSES[1:])
        critical_path[kind]=dict(hardware_command_cycles_reference=hw(ref),hardware_command_cycles_burst8=hw(opt),
            hardware_command_saved=hw(ref)-hw(opt),other_task_interval_saved=comparison[kind]['saved']-(hw(ref)-hw(opt)),
            serial_dma_stall_saved=ref['cases'][0]['serial_dma_stall_union']-opt['cases'][0]['serial_dma_stall_union'],
            optimistic_all_dma_request_wait_budget=ref['cases'][0]['dma_request_stalls'],
            budget_percent=ref['cases'][0]['dma_request_stalls']/ref['cycles'][0]*100,
            host_data_words=data_words,host_serial_data_wait_lower=max(0,host_wait-(host['accepted']-data_words)*host['max_wait']),
            host_serial_data_wait_upper=host_wait,
            caveat='Wait-event budgets can overlap hidden work; they are not promised whole-task savings. Other task interval includes host loading, CPU handoff and completion polling.')
    protocols={}
    for b in [1,8]:
        fair=[]
        for suffix in ['-run','-icarus']:
            t=log('bus_protocol_'+str(b)+suffix,'BUS_PASS')
            r=rows(t,'BUS_FAIR_PASS');require(len(r)==6,'Missing fairness scenarios')
            for row in r:require(row['max_bypasses']<=(2 if row['master']==2 else b+1),'Fairness violation')
            fair.append(r)
        require(fair[0]==fair[1],'Simulator fairness disagreement')
        t=log('bus_cancel_'+str(b)+'-run','INPUT_LINK_PASS')
        require([r['phase'] for r in rows(t,'INPUT_LINK_CANCEL_PASS')]==[0,1,2],'Cancellation coverage')
        require(not log('bus-lint-'+str(b),'').strip(),'Strict lint diagnostics')
        protocols[str(b)]=dict(fairness=fair[0],cancel_phases=[0,1,2],restart_bit_exact=True)
        generated=DEST/('bus_cancel_'+str(b)+'.sv')
        expected=(ROOT/'tests/tb_input_link.sv').read_text().replace('kwt_extended_system_bus dut(',
                 'kwt_extended_system_bus #(.DMA_BURST('+str(b)+')) dut(')
        require(generated.read_text()==expected,'Generated protocol test changed')
        checks[generated.relative_to(ROOT).as_posix()]=sha(generated)
    archives={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'deliverables/c0724ce-baseline').glob('*.zip')}
    require(len(archives)==3,'Baseline archives missing')
    for label in ['bus_baseline_'+k for k in ['linear','ffn','encoder']]+['bus_burst8_'+k for k in ['linear','ffn','encoder']]+['bus_reference_'+k for k in ['linear','ffn','encoder']]+['bus_protocol_1','bus_protocol_8','bus_cancel_1','bus_cancel_8']:
        log(label+'-build','make: Leaving directory')
    for stage in ['pilot','reference','protocol','full']:
        path=ROOT/'deliverables'/('bus-'+stage+'-sources.zip')
        with zipfile.ZipFile(path) as z:
            require(z.testzip() is None,'Source archive CRC')
            for name,digest in receipts[stage]['sources'].items():
                require(hashlib.sha256(z.read(name).replace(b'\r\n',b'\n')).hexdigest()==digest,'Archived source differs '+name)
        archives[path.relative_to(ROOT).as_posix()]=sha(path)
    report=dict(base_commit=BASE,original_baseline_production_matches_commit=original_production,
                default_dma_burst=1,candidate_dma_burst=8,sources=SOURCES,causes=CAUSES,windows=WINDOWS,
                comparison=comparison,critical_path=critical_path,experiments=experiments,protocols=protocols,frozen_numeric_sha256=frozen,
                baseline_archives=archives,checks_sha256=checks,
                scope='RTL cycles only; task 0 twelve-layer encoder, 12 independent Linear tasks and 12 independent FFN tasks per parameter; no new PPA results',passed=True)
    (ROOT/'docs/bus-study-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(comparison,indent=2))
    return report


def package():
    r=collect();files={ROOT/n for n in r['checks_sha256']}
    receipt=json.loads((OUT/'bus-full-inputs.json').read_text())
    files.update(ROOT/n for n in receipt['sources'])
    files.update(ROOT/n for n in receipt['firmware'])
    files.update(ROOT/n for n in ['README.md','docs/bus-study.md','docs/bus-study-validation.json','scripts/run_bus_study.py','scripts/collect_bus_study.py'])
    target=ROOT/'deliverables/bus-study-c0724ce.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        require(z.testzip() is None,'Archive CRC failed')
        for p in files:require(z.read(p.relative_to(ROOT).as_posix())==p.read_bytes(),'Archive differs '+str(p))
    target.with_suffix('.sha256.txt').write_text(sha(target)+'  '+target.name+'\n')
    print(str(target)+' SHA256='+sha(target))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',action='store_true');a=p.parse_args()
    if a.package:package()
    else:collect()
