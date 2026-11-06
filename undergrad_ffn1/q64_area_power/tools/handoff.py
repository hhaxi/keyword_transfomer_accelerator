"""Audit qualified q64 candidates, report actual cycles, create standalone handoff."""
import argparse,csv,difflib,hashlib,json,re,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
import vcs_power
from optional_options import read as read_options
from simulate import files
from prepare import sha,save,write,CASES
from variant_rtl import transform

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def hashes(mapping):
 for p,h in mapping.items():
  if sha(ROOT/p)!=h:raise ValueError('Stale evidence: '+p)

def audit():
 rows=[]
 frozen=load(ROOT/'reports/source_reference.json')['source_sha256']
 for design in CASES:
  name=design['name'];case=ROOT/'study/cases'/name
  record=load(ROOT/'reports'/('qualification_'+name+'.json'))
  structure=load(ROOT/'reports'/('structure_'+name+'.json'))
  if not record.get('passed') or record.get('tasks')!=12 or record['inputs']!=files(case):
   raise ValueError('Missing/stale full qualification: '+name)
  if not structure.get('passed') or any(sha(case/p)!=h for p,h in structure['inputs'].items()):
   raise ValueError('Missing/stale structure check: '+name)
  if structure['checker_sha256']!=sha(ROOT/'tools/check_structure.py'):raise ValueError('Stale checker')
  if structure['blackbox_sha256']!=sha(ROOT/'tests/sram_blackboxes.sv'):raise ValueError('Changed macro models')
  # Only the declared RTL/files lists/case metadata may differ from frozen q64.
  allowed={'case.json'}
  if design['queue']!='reference':allowed|={'rtl/kwt_tile_core.sv','filelists/soc.f','filelists/accelerator.f'}
  if design['narrow']:allowed.add('rtl/kwt_tile_mac.sv')
  if design.get('formatter_depth')==1:allowed.add('rtl/kwt_output_formatter.sv')
  for rel,h in frozen.items():
   if rel in allowed or rel in ('vcs_seed.json','README.md'):continue
   if sha(case/rel)!=h:raise ValueError('Unexpected reference change: '+name+'/'+rel)
  core=(ROOT/'study/cases/q64_ref/rtl/kwt_tile_core.sv').read_text()
  if design['queue']!='reference':core=transform(core,design)
  if (case/'rtl/kwt_tile_core.sv').read_text()!=core:raise ValueError('Generator mismatch')
  for filename,required in [('kwt_output_sequence.sv',design['queue']!='reference'),
    ('kwt_group_queue.sv',design['queue'] in ('bank1','bank2')),
    ('kwt_tile_mac.sv',design['narrow']),('kwt_output_formatter.sv',design.get('formatter_depth')==1)]:
   if required and sha(case/'rtl'/filename)!=sha(ROOT/'rtl'/filename):raise ValueError('Component/case mismatch')
  vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
  for mode in record['modes'].values():
   receipt=mode['receipt'];path=ROOT/receipt['log']
   if sha(path)!=receipt['log_sha256']:raise ValueError('Log changed')
   windows,profiles=vcs_power.validate_simulation(path.read_text(),read_options(case),12)
   if windows!=mode['windows']:raise ValueError('Window mismatch')
   if {str(k):{str(i):v for i,v in p.items()} for k,p in profiles.items()}!=mode['profiles']:
    raise ValueError('Profile mismatch')
   for w in windows:
    if w['duration_fs']!=(w['end_cycle']-w['begin_cycle'])*6666667+3333333:raise ValueError('Timestamp precision')
  for receipt in (record['build'],structure['receipt'],structure['accelerator_receipt']):
   if sha(ROOT/receipt['log'])!=receipt['log_sha256']:raise ValueError('Build/structure log changed')
  reset=record['modes']['reset'];cont=record['modes']['continuous'];p=reset['profiles']['0']
  cycles=round(reset['mean_cycles'],6)
  rows.append(dict(name=name,parent=design['parent'],reset_mean_cycles=cycles,
   continuous_mean_cycles=round(cont['mean_cycles'],6),
   continuous_min_cycles=round(min(w['cycles'] for w in cont['windows']),6),
   continuous_max_cycles=round(max(w['cycles'] for w in cont['windows']),6),
   macs=structure['macs'],sram_kib=sum(int(re.search(r'RAMSP(\d+)X16',n).group(1))*2*v for n,v in structure['accelerator_macros'].items())/1024,
   generic_sequential_bits=structure['generic_sequential_bits'],generic_mux_output_bits=structure['generic_mux_output_bits'],
   nominal_tasks_per_second_150mhz=150000000/cycles,fifo_wait=int(p['5']),request_wait=int(p['7']),
   mac_active_cycles=int(p['4']),dma_read_words=int(p['9']),dma_write_words=int(p['10']),
   passed_reset_tasks=12,passed_continuous_tasks=12,backend_area=None,backend_power=None,backend_wns=None))
 components=load(ROOT/'reports/components/results.json')
 if not components['passed'] or components['driver_sha256']!=sha(ROOT/'tools/test_components.py'):raise ValueError('Stale component tests')
 for test in components['tests']:
  hashes(test['source_sha256'])
  if not test['passed'] or sha(ROOT/test['log'])!=test['log_sha256']:raise ValueError('Component evidence failed')
 reused=load(ROOT/'reports/server_driver_reuse.json');integration=load(ROOT/'reports/server_integration.json')
 if not reused['passed'] or not integration['passed']:raise ValueError('Server checks failed')
 hashes(reused['driver_sha256']);hashes(reused['inherited_evidence_sha256']);hashes(integration['inputs'])
 for row in rows:
  row['cycle_delta_vs_ref']=row['reset_mean_cycles']-rows[0]['reset_mean_cycles']
  row['cycle_delta_vs_ref_percent']=100*row['cycle_delta_vs_ref']/rows[0]['reset_mean_cycles']
  row['generic_sequential_reduction_percent']=100*(1-row['generic_sequential_bits']/rows[0]['generic_sequential_bits'])
 return rows

def report(rows):
 save(ROOT/'reports/comparison.json',rows)
 for design in CASES:
  if design['parent'] is None:continue
  before=ROOT/'study/cases'/design['parent'];after=ROOT/'study/cases'/design['name']
  patch=[]
  for folder in ('rtl','filelists'):
   names={p.relative_to(before).as_posix() for p in (before/folder).rglob('*') if p.is_file()}
   names|={p.relative_to(after).as_posix() for p in (after/folder).rglob('*') if p.is_file()}
   for name in sorted(names):
    a=(before/name).read_text().splitlines(keepends=True) if (before/name).exists() else []
    b=(after/name).read_text().splitlines(keepends=True) if (after/name).exists() else []
    patch.extend(difflib.unified_diff(a,b,fromfile=design['parent']+'/'+name,tofile=design['name']+'/'+name))
  write(ROOT/'reports/design_diffs'/(design['name']+'.patch'),''.join(patch))
 with (ROOT/'reports/comparison.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 lines=['# q64 面积/功耗前端候选：仿真与结构结果','',
  '所有周期来自真实 E203 整机功能仿真。基准为上一轮 q64_fused_pause 原样复测。',
  '严格窗口：第一笔 Host 输入装载请求至最后 DMA 输出写响应；不含一次性启动和结果回读。',
  '相同 pause64 固件、12 层权重和合成 X、packed40 输出、64 MAC、37 KiB 本地 SRAM。',
  '寄存器和 mux 为 Yosys 通用优化后的加速器 RTL 统计，不是映射面积；未测量工艺功耗或时序。','',
  '| 候选 | 复位平均拍 | 连续平均拍 | 相对参考增加拍 | 周期变化 | 通用寄存器位 | 位数减少 | 通用 mux 输出位 |',
  '|---|---:|---:|---:|---:|---:|---:|---:|']
 for r in rows:
  lines.append('| {name} | {reset_mean_cycles:.1f} | {continuous_mean_cycles:.3f} | {cycle_delta_vs_ref:+.1f} | {cycle_delta_vs_ref_percent:+.4f}% | {generic_sequential_bits} | {generic_sequential_reduction_percent:.2f}% | {generic_mux_output_bits} |'.format(**r))
  write(ROOT/'study/cases'/r['name']/'README.md',
   ('# {name}\n\n父项：{parent}；设计变更见交付根目录 README、PLAN 和本目录 case.json。\n\n'
    '12 次复位＋12 次连续任务逐位正确。复位平均 {reset_mean_cycles:.1f} 拍，连续平均 {continuous_mean_cycles:.3f} 拍；'
    '相对 q64_ref 增加 {cycle_delta_vs_ref:+.1f} 拍（{cycle_delta_vs_ref_percent:+.4f}%）。\n\n'
    '64 MAC、37 KiB 本地 SRAM；通用寄存器 {generic_sequential_bits} 位，mux 输出位 {generic_mux_output_bits}。'
    '这些是 RTL 结构指标，实际面积、活动功耗和时序待服务器验证。\n\n'
    '从交付根目录运行 `bash run_server.sh --quick --case {name}`。\n').format(**r))
 lines+=['','## 验证范围','',
  '- 8 组各 12 次复位＋12 次连续任务，共 192 任务、4,866,048 个逐位核对输出。',
  '- 每任务 MAC 活跃 25,600 拍、DMA 读 11,616 字、写 31,680 字；计数与整数 fs 窗口均校验。',
  '- Icarus 四状态测试覆盖 1,000 组 MAC（32,000 对乘积），极值、随机、停顿、首项和清空；',
  '  深度 1/2 队列全 99 行遍历、尾部 24 结果、长背压、同时读写、复位/清空；INT64/packed40 格式器随机/极值/非法索引。',
  '- Yosys 展开和 check 通过：所有组 64 个有符号 16×16 乘法器；本地 20×128×16＋16×1024×16 宏，SoC 另有 80×4096×16。',
  '- 通用寄存器位数为 $*dff* 单元 Q 端口位数总和；mux 指 $mux/$pmux 的 Y 位数总和，未按选择输入数加权。',
  '  不同综合器可能重构逻辑，因此这些统计只用于解释候选，不能当作面积降幅或功耗预测。',
  '- 公共服务器驱动逐字节沿用上一轮已测试版本；本轮验证全部 seed、快速目录克隆和 13 个入口分发组合。',
  '  旧驱动测试证据明确标为继承，本机没有执行 VCS/DC。','',
  '## 下一轮服务器比较','',
  '先跑全部 8 组的相同 task00，再对保留项和参考运行全部 12 任务。',
  'q64_seq 用于验证不增加周期的地址逻辑优化；q64_bank2/bank1 比较固定分组和容量取舍；',
  'q64_bank1_mac38、q64_bank1_fmt1 与父项独立比较，q64_lean 检查组合效果。',
  'q64_lean_earlyfree 在组合版上提前释放已用完的 X tile，比较 DMA 装载与结果排出的重叠。',
  '本次提前释放未改善严格周期或通用寄存器位数，保留为调度对照，未列入默认推荐组。',
  '队列减少后的周期代价见表；不能将结构简化直接称为功耗改善。',
  '请同时比较 added area、SoC area、动态/漏电/总功耗、严格窗口能量、setup/hold 与 SAIF/SRAM 活动覆盖。',
  '用户上一轮 q64_fused_pause 为 added area 362794、总功耗 174.763 mW、64.504444 uJ/task；',
  '该值只覆盖 task00，SS hold WNS −0.19 ns，覆盖需检查；应重新跑 q64_ref 作为同环境对照。',
  '不以修复 hold 之前的功耗最低项直接定版；以时序/覆盖合格后的周期、面积与任务能量选择。','']
 lines+=['## 历史冻结基线','',
  '仓库 verification/baseline.json 记录旧版 task_cycles=167134、本地 SRAM=52 KiB；本轮各项均为 37 KiB。',
  '该基线的配置及周期口径与本轮不同，仅保留在 historical_baseline.json 用于追溯，',
  '不将 167134 与本轮严格周期相除作为本轮加速比。本轮收益一律与同条件 q64_ref 比较。','']
 write(ROOT/'reports/RESULTS.md','\n'.join(lines))

def package():
 out=ROOT/'output';out.mkdir(exist_ok=True)
 archive=out/'ffn1_q64_area_power_2026-11-06.tar.gz';top='ffn1_q64_area_power'
 paths=[]
 for folder in ('rtl','tools','tests','reports','study'):
  for p in (ROOT/folder).rglob('*'):
   rel=p.relative_to(ROOT)
   if not p.is_file() or any(x in rel.parts for x in ('tmp','__pycache__','server')):continue
   if p.suffix in ('.pyc','.elf','.bin','.vcd','.saif','.db','.lib','.ddc'):continue
   if 'output' in rel.parts and 'firmware' not in rel.parts:continue
   if p.name=='local_config.tcl':continue
   paths.append(p)
 paths += [ROOT/n for n in ('README.md','PLAN.md','run_server.sh')]
 manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(paths))}
 save(out/'package_manifest.json',manifest)
 with tarfile.open(archive,'w:gz') as tar:
  for rel in manifest:tar.add(ROOT/rel,arcname=top+'/'+rel,recursive=False)
  tar.add(out/'package_manifest.json',arcname=top+'/package_manifest.json')
 with tarfile.open(archive) as tar:
  for rel,h in manifest.items():
   if hashlib.sha256(tar.extractfile(top+'/'+rel).read()).hexdigest()!=h:raise ValueError('Archive byte mismatch')
 write(out/(archive.name+'.sha256'),sha(archive)+'  '+archive.name+'\n')
 print('PACKAGE_PASS',archive,'bytes',archive.stat().st_size,'sha256',sha(archive),flush=True)

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',action='store_true');args=ap.parse_args()
 rows=audit();report(rows)
 print('AUDIT_PASS',len(rows),'cases',len(rows)*24,'tasks',len(rows)*24*25344,'outputs',flush=True)
 if args.package:package()
