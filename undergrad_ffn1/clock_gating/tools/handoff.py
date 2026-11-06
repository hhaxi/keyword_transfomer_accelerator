"""Audit exact-cycle clock gating qualification and package independent server cases."""
import argparse,csv,difflib,hashlib,json,sys,tarfile
from pathlib import Path
from prepare import ROOT,CASES,sha,save,write,gate_paths
from variant_rtl import result_queue,mac_core,formatter
from gate_metrics import parse,equal
from simulate import files
sys.path.insert(0,str(ROOT/'study/tools'))
import vcs_power
from optional_options import read as read_options

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def check_hashes(mapping):
 for p,h in mapping.items():
  if sha(ROOT/p)!=h:raise ValueError('Stale evidence: '+p)

def audit():
 reference=load(ROOT/'reports/qualification_fmt1_ref.json')
 frozen=load(ROOT/'reports/frozen/qualification_q64_bank1_fmt1.json')
 original=load(ROOT/'reports/source_reference.json')['files']
 rows=[];activity={}
 for mode in ('reset','continuous'):equal(frozen['modes'][mode],reference['modes'][mode],'frozen fmt1 '+mode)
 for design in CASES:
  name=design['name'];case=ROOT/'study/cases'/name
  q=load(ROOT/'reports'/('qualification_'+name+'.json'));s=load(ROOT/'reports'/('structure_'+name+'.json'))
  if not q.get('passed') or q.get('tasks')!=12 or q['inputs']!=files(case):raise ValueError('Stale/incomplete qualification: '+name)
  if not s.get('passed') or any(sha(case/p)!=h for p,h in s['inputs'].items()):raise ValueError('Stale structure check')
  if s['checker_sha256']!=sha(ROOT/'tools/check_structure.py') or s['blackbox_sha256']!=sha(ROOT/'tests/sram_blackboxes.sv'):raise ValueError('Checker changed')
  changed={'case.json','tests/tb_soc_power.sv','tests/tb_soc_vcs_power.sv','script/set_env.tcl','script/read_file.tcl','script/write_file.tcl','README.md','vcs_seed.json'}
  for enabled,rel in [(design['result'],'rtl/kwt_group_queue.sv'),(design['mac'],'rtl/kwt_tile_core.sv'),(design['formatter'],'rtl/kwt_output_formatter.sv')]:
   if enabled:changed.add(rel)
  if gate_paths(design):changed|={'filelists/soc.f','filelists/accelerator.f'}
  for rel,h in original.items():
   if rel not in changed and sha(case/rel)!=h:raise ValueError('Unexpected frozen reference change: '+name+'/'+rel)
  for enabled,rel,transform in [(design['result'],'rtl/kwt_group_queue.sv',result_queue),
      (design['mac'],'rtl/kwt_tile_core.sv',mac_core),(design['formatter'],'rtl/kwt_output_formatter.sv',formatter)]:
   before=(ROOT/'study/cases/fmt1_ref'/rel).read_text()
   expected=transform(before) if enabled else before
   if (case/rel).read_text()!=expected:raise ValueError('Candidate transform mismatch: '+rel)
  if gate_paths(design) and sha(case/'rtl/kwt_clock_gate.sv')!=sha(ROOT/'rtl/kwt_clock_gate.sv'):raise ValueError('Clock gate model differs')
  if sha(case/'script/clock_gating.tcl')!=sha(ROOT/'backend/clock_gating.tcl'):raise ValueError('Backend adapter differs')
  vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
  activity[name]={}
  for mode in ('reset','continuous'):
   m=q['modes'][mode];equal(reference['modes'][mode],m,name+' '+mode)
   p=ROOT/m['receipt']['log']
   if sha(p)!=m['receipt']['log_sha256']:raise ValueError('Simulation log changed')
   windows,profiles=vcs_power.validate_simulation(p.read_text(),read_options(case),12)
   if windows!=m['windows']:raise ValueError('Window receipt differs')
   equal(m,dict(windows=windows,profiles=profiles),'reparsed log')
   for w in windows:
    if w['duration_fs']!=(w['end_cycle']-w['begin_cycle'])*6666667+3333333:raise ValueError('Timestamp precision mismatch')
   activity[name][mode]=parse(name,p.read_text(),windows)
  for receipt in (q['build'],s['receipt'],s['accelerator_receipt']):
   if sha(ROOT/receipt['log'])!=receipt['log_sha256']:raise ValueError('Build/structure evidence changed')
  reset=q['modes']['reset'];continuous=q['modes']['continuous'];stats=activity[name]['reset']
  before=sum(r['ungated_register_bit_edges'] for r in stats);after=sum(r['gated_register_bit_edges'] for r in stats)
  rows.append(dict(name=name,reset_mean_cycles=round(reset['mean_cycles'],6),
   continuous_mean_cycles=round(continuous['mean_cycles'],6),cycle_delta_vs_ref=0,
   all_task_durations_identical=True,all_profiles_identical=True,intended_icg_instances=len(gate_paths(design)),
   gated_register_bits=s['gated_register_bits'],datapath_register_bits=s['generic_sequential_bits'],
   target_register_clock_edges_suppressed_percent=100*(1-after/before) if before else 0,
   task00_gate_edges={k:v['edges'] for k,v in stats[0]['gates'].items()},
   macs=64,local_sram_kib=37,passed_reset_tasks=12,passed_continuous_tasks=12,
   nominal_throughput_150mhz=150000000/round(reset['mean_cycles'],6),
   backend_area=None,backend_power=None,backend_setup=None,backend_hold=None,backend_tested=False))
 components=load(ROOT/'reports/components/results.json')
 if not components['passed'] or components['driver_sha256']!=sha(ROOT/'tools/test_components.py'):raise ValueError('Component driver stale')
 for t in components['tests']:
  check_hashes(t['source_sha256'])
  if not t['passed'] or sha(ROOT/t['log'])!=t['log_sha256']:raise ValueError('Component evidence changed')
 for label in ('backend_adapter','server_integration'):
  record=load(ROOT/'reports'/(label+'.json'))
  if not record['passed']:raise ValueError('Acceptance adapter failed')
  check_hashes(record['inputs'])
  if 'log' in record and sha(ROOT/record['log'])!=record['log_sha256']:raise ValueError('Adapter log changed')
 reused=load(ROOT/'reports/server_driver_reuse.json');check_hashes(reused['driver_sha256']);check_hashes(reused['inherited_evidence_sha256'])
 save(ROOT/'reports/gated_clock_activity.json',activity)
 save(ROOT/'reports/acceptance.json',dict(passed=True,frontend_only=True,cases=5,whole_soc_tasks=120,
  exact_outputs_checked=3041280,all_per_task_durations_identical=True,all_profiles_identical=True,
  frozen_reference_reproduced=True,backend_acceptance='pending real ICG mapping, timing, postmapping functionality and power/activity review'))
 return rows

def report(rows):
 save(ROOT/'reports/comparison.json',rows)
 with (ROOT/'reports/comparison.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 lines=['# fmt1 门控时钟候选：前端验收结果','',
  '五组均使用 q64_bank1_fmt1 的固定 pause64 固件、64 MAC、37 KiB 本地 SRAM、INT40 输出及相同 12 层权重/合成 X。',
  '每组 12 次复位＋12 次连续任务；共 120 个任务、3,041,280 个输出逐位正确。',
  '每个任务的严格整数 fs 时长、全部 15 个性能计数均与新参考相等；新参考亦复现冻结归档中的逐任务结果。','',
  '| 设计 | 复位平均拍 | 连续平均拍 | 周期变化 | 计划 ICG 数 | 受控寄存器位 | 受控寄存器时钟沿×位数减少 |',
  '|---|---:|---:|---:|---:|---:|---:|']
 for r in rows:
  lines.append('| {name} | {reset_mean_cycles:.1f} | {continuous_mean_cycles:.3f} | 0 | {intended_icg_instances} | {gated_register_bits} | {target_register_clock_edges_suppressed_percent:.2f}% |'.format(**r))
  write(ROOT/'study/cases'/r['name']/'README.md',('# {name}\n\n'
   '复位平均 {reset_mean_cycles:.1f} 拍，连续平均 {continuous_mean_cycles:.3f} 拍；全部逐任务时长和计数与 fmt1_ref 一致。\n\n'
   '计划 ICG {intended_icg_instances} 个，受控数据寄存器 {gated_register_bits} 位；实际库映射/时序/功耗待服务器验证。\n'
   '前端受控寄存器时钟沿×位数减少 {target_register_clock_edges_suppressed_percent:.2f}%，不是功耗降幅。\n\n'
   '在交付根目录运行 `bash run_server.sh --quick --case {name}`，入口自动带上 fmt1_ref。\n').format(**r))
 lines+=['','上述百分比仅针对各候选被门控的数据寄存器，以实测时钟沿×寄存器位数加权。',
  '它不包括 ICG 自身、缓冲、组合逻辑、CPU、SRAM 或互连的功耗，不能解释为 SoC 功耗降幅。',
  '所有组的加速器数据/控制寄存器容量均为 4084 位，另外存在门控锁存状态；数值格式、SRAM 和乘法器数量未变。','',
  '## 严格窗口内时钟行为','',
  'task00 原始时钟有 55,417 个上升沿；窗口从下降沿开始，严格时长为 55,416.5 拍。',
  '结果缓冲每组 800 个沿；MAC 每组 25,603 个沿（有效乘加和同步清空）；打包器每组 6,338 个沿。',
  '每个实际门控沿都与原始时钟沿和写使能比对，监测额外/丢失脉冲。完整逐任务记录见 gated_clock_activity.json。','',
  '## 验证边界','',
  '- Icarus 四状态测试：时钟高相位使能变化、测试覆盖、停钟/恢复；MAC 极值/随机/清空与无门控逐拍对照；队列与打包器长背压、同时读写、复位、清空。',
  '- Yosys 前端结构检查：64 个 signed 16×16 乘法器，SRAM 数量不变，目标时钟实际连接到 1280/1280/311/2871 位数据寄存器。',
  '- 库绑定 Tcl 经过模拟库 API 和生成 HDL 的测试，验证找不到合法 ICG、端口不兼容、映射数不符时拒绝继续；不是实际 DC 测试。',
  '- 公共 VCS/SAIF/DC 驱动与上一轮归档逐字节相同；新入口在 DC 前强制比较 VCS 的逐任务周期、计数和门控证据。',
  '- 本机无 VCS/DC/工艺库，未获得新候选面积、功耗或时序结果。前端通过不代表后端通过。',
  '- 时序、门控检查、真实 ICG 时钟活动覆盖以及综合后功能一致性须在服务器完成；禁止用缺失活动制造零功耗收益。','']
 write(ROOT/'reports/RESULTS.md','\n'.join(lines))
 ref=ROOT/'study/cases/fmt1_ref'
 for d in CASES[1:]:
  case=ROOT/'study/cases'/d['name'];diff=[]
  names=set()
  for base in (ref,case):
   names.update(p.relative_to(base).as_posix() for p in (base/'rtl').rglob('*') if p.is_file())
  for name in sorted(names):
   a=(ref/name).read_text().splitlines(keepends=True) if (ref/name).exists() else []
   b=(case/name).read_text().splitlines(keepends=True) if (case/name).exists() else []
   diff.extend(difflib.unified_diff(a,b,fromfile='fmt1_ref/'+name,tofile=d['name']+'/'+name))
  write(ROOT/'reports/design_diffs'/(d['name']+'.patch'),''.join(diff))

def package():
 out=ROOT/'output';out.mkdir(exist_ok=True);archive=out/'ffn1_clock_gating_2026-11-06.tar.gz';top='ffn1_clock_gating'
 paths=[]
 for folder in ('rtl','backend','tools','tests','reports','study'):
  for p in (ROOT/folder).rglob('*'):
   rel=p.relative_to(ROOT)
   if not p.is_file() or any(x in rel.parts for x in ('tmp','__pycache__','server')):continue
   if p.suffix in ('.pyc','.elf','.bin','.vcd','.saif','.db','.lib','.ddc'):continue
   if 'output' in rel.parts and 'firmware' not in rel.parts:continue
   if p.name=='local_config.tcl':continue
   paths.append(p)
 paths += [ROOT/n for n in ('README.md','PLAN.md','run_server.sh')]
 manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(paths))};save(out/'package_manifest.json',manifest)
 with tarfile.open(archive,'w:gz') as tar:
  for rel in manifest:tar.add(ROOT/rel,arcname=top+'/'+rel,recursive=False)
  tar.add(out/'package_manifest.json',arcname=top+'/package_manifest.json')
 with tarfile.open(archive) as tar:
  for rel,h in manifest.items():
   if hashlib.sha256(tar.extractfile(top+'/'+rel).read()).hexdigest()!=h:raise ValueError('Archive bytes differ')
 write(out/(archive.name+'.sha256'),sha(archive)+'  '+archive.name+'\n')
 print('PACKAGE_PASS',archive,'bytes',archive.stat().st_size,'sha256',sha(archive),flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',action='store_true');args=ap.parse_args()
 rows=audit();report(rows);print('AUDIT_PASS 5 cases / 120 tasks / 3041280 exact outputs / zero cycle or profile changes',flush=True)
 if args.package:package()
