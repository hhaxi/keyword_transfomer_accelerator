"""Validate matched FIFO observations and one output-merge RTL experiment."""
import hashlib
import json
from pathlib import Path
import re
from run_fifo_study import ROOT, OUT


def require(ok, message):
    if not ok:raise RuntimeError(message)


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    checks={}
    def log(name,marker):
        p=OUT/(name+'.log');s=p.read_text()
        require(marker in s and not re.search(r'(?i)(fatal:|%fatal|assertion failed)',s),'Incomplete/failed '+name)
        checks[p.relative_to(ROOT).as_posix()]={'sha256':digest(p),'marker':marker}
        return s

    def profile(mode,count):
        name='tb_encoder_fifo_'+mode
        s=log(name+'-run','ENC_SOC_')
        rows=re.findall(r'ENC_SOC_TASK_PASS task=(\d+) cycles=(\d+) baseline=0 outputs=6336 transport=2',s)
        require([int(t) for t,c in rows]==list(range(count)),'Task coverage '+mode)
        require('ENC_SOC_PASS tasks='+str(count) in s or 'ENC_SOC_SHARDS_PASS tasks='+str(count) in s,'Final marker '+mode)
        layers=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in s.splitlines() if line.startswith('FIFO_PROFILE ')]
        require([(d['task'],d['layer']) for d in layers]==[(t,l) for t in range(count) for l in range(12)],'Layer coverage '+mode)
        states=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in s.splitlines() if line.startswith('FFN_STATE ')]
        occupancy=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in s.splitlines() if line.startswith('FIFO_OCCUPANCY ')]
        phase=[tuple(map(int,m)) for m in re.findall(r'ENC_PHASE task=(\d+) layer=(\d+) op=(\d+) index=(\d+) value=(\d+)',s)]
        stats=[tuple(map(int,m)) for m in re.findall(r'ENC_LAYER_STATS task=(\d+) layer=(\d+) index=(\d+) value=(\d+)',s)]
        require(len(phase)==count*12*20 and len(stats)==count*12*8,'Phase telemetry coverage')
        for d in layers:
            t,l=d['task'],d['layer']
            require(d['push']==d['pop']==d['accept']==6336 and d['peak']<=4,'Transfer count')
            require(d['transfer_cycles']+d['duplex']==12672,'Transfer cycle conservation')
            require(d['empty_wait']==d['initial_wait']+d['between_wait'],'Wait split')
            require(d['tail_total']==sum(d[k] for k in ['initial_wait','between_wait','accept','residual_control','ln2','output','other']) and d['other']==0,'Tail partition')
            require(d['mac']==202752,'MAC count changed')
            ss={x['state']:x['cycles'] for x in states if (x['task'],x['layer'])==(t,l)}
            oo={x['count']:x['cycles'] for x in occupancy if (x['task'],x['layer'])==(t,l)}
            require(set(ss)==set(range(10)) and set(oo)==set(range(5)),'Histogram coverage')
            d['ffn_state_cycles']=ss;d['occupancy_cycles']=oo
            v={i:n for a,b,i,n in stats if (a,b)==(t,l)}
            for op in range(2):
                p={i:n for a,b,o,i,n in phase if (a,b,o)==(t,l,op)}
                require(set(p)==set(range(10)) and sum(p.values())==v[op],'Phase conservation')
            require(v[1]==d['tail_total'] and v[2]==d['ffn_cycles'] and v[7]==0,'SoC counters')
            require(v[3]==(23040 if l==0 else 16704) and v[4]==(9504 if l==11 else 3168),'DMA traffic changed')
        inputs_path=OUT/(name+'-inputs.json');inputs=json.loads(inputs_path.read_text())
        checks[inputs_path.relative_to(ROOT).as_posix()]={'sha256':digest(inputs_path),'marker':'pre-build input fingerprint'}
        return dict(tasks=[dict(task=int(t),cycles=int(c)) for t,c in rows],layers=layers,inputs=inputs)

    base=profile('baseline',1);candidate=profile('candidate',12)
    frozen=json.loads((ROOT/'docs/frontend-transfer-validation.json').read_text())
    require(base['tasks'][0]['cycles']==14561648,'Observer perturbed frozen baseline')
    require(base['inputs']['firmware_sha256']==candidate['inputs']['firmware_sha256'],'Different firmware')
    require(base['inputs']['firmware_sha256']==frozen['firmware_sha256'],'Firmware differs from frozen v3')
    require(base['inputs']['vectors']==candidate['inputs']['vectors'],'Different vectors')
    require(all(frozen['vector_sha256'].get(p)==h for p,h in base['inputs']['vectors'].items()),'Vectors differ from frozen v3')
    changes=[p for p,h in base['inputs']['sources'].items() if p.startswith(('rtl/','integration/','firmware/')) and candidate['inputs']['sources'].get(p)!=h]
    require(changes in ([],['rtl/kwt_accel.sv']),'Unexpected datapath/firmware changes: '+str(changes))
    if changes:
        old=json.loads((ROOT/'docs/frontend-transfer-validation.json').read_text())
        require(base['inputs']['sources']['rtl/kwt_accel.sv']==old['sources_sha256']['rtl/kwt_accel.sv'],'Baseline is not frozen v3')
    else:
        require('KWT_BASELINE_OUTPUT_MERGE' in base['inputs']['compile_defines'] and 'KWT_BASELINE_OUTPUT_MERGE' not in candidate['inputs']['compile_defines'],'Missing A/B compile switch')
    for p,h in candidate['inputs']['sources'].items():
        if p.startswith(('rtl/','integration/','firmware/','tests/')):
            require(hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==h,'Stale source '+p)
    for a,b in zip(base['layers'],candidate['layers'][:12]):
        require(a['ffn_cycles']-b['ffn_cycles']==792 and a['empty_wait']-b['empty_wait']==792,'Unexpected FFN/consumer wait reduction')
        require(a['ffn_state_cycles'][9]-b['ffn_state_cycles'][9]==792,'Merge cycles')
        for k in ['full_wait','push','pop','transfer_cycles','duplex','peak','accept','residual_control','ln2','other','mac','parameter_wait']:
            require(a[k]==b[k],'Unexpected changed metric '+k)
    require(all(t['cycles']<base['tasks'][0]['cycles'] for t in candidate['tasks']),'No full-task speedup')
    require(len({t['cycles'] for t in candidate['tasks']})==1,'Unexpected input-dependent task cycles')
    independent={}
    for name,top,limit in [('linear','tb_soc',170236),('ffn','tb_soc_ffn',306703)]:
        s=log(top+'_encoder_compat-run','SOC_PASS tasks=12')
        rows=re.findall(r'SOC_TASK_PASS task=(\d+) cycles=(\d+) outputs=',s)
        require([int(t) for t,c in rows]==list(range(12)) and max(int(c) for t,c in rows)<=limit,'Independent regression')
        independent[name]={'baseline_cycles':limit,'cycles':[int(c) for t,c in rows]}
    for name,marker in {
        'tb_accel-run':'ACCEL_PASS 12', 'tb_ffn_edges-run':'FFN_EDGES_PASS cases=3',
        'tb_ffn-run':'FFN_PASS','tb_dma-run':'DMA_PASS',
        'tb_ffn_transport-run':'abort_drain error_drain cancellation restart',
        'tb_ffn_transport_ideal-run':'read_streak=19872 write_streak=5',
        'icarus-accel':'ACCEL_PASS 1', 'icarus-tb_ffn_edges':'FFN_EDGES_PASS cases=3',
        'icarus-tb_ffn':'FFN_PASS','icarus-tb_dma':'DMA_PASS',
        'icarus-tb_ffn_transport':'abort_drain error_drain cancellation restart',
    }.items():log(name,marker)
    require(not (OUT/'encoder-lint.log').read_text().strip(),'Lint failed')
    checks['output/design/encoder-lint.log']={'sha256':digest(OUT/'encoder-lint.log'),'marker':'empty strict lint log'}
    for p,h in frozen['frozen_numeric_sha256'].items():require(digest(ROOT/p)==h,'Numeric contract changed')
    archive_record=json.loads((ROOT/'docs/fifo-study-baseline.json').read_text())
    archives={}
    for prefix in ['source','artifact']:
        p=ROOT/archive_record[prefix+'_archive']
        archives[p.relative_to(ROOT).as_posix()]={'available_locally':p.exists(),'expected_sha256':archive_record[prefix+'_sha256']}
        if p.exists():require(digest(p)==archive_record[prefix+'_sha256'],'Frozen archive changed '+str(p))
    report=dict(version='encoder-v4/ffn-v10',scope='Frontend RTL observation and output-merge scheduling; no fresh synthesis/netlist/PPA',
                baseline_commit='59487c7eb255ce8281185f1338d616b9c3f5e245',
                baseline=base,candidate=candidate,independent=independent,checks=checks,
                cycle_saving=base['tasks'][0]['cycles']-candidate['tasks'][0]['cycles'],
                cycle_reduction_percent=100*(base['tasks'][0]['cycles']-candidate['tasks'][0]['cycles'])/base['tasks'][0]['cycles'],
                fifo_counters='RTL-only observer; no synthesized MMIO counters or additional CPU accesses',
                traffic_words32=489600,mac_lanes=16,baseline_archive='docs/fifo-study-baseline.json',
                baseline_archives=archives,
                frozen_numeric_sha256=frozen['frozen_numeric_sha256'],
                pending='LN1-to-FFN input streaming not implemented; requires a separate single-layer readiness/backpressure/cancel experiment',passed=True)
    (ROOT/'docs/fifo-study-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FIFO_STUDY_PASS',json.dumps({'baseline':base['tasks'][0]['cycles'],'candidate':candidate['tasks'][0]['cycles'],'independent':independent}))
    return report


if __name__=='__main__':main()
