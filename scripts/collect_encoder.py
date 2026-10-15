"""Fail-closed collection of full-encoder results, same-configuration A/B and provenance."""
from collections import Counter
from datetime import datetime,timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'output/design';DEST=ROOT/'output/encoder-design'
BASE='3461cf71deb5296f6b221e94a188ec94758a55d9'
STATS=['front_cycles','tail_cycles','ffn_dma_cycles','encoder_dma_read32','encoder_dma_write32',
       'encoder_sram_read16','encoder_sram_write16','encoder_saturations']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def require(condition,message):
    if not condition:raise RuntimeError(message)

def soc(name,count,baseline=0):
    p=LOG/(name+'-run.log');text=p.read_text()
    rows=[dict(task=int(t),cycles=int(c),outputs=int(o)) for t,c,b,o in
          re.findall(r'ENC_SOC_TASK_PASS task=(\d+) cycles=(\d+) baseline=(\d+) outputs=(\d+)',text) if int(b)==baseline]
    require(len(rows)==count and [r['task'] for r in rows]==list(range(count)),name+' missing tasks')
    require(all(r['outputs']==6336 for r in rows),name+' output count')
    require('ENC_SOC_PASS tasks='+str(count) in text,name+' missing completion')
    profile={}
    for t,l,i,v in re.findall(r'ENC_LAYER_STATS task=(\d+) layer=(\d+) index=(\d+) value=(\d+)',text):
        key=(int(t),int(l),int(i));require(key not in profile,'Duplicate profile');profile[key]=int(v)
    require(len(profile)==count*12*8,name+' missing layer counters')
    for t in range(count):
        layers=[]
        for l in range(12):
            d={s:profile[t,l,i] for i,s in enumerate(STATS)}
            require(d['encoder_saturations']==0,'Unexpected clipping')
            require(d['encoder_dma_read32']==(35712 if baseline or l==0 else 29376),'DMA read count')
            require(d['encoder_dma_write32']==(9504 if baseline or l==11 else 3168),'DMA write count')
            layers.append(d)
        rows[t]['layers']=layers
        sums={s:sum(d[s] for d in layers) for s in STATS};rows[t]['sums']=sums
        rows[t]['load_cpu_and_notification_cycles']=rows[t]['cycles']-sum(sums[s] for s in STATS[:3])
        require(rows[t]['load_cpu_and_notification_cycles']>=0,'Cycle accounting')
    memory=[]
    for line in text.splitlines():
        if line.startswith('ENC_MEMORY '):memory.append({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)})
    return dict(passed=True,tasks=rows,memory=memory,log=p.relative_to(ROOT).as_posix(),sha256=sha(p))

def main():
    checks={}
    markers={
        'tb_encoder-run.log':'ENCODER_PASS layers=12',
        'tb_encoder_constant-run.log':'ENCODER_PASS layers=1 constant_edge=1',
        'icarus-tb_encoder.log':'ENCODER_PASS layers=1',
        'tb_encoder_math-run.log':'ENC_MATH_PASS divide=1029 sqrt=1031 exp=34855 clear',
        'icarus-tb_encoder_math.log':'ENC_MATH_PASS divide=1029 sqrt=1031 exp=34855 clear',
        'tb_encoder_faults-run.log':'ENC_FAULTS_PASS', 'icarus-tb_encoder_faults.log':'ENC_FAULTS_PASS',
        'tb_dma_arbiter-run.log':'ENC_ARBITER_PASS f=500 e=500',
        'icarus-tb_dma_arbiter.log':'ENC_ARBITER_PASS f=500 e=500'}
    for name,marker in markers.items():
        p=LOG/name;require(marker in p.read_text(),name+' failed');checks[name]={'passed':True,'sha256':sha(p)}
    require((LOG/'encoder-lint.log').exists(),'Missing lint')
    require(not (LOG/'encoder-lint.log').read_text().strip(),'Strict lint not clean')
    checks['encoder-lint.log']={'passed':True,'sha256':sha(LOG/'encoder-lint.log')}
    compatibility={}
    for mode,target in [('tb_soc',271678),('tb_soc_ffn',306709)]:
        for suffix in ['', '_netlist']:
            name=mode+'_encoder_compat'+suffix+'-run.log';p=LOG/name;text=p.read_text()
            tasks=[(int(t),int(c)) for t,c in re.findall(r'SOC_TASK_PASS task=(\d+) cycles=(\d+)',text)]
            require(len(tasks)==12 and [t for t,c in tasks]==list(range(12)),name+' incomplete')
            require(all(c==target for t,c in tasks),name+' v8 performance regression')
            compatibility[name]={'cycles_per_task':target,'tasks':12,'sha256':sha(p)}
    rtl=soc('tb_encoder_soc',12);netlist=soc('tb_encoder_soc_netlist',1)
    optimized=soc('tb_encoder_soc_profile',1);baseline=soc('tb_encoder_soc_baseline',1,1)
    require(rtl['tasks'][0]==netlist['tasks'][0]==optimized['tasks'][0],'RTL/netlist/profile disagreement')
    require(len(optimized['memory'])==len(baseline['memory'])==1,'Missing memory A/B')
    for r in [optimized,baseline]:
        m=r['memory'][0];require(m['ffn_dma_read32']==12*19872 and m['ffn_dma_write32']==12*12672,'FFN DMA counts')
        require(m['ffn_read16']==44559744 and m['ffn_write16']==781056,'FFN SRAM access regression')
    a=baseline['tasks'][0];b=optimized['tasks'][0]
    ab=dict(baseline_cycles=a['cycles'],optimized_cycles=b['cycles'],saved_cycles=a['cycles']-b['cycles'],
            cycle_reduction_percent=100*(a['cycles']-b['cycles'])/a['cycles'],speedup=a['cycles']/b['cycles'],
            same_hardware_and_firmware=True,changed_configuration='resident input and suppressed intermediate output only')
    for label,r in [('baseline',baseline),('optimized',optimized)]:
        sums=r['tasks'][0]['sums'];m=r['memory'][0]
        ab[label+'_dma_words']=sums['encoder_dma_read32']+sums['encoder_dma_write32']+m['ffn_dma_read32']+m['ffn_dma_write32']
        ab[label+'_internal_sram_read16']=sums['encoder_sram_read16']+m['ffn_read16']
        ab[label+'_internal_sram_write16']=sums['encoder_sram_write16']+m['ffn_write16']
    ab['saved_dma_words']=ab['baseline_dma_words']-ab['optimized_dma_words']
    require(ab['saved_dma_words']==2*11*6336,'Cross-layer reuse traffic mismatch')
    ab['saved_dma_bytes']=4*ab['saved_dma_words'];ab['dma_reduction_percent']=100*ab['saved_dma_words']/ab['baseline_dma_words']
    net=read(DEST/'encoder_soc_netlist.json');mod=net['modules']['kwt_encoder_soc']
    require('Found and reported 0 problems.' in (LOG/'encoder-synthesis.log').read_text(),'Missing synthesis structural check')
    for name,digest in read(DEST/'synthesis-source-sha256.json')['sha256'].items():
        content=(ROOT/name).read_bytes().replace(b'\r\n',b'\n').rstrip()+b'\n'
        require(hashlib.sha256(content).hexdigest()==digest,'RTL changed since synthesis: '+name)
    default_aw=net['modules']['kwt_sram16']['parameter_default_values']['AW']
    banks=Counter(int(c['parameters'].get('AW',default_aw),2) for c in mod['cells'].values() if c['type']=='kwt_sram16')
    require(banks=={12:2,10:108,7:12},'Unexpected SRAM architecture')
    latches=[c for c in mod['cells'].values() if 'LATCH' in c['type']]
    require(len(latches)==8 and all('e203_clkgate.v' in c.get('attributes',{}).get('src','') for c in latches),'Unexpected accelerator latches')
    stat=read(DEST/'soc-synthesis-stat.json')['design']
    hardware=dict(ffn_mac_lanes=16,encoder_shared_multiply_lanes=4,gelu_units=1,
                  auxiliary_arithmetic='exp interpolation and GELU operators are additional; MAC lane count is not total multiplier count',
                  internal_sram_bytes=sum(2*(1<<aw)*n for aw,n in banks.items()),internal_sram_macro_count=sum(banks.values()),
                  internal_sram_macros_by_address_bits=dict(banks),shared_sram_bytes=524288,
                  generic_soc_cells=stat['num_cells'],scopeinfo_cells=stat['num_cells_by_type'].get('$scopeinfo',0),
                  synthesis='Yosys synth -flatten -noabc; abc -fast; preserved SRAM leaves; no technology mapping',
                  upstream_clock_gate_latches=len(latches))
    sdc=(ROOT/'constraints/kwt_encoder_soc.sdc').read_text();covered=set()
    for group in re.findall(r'\[get_ports\s+([^\]]+)\]',sdc):
        for pat in group.strip('{} ').split():
            matches=fnmatch.filter(mod['ports'],pat);require(bool(matches),'SDC unmatched '+pat);covered.update(matches)
    require(covered==set(mod['ports']),'SDC port not covered')
    numeric={}
    for split,folder,n in [('validation','encoder-vectors',120),('training','encoder-calibration',24)]:
        base=ROOT/'output'/folder;report=read(base/'numeric-report.json')
        require(report['samples']==n and report['passed'],split+' numeric evidence incomplete')
        for path,digest in read(base/'manifest.json').items():require(sha(base/path)==digest,'Vector hash mismatch '+path)
        numeric[split]={k:v for k,v in report.items() if k!='tasks'}
        numeric[split]['report_sha256']=sha(base/'numeric-report.json');numeric[split]['manifest_sha256']=sha(base/'manifest.json')
    preserved=['rtl/kwt_accel.sv','rtl/kwt_dma.sv','rtl/kwt_gelu.sv','rtl/kwt_mac40.sv','rtl/kwt_sram16.sv',
               'integration/kwt_bus_fabric.sv','integration/kwt_soc.sv','integration/kwt_system_bus.sv',
               'firmware/main.c','firmware/kwt_driver.c','tests/tb_soc.sv','tests/tb_soc_ffn.sv','model/format.json','model/ffn-format.json']
    for path in preserved:
        old=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT).replace(b'\r\n',b'\n')
        require(old==(ROOT/path).read_bytes().replace(b'\r\n',b'\n'),'Preserved baseline changed '+path)
    sources={p.relative_to(ROOT).as_posix():sha(p) for directory in ['rtl','integration','firmware','model','tests','constraints','scripts']
             for p in sorted((ROOT/directory).glob('*')) if p.is_file() and p.suffix in ['.sv','.v','.vh','.c','.h','.S','.ld','.json','.py','.sdc']}
    ppa=dict(target_clock_hz=150000000,timing_closed=False,official_area_mm2=None,power_mw=None,energy_per_inference_mj=None,
             physical_area_limit_mm2=2.25,official_600_sample_evaluation=False,
             gate_simulation='Zero-delay generic netlist; no SRAM timing models',
             scope='Both accelerators, DMA/controllers, added bus/arbiter/interface and all internal SRAM; shared SRAM/CPU reported separately',
             activity_available=False,
             missing=['official standard-cell and SRAM libraries','mapped STA and physical area','mapped switching activity and SRAM power','official 600-sample/platform evaluation'])
    report=dict(generated_at_utc=datetime.now(timezone.utc).isoformat(),scope='Local complete PostNorm encoder extension; official acceptance pending',
                floating_reference='Pinned upstream KWT-1 best_weights; TensorFlow 2.4.0 development fallback, official runtime equivalence pending',
                base_commit=BASE,preserved_source_files=preserved,source_sha256=sources,numeric=numeric,
                checks=checks,compatibility=compatibility,rtl=rtl,netlist=netlist,optimized_profile=optimized,baseline_profile=baseline,
                reuse_comparison=ab,hardware=hardware,ppa=ppa,sdc_port_coverage_checked=True,
                firmware_sha256=sha(DEST/'firmware/encoder.bin'),netlist_sha256=sha(DEST/'encoder_soc_netlist.v'),
                synthesis_log_sha256=sha(LOG/'encoder-synthesis.log'),synthesis_script_sha256=sha(DEST/'synth.ys'),
                synthesis_source_manifest_sha256=sha(DEST/'synthesis-source-sha256.json'))
    (ROOT/'docs/encoder-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    cycles=b['cycles'];ms=cycles/150000.;rate=150000000/cycles
    rows='\n'.join('| '+s+' | '+str(a['sums'][s])+' | '+str(b['sums'][s])+' |' for s in STATS)
    md=f'''# 完整编码器实测性能

同一条固定输入执行全部 12 层，**{cycles:,} 周期**；按目标 150 MHz 折算 **{ms:.6f} ms、{rate:.6f} 次/秒**。这是完整编码器的工作量，不能与仅一个 FFN 的 306,709 周期直接计算加速比。150 MHz 尚未完成正式工艺 STA。

## 同配置跨层复用 A/B

两组使用相同 RTL、固件机器码、参数、输入、共享 SRAM 和加载顺序，仅改变驻留输入与中间写回标志。计时包含初始输入、每层参数加载、CPU 调度/统计、全部硬件计算和最终写回确认；不包含初始固件装载和计时后的逐字比较。

| 指标 / 完整 12 层推理 | 每层写回并重读 | 跨层驻留 |
| --- | ---: | ---: |
| 总周期 | {a['cycles']:,} | {b['cycles']:,} |
| 两个 DMA 读写总字数（32 位） | {ab['baseline_dma_words']:,} | {ab['optimized_dma_words']:,} |
| 内部 SRAM 读访问（16 位宏） | {ab['baseline_internal_sram_read16']:,} | {ab['optimized_internal_sram_read16']:,} |
| 内部 SRAM 写访问（16 位宏） | {ab['baseline_internal_sram_write16']:,} | {ab['optimized_internal_sram_write16']:,} |
| 内部 SRAM 容量 / 宏数 | 235 KiB / 122 | 235 KiB / 122 |

减少 **{ab['saved_cycles']:,} 周期（{ab['cycle_reduction_percent']:.4f}%）**；减少 **{ab['saved_dma_words']:,} 个 32 位传输字 / {ab['saved_dma_bytes']:,} B（{ab['dma_reduction_percent']:.4f}%）**。没有增加资源或改变算术。SRAM 访问减少不能直接解释为同百分比功耗下降。

## 阶段与访问计数

以下 front/tail/FFN 周期互不重叠，可相加；余下加载、CPU、通知观察为 {b['load_cpu_and_notification_cycles']:,} 周期。front 包含注意力、第一次残差/LN 和 FFN 输入写出；tail 包含 FFN 输出读取、第二次残差/LN 与末层写出。

| 计数器（12 层求和） | 对照 | 跨层驻留 |
| --- | ---: | ---: |
{rows}

每次推理参数载入 **400,896 个 32 位字 / 1,603,584 B**，另有初始 X 的 25,344 B。SRAM 统计区分内部 16 位宏访问与共享 SRAM 32 位访问。共享 SRAM 的 CPU/主机/DMA 实际读写也记录在 JSON 的 `memory` 字段，包含轮询和统计访问；不要与仅 DMA 字数混用。

## 精度、兼容性与验证范围

- 12 条不同输入，每条 12 层真实 E203 + 硬件 RTL，最终各 6,336 个输出与整数模型逐位一致。
- 综合后网表运行 1 条输入全部 12 层，输出、周期和硬件计数与 RTL 一致；无工艺延时。
- 原独立 FFN1、完整 FFN 各 12 个任务，在拓展 SoC 的 RTL 与网表中均维持 **271,678 / 306,709 周期**。
- 组件测试核对 12 层的 Q/K/V、分数、概率、PV、输出投影、残差/LN 中间结果。除法 1,029 例、平方根 1,031 例、指数近似 34,855 例通过 RTL 和四态测试。
- 两路 DMA 仲裁各 500 个事务，覆盖阻塞、响应归属与同拍退休/接受；配置错误、中止/排空、读错、最后写错、复位和重启通过 RTL/四态测试。
- 120 条本地验证样本分类 119/120，与浮点预测全部一致；最大逐层聚合 NRMSE 0.171713%。官方 600 条准确率待验收。

## 资源与 PPA 边界

原 FFN 16 路 MAC 和 1 个 GELU 保留，新增 4 路共享 32 位乘法算术路径；指数插值另有辅助算术。内部 SRAM 从 88.5 KiB 增至 **235 KiB**，宏数从 40 增至 **122**。总线共享 SRAM 仍为 512 KiB。

完整 E203 拓展 SoC 通用综合统计 {hardware['generic_soc_cells']:,} 个实例（含 {hardware['scopeinfo_cells']} 个 `$scopeinfo` 元数据实例和黑盒存储边界），使用 ABC fast 通用映射。它不是标准单元面积，不能与不同综合选项的历史实例数作物理面积比较。八个锁存器均来自原 E203 时钟门控，未新增加速器锁存器。

正式 **150 MHz、≤2.25 mm²、功耗和每次推理能耗尚未验证**，仍需官方单元/SRAM 库与评测条件。下一步性能重点是注意力投影/QK/PV 与参数传输；现有 FFN 快速模式已经保留，无需为使用拓展放弃它。

原始证据和 SHA-256 见 [encoder-validation.json](encoder-validation.json)，接口及复现见 [full-encoder.md](full-encoder.md)。
'''
    (ROOT/'docs/encoder-performance.md').write_text(md,encoding='utf-8')
    print(json.dumps({'cycles':cycles,'nominal_ms':ms,'reuse':ab,'hardware':hardware},indent=2))

if __name__=='__main__':main()
