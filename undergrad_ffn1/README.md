# 本科 FFN1 独立工程

当前周期、服务器截图PPA及Git复现说明见 [soc-results-2026-11-02.md](docs/soc-results-2026-11-02.md)。Git版不存重复case目录，首次执行 `python3 tools/sweep.py prepare` 生成16种配置。

后续方案集中在 [candidates/](candidates/README.md)，其中 [Q128 IRQ/WFI](candidates/q128_reference_sleep/README.md) 提供同条件 `task00` 的服务器 PPA 和 12 层本地功能结果。

本目录是后续本科优化的工作根目录。原研究生/完整Encoder工程保留在父目录，
本版本的RTL、固件、数值模型、向量、E203源文件、测试及DC脚本均独立保存。
运行源码不依赖父目录；本机工具路径配置可以指向已安装的EDA工具。

硬件仅实现 `Y[99,256] = X[99,64] * W[64,256] + bias[256]`，不包含
Attention、GELU、FFN2、编码器调度或额外结果直传链路。

| 组成 | 当前默认优化版本 |
|---|---|
| FFN1 | 16个16×16 MAC，40位精确累加，八列/每拍两个k |
| 格式 | X/W INT16，bias INT32；输出INT40符号扩展至INT64 |
| 加速器SRAM | 16×1024×16 + 8×128×16，34KiB/24宏 |
| SoC | 固定版本真实E203，512KiB共享SRAM、64KiB ITCM、64KiB DTCM |
| 整机SRAM | 16×1024×16 + 8×128×16 + 80×4096×16，674KiB/104宏 |
| CPU取指 | 从共享启动映像经CPU复制到ITCM，执行fence.i后运行 |
| X缓存 | A/B两组奇偶bank，当前行计算与下一行DMA装载重叠 |
| Host | 连续请求/响应握手，全部数据响应完成才发布任务命令 |
| 默认仲裁 | DMA_BURST=1，HOST_BURST=0 |

这些是结构检查得到的宏数量/容量，不是标准单元面积或实测功耗。

## 基线、逐项检查点与16组合对照

原版冻结在 `experiments/baseline/`，散列在 `experiments/baseline_frozen.json`。
原始源码保持不变。四项已批准优化为 ITCM、Host连续加载、小X双缓冲、bias缩容。
数值格式、16路MAC、仲裁参数、64位输出格式均不变；未实施中断、packed40或PE阵列。

| 累加检查点 | 任务周期（每任务重新复位） | 加速器SRAM | DC入口 |
|---|---:|---:|---|
| 原版基线 | 167134 | 52KiB | dc/00_baseline.tcl |
| +ITCM | 152827 | 52KiB | dc/01_itcm.tcl |
| +Host连续加载 | 131922 | 52KiB | dc/02_host.tcl |
| +小X双缓冲 | 128317 | 37KiB | dc/03_small_x.tcl |
| +bias缩容 | 128317 | 34KiB | dc/04_bias.tcl |

16种组合均已通过12组参数的复位及连续运行验证，共384次任务，每任务25344个
输出逐项一致。上表列出累加优化结果；完整组合、计数和后续DC结果汇总在
`experiments/results/comparison.csv`、`comparison.json`。每种组合独立目录和固件，
名字如 `i1_h1_x1_b1`：i=ITCM、h=Host连续、x=小X、b=小bias；0关闭、1开启。
`experiments/checkpoints/`保存实施各阶段的源码/日志，`dc/`为统一、最新的综合入口。

ITCM/Host模式不改变静态硬件，因此16模式只有4种不同的硬件结构。批量DC默认
按实际RTL/约束散列复用相同硬件结果，逐行保留来源；仿真仍分别测试全部16模式。

旧DC批次已完成但面积检查失败时，运行 `bash run_recover_compare.sh --scope soc`
统一修补面积并从已有DDC恢复、统计16组SoC的PPA，**不重新综合**。详见
`docs/recover-comparison.md`，输出为 `experiments/results/ppa_comparison.csv`。

## 目录和主要入口

```text
rtl/        FFN1核心、DMA、总线和SoC/加速器顶层
tech/       原生RAMSP宏封装、共享SRAM及CPU TCM适配
vendor/     固定版本E203及许可证
firmware/   独立FFN1驱动、启动代码和链接脚本
model/      冻结数值规则、12层FP32参数及转换/运行脚本
vectors/    12套本地功能向量和整数期望结果
tests/      真实CPU整机、MAC、DMA故障/背压及隔离检查
tools/      编译验证、结构检查和打包工具
config/     工艺库路径、时钟与外部接口预算
script/     DC综合及报告恢复Tcl
verification/  基线及验证记录
experiments/   冻结基线、16 组合配置及对照结果
candidates/    后续候选方案及各自的复现入口
docs/       优化计划、接口说明
```

主计算文件：`rtl/kwt_ffn1_core.sv`；搬运文件：`rtl/kwt_ffn1_dma.sv`。
独立加速器顶层为 `kwt_ffn1_top`，整机顶层为 `kwt_ffn1_soc`。

## 本机验证

依赖Python+NumPy、RISC-V GCC、Verilator、GNU Make、Icarus和Yosys。
`environment/local_tools.json`是本机私有路径配置，不进入服务器上传包。
换机器后可配置该文件，或设置 `FFN1_GCC`、`FFN1_VERILATOR`、`FFN1_MAKE`、
`FFN1_IVERILOG`、`FFN1_YOSYS`；未设置时使用PATH中的工具。

从本目录运行：

```powershell
python tests/test_isolation.py
python tests/test_model.py
python tools/verify.py --tasks 12
python tools/verify.py --tasks 12 --continuous --skip-build
python tools/check_components.py
python tools/check_structure.py
python tools/package.py
```

`--skip-build`会核对源码、头文件、固件及可执行文件散列，不能用旧二进制
验证新RTL。每次修改后先重新编译，再做同条件A/B。

已建立的基线见 `verification/baseline.json`。重置任务模式12次均167134拍，
按150MHz折算1.114227ms、897.483任务/秒。不复位连续换参12次也通过，
后续任务167132拍属于CPU/通知相位差，不作为硬件吞吐提升。每项25344个
输出与整数模型逐位一致。

MAC测试覆盖极值、随机、停顿和复位；DMA测试覆盖地址范围/重叠错误、读错、
写错、最终写响应出错、阻塞请求保持、长时间背压、中止排空及不复位恢复。
宏仿真使用独立功能fixture，不是工艺库厂商的时序模型。

测试向量使用指定检查点的12套真实权重和合成输入；不是官方评测任务。
软件模型接收已经按指定上游流程提取的99×64浮点输入，不在硬件中做音频前处理。

## 数值模型与参数转换

```powershell
python model/software_model.py --layer 0 --input input.npy --output decoded.npy --encoded-output integer.npy --export output/converted/layer0
```

`input.npy`形状99×64；参数来自`model/float-parameters.npz`中对应层的
原始FP32 W1/bias，版本与校验值见`model/PROVENANCE.json`。输入、权重
最近偶数舍入后饱和INT16，bias转换INT32，乘加INT40范围内精确，输出不再
截位。每层尺度见`model/format.json`。W按列优先导出，每个32位字打包两个
相邻k的INT16，低半字是先出现的元素。

12组参数通过重新装载X/W/b支持切换，不要求同时驻留12组。每个任务重新
清空有效状态并装载参数，不能把跨任务缓存命中从计时中省略。

## DC服务器运行

将 `output/upload/undergrad_ffn1_sweep.tar.gz` 解压到当前用户Desktop，先加载
服务器提供的Synopsys环境。无需在DC脚本里做lib→db转换。

```bash
cd "$HOME/Desktop/undergrad_ffn1"
# 一次对照16模式；默认复用4种相同硬件的综合结果：
bash run_compare.sh --dc --scope soc
# 若还希望分别综合独立加速器，运行8次不同硬件/范围的综合：
bash run_compare.sh --dc --scope both
# 不复用相同硬件：每个模式单独综合，两个范围共32次：
bash run_compare.sh --dc --scope both --repeat-identical-hardware
# 单独综合当前全优化版本：
bash run_dc.sh --soc
# 仅统计加速器及接口、将CPU/共享SRAM作为边界：
bash run_dc.sh --accelerator
```

标准单元库默认RVT SS 0.99V/125℃；SRAM使用RAMSP128X16、RAMSP1024X16和RAMSP4096X16
的`ss_0p99v_0p99v_125c.db`，从`$HOME/Desktop/lib/`解析，路径可以在
`config/local_config.tcl`覆盖。紧凑方案需要128字宏库，原始方案不要求它。
批量运行时根目录的 `config/local_config.tcl` 统一传给所有case。具体路径与约束均在
`config/library_config.tcl`；EMA/EMAW沿用已确认的0，RET1N为1。

使用`compile_ultra -no_autoungroup`，目标150MHz；在报告检查前保存compiled
DDC和SDC，后续报告失败可以用`recover_reports.sh`恢复。脚本不自动添加
false/multicycle路径。当前uncertainty/外部IO预算沿用原配置，仍需按平台确认。

本机没有运行实际DC/PDK映射，不能据本地Yosys结构检查声称150MHz、面积或
功耗已达标。vectorless功耗不是正式任务平均功耗；正式结果需同任务窗口的
SAIF/VCD、活动映射及SRAM功耗模型。

若服务器还具备功能仿真工具，可同时重跑全部16模式的12任务复位/连续验证：

```bash
bash run_compare.sh --all --scope both --jobs 2
# 只重跑仿真；中途退出后可校验已有证据并恢复：
bash run_compare.sh --sim --jobs 2 --resume
```

默认DC命令使用上传包内已验证的仿真周期，不要求服务器安装Verilator/GCC。
DC失败不会阻止尝试后续case；未知指标保留空值，不能当作0。CSV中的功耗为
vectorless估计；软件模式复用的静态功耗不能代表各模式的真实任务能耗差别。
详见 `docs/server-comparison.md`。

`tests/preflight_stub.tcl`只测试Tcl路径/配置与数量选择；其中dummy文件不是
真实DB，位于tmp，不进入上传包，不能用于正式综合。

## 计时边界和正式平台边界

当前Host/邮箱协议为项目参考集成，不是主办方原版平台认证。每任务从Host
开始写输入/参数计时，到全部结果写回后CPU完成通知被观察为止；包含总线
等待、调度及计算，排除一次性固件装载、文件读取/格式转换和计时后结果检查。
任务之间复位不计时。`boot_wait_cycles`单独报告CPU启动/复制/就绪等待，加上
固定500拍稳定等待；不是纯复制时间。连续任务后续约500拍也不是重新复制。
需要含启动结果时将对应等待区间另计，不能将它静默并入或排除比较口径。
正式接入仍需对照官方平台允许的接口和存储时序。

逐项设计和候选优化见 `docs/optimization-roadmap.md`；实施清单见
`docs/approved-optimization-implementation.md`。DMA的load计数在流式方案只覆盖
W/b及第一行X的启动装载，后续X读取与计算重叠在RUN阶段；不要把load计数当作
整个任务全部DMA传输时间。request_wait与计算也可能重叠，不能直接相减。
