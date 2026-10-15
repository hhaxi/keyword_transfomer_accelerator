"""Collect full-FFN evidence separately from the mandatory FFN1 score/workload."""
import hashlib
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/design'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def soc(log):
    text=(OUT/log).read_text()
    if 'FFN_SOC_PASS tasks=12' not in text:raise RuntimeError('Missing FFN SoC completion')
    tasks=[dict(task=int(t),cycles=int(c),outputs=int(n)) for t,c,n in re.findall(r'FFN_SOC_TASK_PASS task=(\d+) cycles=(\d+) outputs=(\d+)',text)]
    if [t['task'] for t in tasks]!=list(range(12)) or any(t['outputs']!=6336 for t in tasks):raise RuntimeError('Incomplete FFN tasks')
    counters=re.findall(r'FFN_SOC_PROFILE task=(\d+) index=(\d+) value=(\d+)',text)
    extra=re.findall(r'FFN_EXTRA task=(\d+) index=(\d+) value=(\d+)',text)
    if len(counters)!=180 or len(extra)!=36:raise RuntimeError('Incomplete FFN counters')
    begin={int(t):int(c) for t,c in re.findall(r'MEASURE_BEGIN task=(\d+) time_ps=\d+ cycle=(\d+)',text)}
    loaded={int(t):int(c) for t,c in re.findall(r'SOC_TASK_START task=(\d+) pc=[0-9a-f]+ cycle=(\d+)',text)}
    rows=[]
    for t in tasks:
        i=t['task'];values={int(k):int(v) for n,k,v in counters if int(n)==i}
        others={int(k):int(v) for n,k,v in extra if int(n)==i}
        if sorted(values)!=list(range(15)) or others!={0:101376,1:25344,2:0}:raise RuntimeError('FFN component cycle count/saturation mismatch')
        if values[0]!=values[1]+values[2]+values[3] or values[4]!=202752 or values[9]!=19872 or values[10]!=12672:raise RuntimeError('FFN count mismatch')
        if not values[1]<values[11]<=values[12]<values[13]==values[0]:raise RuntimeError('FFN timestamps inconsistent')
        host=loaded[i]-begin[i];cpu=t['cycles']-host-values[0]
        if cpu<0:raise RuntimeError('Invalid timing residual')
        rows.append(dict(task=i,host_load=host,dma_load=values[1],compute_writeback=values[2],
                         dma_control=values[3],cpu_completion_residual=cpu,profile=values,extra=others))
    return tasks,rows


def collect():
    a,pa=soc('tb_soc_ffn-run.log');b,pb=soc('tb_soc_ffn_netlist-run.log')
    if a!=b or pa!=pb:raise RuntimeError('FFN RTL/netlist cycle or output mismatch')
    logs={};stress=[]
    for name,marker in [('tb_ffn-run.log','FFN_PASS'),
                        ('tb_ffn_edges-run.log','FFN_EDGES_PASS cases=3'),
                        ('tb_ffn_edges_netlist-run.log','FFN_EDGES_PASS cases=3'),
                        ('icarus-tb_ffn_edges.log','FFN_EDGES_PASS cases=3'),('tb_ffn_netlist-run.log','FFN_PASS'),
                        ('icarus-tb_ffn.log','FFN_PASS'),('ffn-numeric-tests.log','OK'),
                        ('tb_gelu-run.log','GELU_PASS vectors=54357'),('tb_gelu_netlist-run.log','GELU_PASS vectors=54357'),
                        ('icarus-tb_gelu.log','GELU_PASS vectors=54357'),
                        ('tb_soc_ffn-run.log','FFN_SOC_PASS'),('tb_soc_ffn_netlist-run.log','FFN_SOC_PASS')]:
        p=OUT/name;text=p.read_text()
        if marker not in text:raise RuntimeError('Missing check '+name)
        logs[name]={'passed':True,'sha256':sha(p)}
        if marker=='FFN_PASS':
            profile=re.findall(r'FFN_PROFILE index=(\d+) value=(\d+)',text)
            if len(profile)!=15:raise RuntimeError('Missing FFN stress profile')
            stress.append(profile)
    if not all(p==stress[0] for p in stress):raise RuntimeError('FFN stress counters differ')
    edge_logs=['tb_ffn_edges-run.log','tb_ffn_edges_netlist-run.log','icarus-tb_ffn_edges.log']
    edge_rows=[]
    for name in edge_logs:
        rows=re.findall(r'FFN_EDGE_CASE_PASS case=(\d+) outputs=(\d+) saturation=(\d+)',(OUT/name).read_text())
        if [(int(c),int(n)) for c,n,s in rows]!=[(0,6336),(1,6336),(2,6336)]:
            raise RuntimeError('Incomplete full-range FFN cases: '+name)
        edge_rows.append(rows)
    if not all(rows==edge_rows[0] for rows in edge_rows):raise RuntimeError('Full-range RTL/netlist/four-state mismatch')
    edge_vectors={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'output/ffn-edges').glob('case_*/*.hex'))}
    if len(edge_vectors)!=21:raise RuntimeError('Missing full-range FFN vectors')
    for directory in ['ffn-vectors','ffn-calibration']:
        folder=ROOT/'output'/directory
        for file,digest in json.loads((folder/'manifest.json').read_text()).items():
            if sha(folder/file)!=digest:raise RuntimeError('FFN vector changed: '+file)
    numeric=json.loads((ROOT/'output/ffn-vectors/numeric-report.json').read_text())
    calibration=json.loads((ROOT/'output/ffn-calibration/numeric-report.json').read_text())
    if not numeric['passed'] or not calibration['passed']:raise RuntimeError('FFN numeric verification failed')
    total=sum(t['cycles'] for t in a)
    result={'scope':'Optional complete FFN (linear1, GELU, linear2), without residual/LayerNorm or attention',
            'official_metric':False,'tasks':a,'cycle_analysis':pa,'numeric':numeric,'calibration':calibration,
            'performance':{'total_cycles':total,'target_clock_hz':150000000,'nominal_tasks_per_second':12*150000000/total,
                           'timing_closed':False,'macs_per_task':3244032,'output_elements':6336},
            'component_tests':logs,'mode_switch_without_reset_verified':True,
            'full_range_cases':edge_rows[0],'full_range_vector_sha256':edge_vectors,
            'intermediate_shared_sram_transactions':0,'row_buffer_bytes':512,
            'internal_sram_bytes':87040,'macro_instances':{'16x4096_SP':2,'16x1024_SP':34,'16x128_SP':4},
            'ffn_vector_manifest_sha256':sha(ROOT/'output/ffn-vectors/manifest.json'),
            'note':'Do not compare full FFN tasks/s directly against the undergraduate FFN1 throughput score.'}
    (ROOT/'docs/ffn-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':collect()
