"""Collect current input-stream evidence, rejecting incomplete or stale sources."""
import hashlib
import json
import re
from pathlib import Path
from run_encoder import ROOT,OUT,DEST


def sha(path,normalize=False):
    data=path.read_bytes()
    return hashlib.sha256(data.replace(b'\r\n',b'\n') if normalize else data).hexdigest()


def parse(name,layers,mode,tasks):
    text=(OUT/name).read_text();records={}
    pattern=r'ENC_SOC_TASK_PASS task=(\d+) cycles=(\d+) baseline=0 outputs=6336 transport=2 layers='+str(layers)+r' input_stream='+str(mode)
    for task,cycles in re.findall(pattern,text):records[int(task)]={'cycles':int(cycles),'layers':{}}
    if sorted(records)!=list(range(tasks)):raise RuntimeError('Task coverage: '+name)
    for task,layer,index,value in re.findall(r'ENC_LAYER_STATS task=(\d+) layer=(\d+) index=(\d+) value=(\d+)',text):
        records[int(task)]['layers'].setdefault(int(layer),{'stats':{},'link':{}})['stats'][int(index)]=int(value)
    for line in text.splitlines():
        if line.startswith('INPUT_LINK task='):
            row={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            records[row['task']]['layers'][row['layer']]['link']=row
    for task,layer,op,index,value in re.findall(r'ENC_PHASE task=(\d+) layer=(\d+) op=(\d+) index=(\d+) value=(\d+)',text):
        row=records[int(task)]['layers'][int(layer)]
        row.setdefault('phases',{}).setdefault(int(op),{})[int(index)]=int(value)
    for line in text.splitlines():
        if line.startswith('ENC_MEMORY task='):
            row={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            records[row['task']]['memory']=row
    for task,record in records.items():
        if sorted(record['layers'])!=list(range(layers)):raise RuntimeError('Layer coverage: '+name)
        traffic=0
        for layer,row in record['layers'].items():
            s=row['stats'];link=row['link']
            if sorted(s)!=list(range(8)) or s[7]!=0:raise RuntimeError('Stats/saturation')
            for op in [0,1]:
                phase=row.get('phases',{}).get(op,{})
                if sorted(phase)!=list(range(10)) or sum(phase.values())!=s[op]:raise RuntimeError('Phase accounting')
            if s[3]!=(23040 if layer==0 else 16704):raise RuntimeError('Encoder reads')
            if s[4]!=(6336 if layer==layers-1 else 0)+(0 if mode else 3168):raise RuntimeError('Encoder writes')
            if link.get('mode')!=mode or link['dma_reads']!=(16704 if mode else 19872) or link['words']!=(3168 if mode else 0):raise RuntimeError('FFN transfer accounting')
            traffic+=s[3]+s[4]+link['dma_reads']
        record['traffic_words32']=traffic
        if record['memory']['ffn_dma_read32']!=sum(r['link']['dma_reads'] for r in record['layers'].values()) or record['memory']['ffn_dma_write32']!=0:raise RuntimeError('DMA observation mismatch')
    if 'ENC_SOC_PASS tasks=' not in text:raise RuntimeError('Missing completion')
    return records


def main():
    evidence=json.loads((OUT/'input-study-inputs.json').read_text())
    for name,value in evidence['sources'].items():
        if sha(ROOT/name,True)!=value:raise RuntimeError('Source changed: '+name)
    if sha(DEST/'firmware/encoder.bin')!=evidence['firmware_sha256']:raise RuntimeError('Firmware changed')
    for name,value in evidence['vectors'].items():
        if sha(ROOT/name)!=value:raise RuntimeError('Vector changed: '+name)
    protocol_inputs=json.loads((OUT/'input-protocol-inputs.json').read_text())
    if any(evidence[k]!=protocol_inputs[k] for k in ['sources','firmware_sha256','vectors']):raise RuntimeError('Protocol provenance mismatch')
    checks={}
    def check(name,marker):
        path=OUT/name;text=path.read_text()
        if marker not in text or re.search(r'(^|\n)(%Error|FATAL:)',text):raise RuntimeError('Failed check: '+name)
        checks[path.relative_to(ROOT).as_posix()]={'sha256':sha(path),'marker':marker}
        return text
    single={};full={}
    for mode,label in [(0,'sram'),(1,'direct')]:
        name='tb_input_final'+('_direct' if mode else '')+'-run.log'
        check(name,'ENC_SOC_PASS tasks=1');single[label]=parse(name,1,mode,1)
        name='input_full_'+label+'-run.log'
        check(name,'ENC_SOC_PASS tasks=');full[label]=parse(name,12,mode,1 if mode==0 else 12)
    for label,marker in [('tb_ffn_input','FFN_INPUT_PASS'),('encoder_input','ENCODER_PASS layers=1'),('tb_input_link','INPUT_LINK_PASS'),
                         ('tb_encoder_faults','ENC_FAULTS_PASS'),('tb_dma_arbiter','ENC_ARBITER_PASS')]:
        for name in [label+'-run.log','icarus-'+label+'.log']:check(name,marker)
    if check('encoder-lint.log','').strip():raise RuntimeError('Strict lint emitted diagnostics')
    independent={}
    for label,pattern,expected in [('linear',r'SOC_TASK_PASS task=(\d+) cycles=(\d+)',167134),('ffn',r'FFN_SOC_TASK_PASS task=(\d+) cycles=(\d+)',305708)]:
        log='tb_soc'+('_ffn' if label=='ffn' else '')+'_encoder_compat-run.log'
        text=check(log,'SOC_PASS tasks=12')
        rows=[(int(t),int(c)) for t,c in re.findall(pattern,text)]
        if [t for t,c in rows]!=list(range(12)) or any(c!=expected for t,c in rows):raise RuntimeError('Independent regression')
        independent[label]={'cycles':expected,'tasks':12,'no_regression':True}
    frozen=json.loads((ROOT/'docs/evidence/fifo-study-validation.json').read_text())['frozen_numeric_sha256']
    for name,value in frozen.items():
        # Preserve the byte-exact numeric contract recorded by the prior report.
        data=(ROOT/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=value:raise RuntimeError('Frozen math changed '+name)
    comparisons={}
    for label,group in [('single',single),('twelve',full)]:
        a=group['sram'][0];b=group['direct'][0]
        if b['cycles']>=a['cycles'] or b['traffic_words32']>=a['traffic_words32']:raise RuntimeError('No benefit: '+label)
        comparisons[label]={'saved_cycles':a['cycles']-b['cycles'],'cycle_reduction_percent':100*(a['cycles']-b['cycles'])/a['cycles'],
                            'saved_words32':a['traffic_words32']-b['traffic_words32'],'traffic_reduction_percent':100*(a['traffic_words32']-b['traffic_words32'])/a['traffic_words32']}
    checks['output/design/input-study-inputs.json']={'sha256':sha(OUT/'input-study-inputs.json'),'marker':'source/firmware/vector hashes'}
    checks['output/design/input-protocol-inputs.json']={'sha256':sha(OUT/'input-protocol-inputs.json'),'marker':'protocol inputs match'}
    for name in ['input-full-inputs.json','input-full-sram-inputs.json']:
        path=OUT/name;inputs=json.loads(path.read_text())
        if any(evidence[k]!=inputs[k] for k in ['sources','firmware_sha256','vectors']):raise RuntimeError('Full-run provenance mismatch')
        checks[path.relative_to(ROOT).as_posix()]={'sha256':sha(path),'marker':'matched full-run inputs'}
    report={'version':'encoder-v5-input-stream','base_commit':evidence['base_commit'],'source_hash_method':'SHA-256 after CRLF to LF; vectors, firmware and numeric contracts use raw bytes','single':single,'twelve':full,
            'comparison':comparisons,'independent':independent,'checks':checks,'inputs':evidence,'frozen_numeric_sha256':frozen,
            'scope':'Front-end RTL only. Matched current firmware/executable; SRAM mode is the b716312 data path. Historical b716312 firmware has a different control schedule.',
            'pending':['synthesis','netlist regression','official PPA','official evaluation'],'passed':True}
    (ROOT/'docs/evidence/input-stream-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(comparisons,indent=2));return report

if __name__=='__main__':main()
