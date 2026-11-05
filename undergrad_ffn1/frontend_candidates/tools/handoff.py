"""Audit measured candidates, report frontend metrics, and create a standalone tar."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
import vcs_power
from optional_options import read as read_options

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,value):Path(p).write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())

def current_inputs(case):
    result={}
    for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests','vectors','output/firmware'):
        for p in sorted((case/folder).rglob('*')):
            if p.is_file() and p.suffix not in ('.elf','.bin') and '__pycache__' not in p.parts:
                result[p.relative_to(case).as_posix()]=sha(p)
    result['case.json']=sha(case/'case.json')
    return result

def audit():
    names=[x['name'] for x in load(ROOT/'study/activity_manifest.json')['cases']]
    rows=[]
    for name in names:
        case=ROOT/'study/cases'/name
        record=load(ROOT/'reports'/('qualification_'+name+'.json'))
        structure=load(ROOT/'reports'/('structure_'+name+'.json'))
        if not record.get('passed') or record.get('tasks')!=12 or record['inputs']!=current_inputs(case):
            raise ValueError('Missing/stale 12-task qualification: '+name)
        if not structure.get('passed') or any(sha(case/p)!=h for p,h in structure['inputs'].items()):
            raise ValueError('Missing/stale structure check: '+name)
        vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
        reset=record['modes']['reset'];cont=record['modes']['continuous']
        for mode in (reset,cont):
            path=ROOT/mode['receipt']['log']
            if sha(path)!=mode['receipt']['log_sha256']:raise ValueError('Log mismatch: '+str(path))
            windows,profiles=vcs_power.validate_simulation(path.read_text(),read_options(case),12)
            if windows!=mode['windows']:raise ValueError('Window receipt mismatch: '+name)
            if {str(k):{str(i):v for i,v in p.items()} for k,p in profiles.items()}!=mode['profiles']:
                raise ValueError('Profile receipt mismatch: '+name)
            for w in windows:
                if w['duration_fs']!=(w['end_cycle']-w['begin_cycle'])*6666667+3333333:
                    raise ValueError('Integer-fs precision mismatch')
        p=reset['profiles']['0']
        macros=structure['accelerator_macros']
        capacity=sum(int(re.search(r'RAMSP(\d+)X16',n).group(1))*2*v for n,v in macros.items())
        cycles=reset['mean_cycles']
        opts=read_options(case)
        row=dict(name=name,macs=structure['macs'],sram_kib=capacity/1024,
                 reset_mean_cycles=cycles,continuous_mean_cycles=cont['mean_cycles'],
                 continuous_min_cycles=min(w['cycles'] for w in cont['windows']),
                 continuous_max_cycles=max(w['cycles'] for w in cont['windows']),
                 nominal_latency_ms_150mhz=cycles/150000,nominal_tasks_per_second_150mhz=150000000/cycles,
                 fifo_wait=int(p['5']),request_wait=int(p['7']),mac_active_cycles=int(p['4']),
                 initial_dma_load_cycles=int(p['1']),compute_writeback_cycles=int(p['2']),
                 dma_read_words=int(p['9']),dma_write_words=int(p['10']),wait_mode=opts['wait_mode'],
                 product_pipe=opts['product_pipe'],passed_reset_tasks=12,passed_continuous_tasks=12,
                 backend_area=None,backend_power=None,backend_wns=None)
        rows.append(row)
    formatter=load(ROOT/'reports/formatter/results.json')
    if not formatter.get('passed') or any(sha(ROOT/p)!=h for p,h in formatter['inputs'].items()):
        raise ValueError('Formatter tests stale')
    for test in formatter['tests']:
        if sha(ROOT/test['log'])!=test['log_sha256']:raise ValueError('Formatter log changed')
    server=load(ROOT/'reports/server_tool_tests.json')
    if not server.get('passed') or any(sha(ROOT/p)!=h for p,h in server['inputs'].items()):
        raise ValueError('Server driver tests stale')
    if sha(ROOT/'reports/server_tool_tests.log')!=server['log_sha256']:
        raise ValueError('Server test log changed')
    for label in ('server_tcl_tests','native_exporter_tests'):
        extra=load(ROOT/'reports'/(label+'.json'))
        if not extra.get('passed') or sha(ROOT/'reports'/(label+'.log'))!=extra['log_sha256']:
            raise ValueError('Supplemental server test evidence missing: '+label)
    ref=rows[0]['reset_mean_cycles']
    for row in rows:
        row['cycle_reduction_vs_ref_percent']=100*(1-row['reset_mean_cycles']/ref)
        row['throughput_gain_vs_ref_percent']=100*(ref/row['reset_mean_cycles']-1)
    return rows

def report(rows):
    save(ROOT/'reports/comparison.json',rows)
    for row in rows:
        case=ROOT/'study/cases'/row['name']
        text=('# '+row['name']+'\n\n'
            '独立本科FFN1候选；数值格式和输出协议与同组对照相同。\n\n'
            '- MAC：{macs}；本地SRAM：{sram_kib:.0f} KiB（不含共享SRAM/TCM）。\n'
            '- 复位任务严格窗口平均：{reset_mean_cycles:.1f}拍；连续任务平均：{continuous_mean_cycles:.1f}拍。\n'
            '- 相对原最快版周期减少：{cycle_reduction_vs_ref_percent:.2f}%。\n'
            '- 150MHz折算：{nominal_latency_ms_150mhz:.6f} ms，{nominal_tasks_per_second_150mhz:.2f} task/s。\n'
            '- task00 FIFO满等待：{fifo_wait}拍；DMA请求等待：{request_wait}拍。\n'
            '- 12次复位＋12次连续任务，输出逐位核对通过。\n\n'
            '面积、时序、活动功耗与任务能量未在本机测量。\n'
            '在交付根目录运行：`bash run_server.sh --quick --case {name}`。\n'
            '本组配置见case.json；完整日志与证据见交付根目录reports。\n').format(**row)
        (case/'README.md').write_bytes(text.encode('utf-8'))
    with (ROOT/'reports/comparison.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# 本科 FFN1 前端候选结果（2026-11-05）','',
        '本报告由已绑定源码/固件/向量的真实E203整机仿真日志生成。无本机DC、面积、时序或功耗结果。',
        '共同条件：INT16输入/权重、INT32 bias、INT40精确累加，99×64乘64×256；packed40输出。',
        '严格窗口：第一笔Host装载请求至最后DMA写响应；一次性启动和结果回读不计入。',
        '所有候选使用同一Host装载方式、32位共享存储接口及12层权重/合成X，输出逐位一致。','',
        '| 设计 | MAC | 本地SRAM KiB | 复位平均拍数 | 连续平均拍数 | 相对原最快版少用周期 | 150MHz折算ms | FIFO满等待(task00) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('| {name} | {macs} | {sram_kib:.0f} | {reset_mean_cycles:.1f} | {continuous_mean_cycles:.1f} | {cycle_reduction_vs_ref_percent:.2f}% | {nominal_latency_ms_150mhz:.6f} | {fifo_wait} |'.format(**r))
    lines+=['','## 设计分类','',
        '- `ref32_packed_pause`：原最快版RTL、暂停轮询固件原样保留，仅修正测试平台时间戳记录。',
        '- `q32_pause`：仅替换输出格式器；独立组装寄存器与两项完成组队列重叠工作，用于归因。',
        '- `q32_fused_pause`：在双缓冲上开启原有组间首乘积融合；32 MAC速度候选。',
        '- `q32_fused_wfi`：同一32 MAC数据通路，改用中断等待；能耗候选，需服务器测量。',
        '- `q64_fused_pause`：四行共享权重、64 MAC、融合及双缓冲；吞吐候选。',
        '- `q64_fused_wfi`：同一64 MAC数据通路，改用中断等待；能耗候选。',
        '- `q64_pipe_pause`：64 MAC候选增加已有乘积和寄存级；时序探索候选，不预先声称频率更高。','',
        'WFI镜像使用随包源码及GCC 13.2重新编译，暂停轮询镜像沿用已验证的原版；源码、编译参数与镜像散列见qualification记录。',
        '因此WFI对比是整个等待固件方案对比，不能将全部周期差归因于WFI指令本身。','',
        '## 验证与判断边界','',
        '- 每组12次复位任务＋12次不复位连续任务；每任务25,344个结果，DMA读11,616字、写31,680字。',
        '- 四状态Icarus格式器测试覆盖INT64/packed40、随机负数/极值、非单调组地址、长背压、清空及错误索引。',
        '- 服务器驱动52项测试运行无失败，WSL原运行跳过5项Tcl测试及native测试类；Tcl已在Windows补跑5项全部通过，native导出器另用WSL g++补测。均不表示实际VCS/DC已执行。',
        '- Yosys仅做RTL展开、通用优化和结构检查：32/64个16×16有符号乘法器，真实SRAM实例数量通过；没有工艺映射。',
        '- 32 MAC本地宏：12×128×16＋16×1024×16；64 MAC：20×128×16＋16×1024×16。SoC另有80×4096×16。',
        '- 原版与新版本均使用整数fs计时辅助模块，避开本机Verilator 5.020对$realtime的截断。每条窗口另与时钟边沿计数交叉核对。',
        '- 连续运行的CPU通知/启动相位与复位任务不同，分别报告；不能用更有利的一种口径替换另一种。',
        '- SRAM容量和通用逻辑统计不等于工艺面积；150MHz时延/吞吐仅为同频折算。',
        '- 64 MAC版本输出端背压明显：继续增加MAC前应先测PPA和输出瓶颈；原始请求等待与计算可重叠，不能直接从总周期扣除。',
        '- 原12层整数模型逐位一致不等于FP32无误差，也不构成官方音频评测结论。','',
        '## 服务器优先顺序','',
        '先运行原版、q32_fused_pause、q64_fused_pause、q64_pipe_pause的task00快速PPA；',
        '再加入WFI候选比较真实活动功耗；最后对保留设计运行12任务。具体命令见根目录README。',
        '请返回完整comparison.csv/json及原始面积、setup/hold、SAIF覆盖和每任务功耗报告。不要用vectorless功耗替代任务能量。','']
    (ROOT/'reports/RESULTS.md').write_bytes('\n'.join(lines).encode('utf-8'))

def package():
    out=ROOT/'output';out.mkdir(exist_ok=True)
    archive=out/'ffn1_frontend_candidates_2026-11-05.tar.gz'
    paths=[]
    for folder in ('rtl','tools','tests','reports'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc',):paths.append(p)
    for p in (ROOT/'study').rglob('*'):
        relative=p.relative_to(ROOT/'study')
        if not p.is_file() or any(x in relative.parts for x in ('tmp','__pycache__','server')):continue
        if p.suffix in ('.pyc','.elf','.bin','.vcd','.saif','.db','.lib','.ddc'):continue
        if 'output' in relative.parts and 'firmware' not in relative.parts:continue
        if p.name=='local_config.tcl':continue
        paths.append(p)
    paths += [ROOT/n for n in ('README.md','PLAN.md','run_server.sh')]
    paths=sorted(set(paths))
    manifest={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    save(out/'package_manifest.json',manifest)
    with tarfile.open(archive,'w:gz') as tar:
        for p in paths:tar.add(p,arcname='ffn1_frontend_candidates/'+p.relative_to(ROOT).as_posix(),recursive=False)
        tar.add(out/'package_manifest.json',arcname='ffn1_frontend_candidates/package_manifest.json')
    with tarfile.open(archive) as tar:
        for rel,digest in manifest.items():
            actual=hashlib.sha256(tar.extractfile('ffn1_frontend_candidates/'+rel).read()).hexdigest()
            if actual!=digest:raise ValueError('Archive byte mismatch: '+rel)
    digest=sha(archive)
    (out/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n')
    print('PACKAGE_PASS',archive,'bytes',archive.stat().st_size,'sha256',digest,flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',action='store_true');args=ap.parse_args()
    rows=audit();report(rows)
    print('AUDIT_PASS',len(rows),'cases',len(rows)*24,'tasks',len(rows)*24*25344,'outputs',flush=True)
    if args.package:package()
