"""Parse DC reports without assigning zero to unavailable metrics or units."""
import math,re
from pathlib import Path

NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'

def finite(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None

def match_number(pattern,text):
    match=re.search(pattern,text,re.I|re.M)
    return finite(match.group(1)) if match else None

def power_multiplier(unit):
    return {'W':1,'mW':1e-3,'uW':1e-6,'nW':1e-9,'pW':1e-12,'fW':1e-15}.get(unit.replace('\u00b5','u'))

def power_value(label,text,kind):
    match=re.search(r'^\s*'+label+r'\s*=\s*('+NUMBER+r')\s*([munpf\u00b5]?W)?\b',text,re.M)
    if not match:return None
    value=finite(match.group(1))
    unit=match.group(2)
    scale=power_multiplier(unit) if unit else None
    if unit is None:
        units=re.search(kind+r' Power Units\s*=\s*('+NUMBER+r')\s*([munpf\u00b5]?W)\b',text)
        if units:
            factor=power_multiplier(units.group(2))
            if factor is not None:scale=float(units.group(1))*factor
    return value*scale if value is not None and scale is not None else None

def hierarchy_power(text):
    """DC -hierarchy uses dynamic units for Switch/Int/Total, separate Leak units."""
    header=re.search(r'Switch\s+Int\s+Leak\s+Total',text)
    design=re.search(r'^\s*Design\s*:\s*(\S+)',text,re.M)
    if not header or not design:return {}
    row=re.search(r'^[ \t]*'+re.escape(design.group(1))+r'[ \t]+'
                  +r'[ \t]+'.join('('+NUMBER+')' for _ in range(5))+r'(?:[ \t]|$)',
                  text[header.end():],re.M)
    if not row:return {}
    values=[finite(v) for v in row.groups()]
    if any(v is None for v in values):return {}
    def scale(kind):
        unit=re.search(kind+r' Power Units\s*=\s*('+NUMBER+r')\s*([munpf\u00b5]?W)\b',text)
        factor=power_multiplier(unit.group(2)) if unit else None
        return float(unit.group(1))*factor if factor is not None else None
    dynamic=scale('Dynamic');leakage=scale('Leakage')
    return dict(switching_power_w=values[0]*dynamic if dynamic is not None else None,
                internal_power_w=values[1]*dynamic if dynamic is not None else None,
                dynamic_power_w=(values[0]+values[1])*dynamic if dynamic is not None else None,
                leakage_power_w=values[2]*leakage if leakage is not None else None,
                reported_total_power_w=values[3]*dynamic if dynamic is not None else None)

def parse_reports(folder,scope):
    folder=Path(folder)
    def read(name):
        path=folder/name
        return path.read_text(errors='replace') if path.is_file() else ''
    area=read('area.rpt');power=read('power_vectorless_NOT_OFFICIAL.rpt')
    units=read('units.rpt');setup=read('timing_setup.rpt');hold=read('timing_hold_ss_only.rpt')
    qor=read('qor.rpt');scoped=read('area_scope.rpt');metadata=read('recovery_metadata.rpt')
    result={'power_method':'vectorless_NOT_OFFICIAL','report':str(folder)}
    for key,label in [('cell_area','Total cell area'),('comb_area','Combinational area'),
                      ('sequential_area','Noncombinational area'),('macro_area','Macro/Black Box area'),
                      ('buffer_inverter_area','Buf/Inv area'),('cell_count','Number of cells')]:
        result[key]=match_number(r'^\s*'+re.escape(label)+r'\s*:\s*('+NUMBER+r')\s*$',area)
    result['cell_count']=int(result['cell_count']) if result['cell_count'] is not None else None
    time_match=re.search(r'Time[\s_]+Units?\s*[:=]\s*('+NUMBER+r')\s*(fs|ps|ns|us|ms|s)\b',units+'\n'+power,re.I)
    result['time_unit']=''.join(time_match.groups()) if time_match else None
    time_ns=(float(time_match.group(1))*{'fs':1e-6,'ps':1e-3,'ns':1,'us':1e3,'ms':1e6,'s':1e9}[time_match.group(2).lower()]) if time_match else None
    area_match=re.search(r'Area[\s_]+Units?\s*[:=]\s*(.+)',units,re.I)
    result['area_unit']=area_match.group(1).strip() if area_match else 'library_area_units (verify .db)'
    for key,text in [('setup_wns',setup),('hold_wns_ss_only',hold)]:
        values=[finite(v) for v in re.findall(r'slack\s*\([^)]*\)\s*('+NUMBER+r')',text,re.I)]
        values=[v for v in values if v is not None]
        result[key]=min(values) if values else None
        result[key+'_ns']=result[key]*time_ns if result[key] is not None and time_ns is not None else None
    result['setup_meets_target']=(result['setup_wns']>=0 and not re.search(r'slack\s*\(VIOLATED\)',setup,re.I)) if result['setup_wns'] is not None else None
    result['hold_meets_target_ss_only']=(result['hold_wns_ss_only']>=0 and not re.search(r'slack\s*\(VIOLATED\)',hold,re.I)) if result['hold_wns_ss_only'] is not None else None
    # Exclude optional hold sections from setup totals. Timing path group or
    # explicit setup headings start the next setup section.
    setup_qor=[];in_hold=False
    for line in qor.splitlines():
        if re.match(r'^\s*Hold\s+Timing\b',line,re.I):in_hold=True
        elif re.match(r'^\s*(?:Timing Path Group|Setup\s+Timing)\b',line,re.I):in_hold=False
        if not in_hold:setup_qor.append(line)
    setup_qor='\n'.join(setup_qor)
    # report_qor gives disjoint timing path groups. Prefer explicit design totals.
    for key,label,design_label in [('setup_tns','Total Negative Slack','Design TNS'),
                                    ('setup_violating_paths','No. of Violating Paths','Design Violating Paths')]:
        total=match_number(re.escape(design_label)+r'\s*:\s*('+NUMBER+r')',setup_qor)
        values=[finite(v) for v in re.findall(re.escape(label)+r'\s*:\s*('+NUMBER+r')',setup_qor)]
        result[key]=total if total is not None else (sum(values) if values else None)
    if result['setup_violating_paths'] is not None:result['setup_violating_paths']=int(result['setup_violating_paths'])
    result['setup_tns_ns']=result['setup_tns']*time_ns if result['setup_tns'] is not None and time_ns is not None else None
    result['constraint_violation_lines']=len(re.findall(r'\(VIOLATED\)',read('constraints.rpt'),re.I)) if read('constraints.rpt').strip() else None
    for key,label,kind in [('internal_power_w','Cell Internal Power','Dynamic'),
                           ('switching_power_w','Net Switching Power','Dynamic'),
                           ('dynamic_power_w','Total Dynamic Power','Dynamic'),
                           ('leakage_power_w','Cell Leakage Power','Leakage')]:
        result[key]=power_value(label,power,kind)
    table=hierarchy_power(power)
    for key,value in table.items():
        if result.get(key) is None:result[key]=value
    result['power_format']='hierarchy_top_row' if table else 'summary_labels'
    result.setdefault('reported_total_power_w',power_value('Total Power',power,'Dynamic'))
    result['calculated_total_power_w']=(result['dynamic_power_w']+result['leakage_power_w']) if all(result[k] is not None for k in ('dynamic_power_w','leakage_power_w')) else None
    result['total_power_w']=result['reported_total_power_w'] if result['reported_total_power_w'] is not None else result['calculated_total_power_w']
    result['area_scope_complete']=('status=COMPLETE' in scoped) if scope=='soc' else None
    for category in ('added','cpu','shared'):
        line=re.search(r'^'+category+r'\s+(.+)$',scoped,re.M)
        fields=dict(re.findall(r'(\w+)=([^\s]+)',line.group(1))) if line else {}
        result[category+'_area']=finite(fields.get('area'))
        result[category+'_known_area']=finite(fields.get('known_area'))
        unknown=finite(fields.get('unknown_leaves'))
        result[category+'_unknown_leaves']=int(unknown) if unknown is not None else None
    if scope=='accelerator':result['added_area']=result['cell_area']
    result['constant_pseudo_count']=match_number(r'constant_pseudo=(\d+)',scoped)
    clocks=[]
    for name,period in re.findall(r'^clock=([^\t\r\n]+)\tperiod=('+NUMBER+r')',metadata,re.M):
        clocks.append(dict(name=name,period=finite(period)))
    result['saved_clocks']=clocks
    periods={c['period'] for c in clocks}
    result['clock_period_ns']=next(iter(periods))*time_ns if len(periods)==1 and time_ns is not None else None
    result['nominal_clock_mhz']=1000/result['clock_period_ns'] if result['clock_period_ns'] is not None and result['clock_period_ns']>0 else None
    for macro in ('RAMSP128X16','RAMSP1024X16','RAMSP4096X16'):
        result[macro+'_count']=match_number(r'^'+macro+r'\s+count=(\d+)',read('sram_inventory.rpt'))
    result['key_metrics_complete']=all(result[k] is not None for k in ('cell_area','setup_wns','dynamic_power_w','leakage_power_w')) and (scope!='soc' or result['area_scope_complete'] is True)
    result['missing_key_metrics']=[k for k in ('cell_area','setup_wns','dynamic_power_w','leakage_power_w') if result[k] is None]
    if scope=='soc' and result['area_scope_complete'] is not True:result['missing_key_metrics'].append('complete_scope_area')
    result['hold_corner_note']='SS-only; not fast-corner hold signoff'
    return result
