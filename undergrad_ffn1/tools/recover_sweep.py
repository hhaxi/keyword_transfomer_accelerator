"""Patch area reporting and recover saved sweep DDCs. Never run synthesis."""
import argparse,csv,hashlib,itertools,json,os,re,shutil,subprocess,uuid
from pathlib import Path
from ppa_metrics import parse_reports

ROOT=Path(__file__).resolve().parents[1]
KEYS=('itcm','host_continuous','small_x','small_bias')
CHECKPOINTS={'i0_h0_x0_b0':'00_baseline','i1_h0_x0_b0':'01_itcm',
             'i1_h1_x0_b0':'02_host','i1_h1_x1_b0':'03_small_x','i1_h1_x1_b1':'04_bias'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def matrix_cases():
    return [dict(name='i%d_h%d_x%d_b%d'%bits,options=dict(zip(KEYS,map(bool,bits))))
            for bits in itertools.product((0,1),repeat=4)]

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    os.replace(str(temp),str(path))

def within(root,path):
    path=Path(path).resolve()
    try:path.relative_to(Path(root).resolve())
    except ValueError:raise ValueError('Recorded path escapes workspace: '+str(path))
    return path

def select_source(root,name,scope,status):
    root=Path(root).resolve();case=root/'experiments/cases'/name
    entry=next((r for r in reversed(status) if r.get('case')==name and r.get('scope')==scope),{})
    run=None;selection='latest_directory'
    if entry.get('report_relative'):
        report=within(root,root/entry['report_relative'])
        run=report.parent;selection='original_dc_status_report'
    elif entry.get('launch_log'):
        log=within(root,root/entry['launch_log'])
        if log.is_file():
            pattern=r'[/\\]run[/\\](\d{8}_\d{6}_\d+_'+scope+r')(?=[/\\\s]|$)'
            candidates=re.findall(pattern,log.read_text(errors='replace'))
            if candidates:run=case/'run'/candidates[-1];selection='original_dc_status_launch'
    if run is None:
        if entry:
            raise ValueError('DC status exists but no recorded run can be identified; refusing an older DDC')
        candidates=sorted((case/'run').glob('*_'+scope))
        candidates=[p for p in candidates if p.is_dir() and re.match(r'^\d{8}_\d{6}_\d+_'+scope+r'$',p.name)]
        if not candidates:raise ValueError('No saved '+scope+' run for '+name)
        run=candidates[-1]
    run=within(root,run)
    try:relative=run.relative_to(root/'experiments/cases')
    except ValueError:raise ValueError('Source is outside case run directories')
    if len(relative.parts)!=3 or relative.parts[1]!='run' or not run.name.endswith('_'+scope):
        raise ValueError('Invalid recorded run directory: '+str(run))
    source_case=relative.parts[0]
    valid={i['name'] for i in matrix_cases()}
    if source_case not in valid or source_case[-5:]!=name[-5:]:
        raise ValueError('Reused DDC hardware does not match requested case')
    if source_case!=name and not entry.get('reused'):
        raise ValueError('Cross-case source is not declared reused')
    top='kwt_ffn1_soc' if scope=='soc' else 'kwt_ffn1_top'
    final=run/'netlist'/(top+'.ddc');compiled=run/'netlist'/(top+'_compiled.ddc')
    ddc=final if final.is_file() else compiled
    if not ddc.is_file():raise ValueError('Latest/recorded run has no saved DDC: '+str(run))
    if ddc.stat().st_size==0:raise ValueError('Saved DDC is empty: '+str(ddc))
    return dict(run_dir=run,ddc=within(root,ddc),source_case=source_case,selection=selection,original_entry=entry)

def patch_area(root):
    source=root/'script/area_scope.tcl'
    content=source.read_bytes().replace(b'\r\n',b'\n')
    if b'constant_pseudo' not in content:raise ValueError('Update root script/area_scope.tcl before recovery')
    patched=[]
    for base in ('experiments/cases','experiments/checkpoints'):
        for target in (root/base).glob('*/script/area_scope.tcl'):
            within(root,target)
            if target.read_bytes()!=content:target.write_bytes(content)
            patched.append(str(target.relative_to(root)))
            recovery=target.with_name('recover_reports.tcl')
            if recovery.exists():
                within(root,recovery)
                updated=(root/'script/recover_reports.tcl').read_bytes().replace(b'\r\n',b'\n')
                if recovery.read_bytes()!=updated:recovery.write_bytes(updated)
                patched.append(str(recovery.relative_to(root)))
    return patched

def recovery_signature(root,source,scope):
    case=root/'experiments/cases'/source['source_case']
    inputs=[root/'script/recover_reports.tcl',case/'script/area_scope.tcl',
            case/'script/common.tcl',case/'config/library_config.tcl']
    inputs += [p for p in (case/'config/optimization_config.tcl',case/'config/local_config.tcl',root/'config/local_config.tcl') if p.is_file()]
    return dict(ddc_sha256=sha(source['ddc']),scope=scope,
                report_scripts_and_config={str(p.relative_to(root)):sha(p) for p in inputs})

def reusable(root,record,signature):
    # A successful DC run can have failed ONLY the old Python metric parser.
    # Validate the actual DC success marker and artifacts before re-parsing it.
    if record.get('tool_returncode')!=0 or record.get('signature')!=signature:return False
    try:
        log=within(root,root/record['launch_log'])
        if 'KWT_REPORTS_RECOVERED:' not in log.read_text(errors='replace'):return False
        if record.get('log_sha256') and sha(log)!=record['log_sha256']:return False
        return bool(record.get('report_sha256')) and all(sha(within(root,root/name))==value for name,value in record['report_sha256'].items()) and all(sha(Path(name))==value for name,value in record.get('library_sha256',{}).items())
    except (OSError,ValueError,KeyError,TypeError):return False

def verified_cycles(root,name):
    path=root/'experiments/cases'/name/'verification/reset_tasks.json'
    if not path.is_file():return None
    data=json.loads(path.read_text());case=path.parents[1]
    if not data.get('passed') or not data.get('vectors_checked_before_run') or len(data.get('vector_sha256',{}))!=72:return None
    expected=next(i['options'] for i in matrix_cases() if i['name']==name)
    if data.get('options')!=expected or data.get('tasks')!=12 or len(data.get('task_cycles',[]))!=12:return None
    try:
        if not all(sha(case/name)==value for name,value in dict(data.get('sources',{}),**data.get('harness',{}),**data['vector_sha256']).items()):return None
    except OSError:return None
    cycles=data.get('task_cycles',[])
    return sum(cycles)/len(cycles) if cycles else None

def write_csv(path,rows):
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w',newline='',encoding='utf-8-sig') as output:
        writer=csv.DictWriter(output,fields);writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def summarize(root,records,scopes=('soc',)):
    out=root/'experiments/results';out.mkdir(parents=True,exist_ok=True)
    records=[r for r in records if r['scope'] in scopes]
    write_json(out/'ppa_recovery_long.json',records);write_csv(out/'ppa_recovery_long.csv',records)
    rows=[]
    for item in matrix_cases():
        name=item['name'];opts=item['options']
        row=dict(case=name,checkpoint=CHECKPOINTS.get(name,''),**opts)
        row['accelerator_sram_bytes']=53248-15360*int(opts['small_x'])-3072*int(opts['small_bias'])
        cycles=verified_cycles(root,name);row['task_cycles']=cycles
        row['nominal_tasks_per_second_at_150MHz']=150e6/cycles if cycles else None
        for scope in scopes:
            record=next((r for r in records if r['case']==name and r['scope']==scope),None)
            if record is None:row[scope+'_recovery_status']='not_requested_or_missing';continue
            for key,value in record.items():
                if key not in ('case','scope','signature','original_entry','report_sha256'):row[scope+'_'+key]=value
            period=row.get(scope+'_clock_period_ns')
            row[scope+'_tasks_per_second_at_saved_clock']=1e9/(period*cycles) if period and cycles else None
        rows.append(row)
    # Improvements use each scope's own baseline; unknowns and failed recoveries
    # are never promoted to valid comparisons. Positive means a reduction.
    baseline=rows[0]
    for row in rows:
        for scope in scopes:
            for metric in ('cell_area','added_area','dynamic_power_w','leakage_power_w','total_power_w'):
                key=scope+'_'+metric;base=baseline.get(key);value=row.get(key)
                row[key+'_reduction_pct_vs_baseline']=(100*(base-value)/base if base and value is not None and baseline.get(scope+'_recovery_passed') and row.get(scope+'_recovery_passed') else None)
    write_json(out/'ppa_comparison.json',rows);write_csv(out/'ppa_comparison.csv',rows)
    lines=['# Saved-DDC comparison','',
           'No RTL compilation was run. Original reports and dc_status.json are preserved.',
           'Power is vectorless, not measured task power/energy. SS hold is not fast-corner signoff.',
           'Timing pass and successful report recovery are separate. Unknown values remain blank in CSV.',
           'Rows reuse a report only when the original sweep referred to the same saved DDC.',
           '','| Case | Scope | Recovery | Cell area | Added area | Setup WNS (ns) | SS hold WNS (ns) | Dynamic (mW) | Leakage (mW) |',
           '|---|---|---|---:|---:|---:|---:|---:|---:|']
    def fmt(value,scale=1):return 'UNKNOWN' if value is None else '{:.6g}'.format(value*scale)
    for row in rows:
        for scope in scopes:
            p=lambda k:row.get(scope+'_'+k)
            lines.append('| {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(row['case'],scope,p('recovery_status') or 'missing',fmt(p('cell_area')),fmt(p('added_area')),fmt(p('setup_wns_ns')),fmt(p('hold_wns_ss_only_ns')),fmt(p('dynamic_power_w'),1000),fmt(p('leakage_power_w'),1000)))
    lines+=['','Area units: see each units.rpt and library data; values are not assumed to be um^2.',
            'Source DDCs, SHA-256 receipts, report folders, setup TNS/violations and macro counts are in the CSV/JSON.','']
    (out/'ppa_summary.md').write_text('\n'.join(lines))
    print('PPA_SUMMARY '+str(out/'ppa_comparison.csv'),flush=True)
    return rows

def recover_all(root,scopes,runner=None,items=None,resume=True,collect_only=False,dry_run=False):
    root=Path(root).resolve();runner=runner or subprocess.run;items=items or matrix_cases()
    out=root/'experiments/results';out.mkdir(parents=True,exist_ok=True)
    status_path=out/'dc_status.json';status=json.loads(status_path.read_text()) if status_path.is_file() else []
    records_path=out/'recovery_status.json'
    old=json.loads(records_path.read_text()) if records_path.is_file() else []
    if not collect_only and not dry_run:patch_area(root)
    records=[];cache={};saved={(r['case'],r['scope']):r for r in old}
    for scope in scopes:
        for item in items:
            name=item['name'];record=dict(case=name,scope=scope,recovery_passed=False,recovery_status='failed')
            try:
                source=select_source(root,name,scope,status)
                record.update(source_case=source['source_case'],source_ddc=source['ddc'].relative_to(root).as_posix(),
                              selection=source['selection'],original_entry=source['original_entry'])
                signature=recovery_signature(root,source,scope);record['signature']=signature
                key=(scope,str(source['ddc']))
                prior=next((r for r in old if r.get('case')==name and r.get('scope')==scope),{})
                if dry_run:
                    record['recovery_status']='planned';print('RECOVER_PLAN',name,scope,record['source_ddc'],flush=True)
                elif key in cache and reusable(root,cache[key],signature):
                    shared=dict(cache[key]);shared.update(case=name,source_case=source['source_case'],selection=source['selection'],original_entry=source['original_entry'],reused=True,recovery_status='reused')
                    record=shared;print('RECOVER_REUSE',name,scope,flush=True)
                elif (resume or collect_only) and reusable(root,prior,signature):
                    record=dict(prior);record.update(recovery_status='resumed',reused=False)
                    record.update(parse_reports(root/record['report_relative'],scope))
                    record['recovery_passed']=record['key_metrics_complete']
                    record['parser_sha256']=sha(Path(__file__).with_name('ppa_metrics.py'))
                    if not record['recovery_passed']:
                        record.update(recovery_status='failed',error='Re-parsed saved reports have incomplete key metrics')
                    else:record.pop('error',None)
                    print('RECOVER_RESUME',name,scope,flush=True)
                elif collect_only:
                    raise ValueError('No current successful recovery receipt; run recovery first')
                else:
                    token=uuid.uuid4().hex
                    folder=source['run_dir']/('report_recovered_'+token)
                    log=out/'recovery_logs'/(name+'_'+scope+'_'+token+'.log');log.parent.mkdir(exist_ok=True)
                    env=os.environ.copy();env.update(KWT_RECOVER_DDC=str(source['ddc']),KWT_RECOVER_REPORT_DIR=str(folder),
                        KWT_RECOVER_BACKEND_ROOT=str(root/'experiments/cases'/source['source_case']),
                        KWT_GLOBAL_LOCAL_CONFIG=str(root/'config/local_config.tcl'),KWT_SYNTHESIS_SCOPE=scope)
                    record.update(report_relative=folder.relative_to(root).as_posix(),launch_log=log.relative_to(root).as_posix(),reused=False)
                    print('RECOVER_START',name,scope,record['source_ddc'],'log='+str(log.relative_to(root)),flush=True)
                    with log.open('wb') as output:
                        result=runner(['dc_shell','-f',str(root/'script/recover_reports.tcl')],cwd=root/'experiments/cases'/source['source_case'],env=env,stdout=output,stderr=subprocess.STDOUT)
                    record.update(parse_reports(folder,scope))
                    record['parser_sha256']=sha(Path(__file__).with_name('ppa_metrics.py'))
                    record['tool_returncode']=result.returncode
                    if sha(source['ddc'])!=signature['ddc_sha256']:raise ValueError('Source DDC changed during recovery')
                    text=log.read_text(errors='replace')
                    record['log_sha256']=sha(log)
                    record['recovery_passed']=result.returncode==0 and 'KWT_REPORTS_RECOVERED:' in text and record['key_metrics_complete']
                    record['recovery_status']='recovered' if record['recovery_passed'] else 'failed'
                    record['report_sha256']={p.relative_to(root).as_posix():sha(p) for p in folder.glob('*.rpt') if p.is_file()}
                    libraries=folder/'library_sources.rpt'
                    paths=re.findall(r'^path=(.+)$',libraries.read_text(),re.M) if libraries.is_file() else []
                    record['library_sha256']={path:sha(Path(path)) for path in paths}
                    if not record['recovery_passed']:record['error']='Recovery failed or key metrics incomplete; inspect '+record['launch_log']
                    print('RECOVER_'+('PASS' if record['recovery_passed'] else 'FAILED'),name,scope,flush=True)
                if record.get('recovery_passed'):cache[key]=dict(record)
            except Exception as error:
                record.update(recovery_passed=False,recovery_status='failed',error=str(error))
                print('RECOVER_FAILED',name,scope,str(error),flush=True)
            records.append(record)
            if not dry_run:
                saved[(name,scope)]=record
                write_json(records_path,list(saved.values()))
    if not dry_run:summarize(root,list(saved.values()),scopes)
    return records

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scope',choices=('soc','accelerator','both'),default='soc',help='Default: 16 SoC configurations only')
    ap.add_argument('--force',action='store_true',help='Regenerate reports even if receipts are current')
    ap.add_argument('--collect-only',action='store_true',help='Rebuild tables from current recovery receipts without DC')
    ap.add_argument('--dry-run',action='store_true',help='List selected saved DDCs without patching or running DC')
    a=ap.parse_args();scopes=('soc','accelerator') if a.scope=='both' else (a.scope,)
    result=recover_all(ROOT,scopes,resume=not a.force,collect_only=a.collect_only,dry_run=a.dry_run)
    if not a.dry_run and not all(r['recovery_passed'] for r in result):
        raise SystemExit('Some cases could not be recovered. All cases were attempted; tables retain failures and available metrics.')
if __name__=='__main__':main()
