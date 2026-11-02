# 本科 FFN1 独立工程

本目录是后续本科优化的工作根目录。原研究生/完整Encoder工程保留在父目录，
本版本的RTL、固件、数值模型、向量、E203源文件、测试及DC脚本均独立保存。
运行源码不依赖父目录；本机工具路径配置可以指向已安装的EDA工具。

硬件仅实现 `Y[99,256] = X[99,64] * W[64,256] + bias[256]`，不包含
Attention、GELU、FFN2、编码器调度或额外结果直传链路。

| 组成 | 当前基线 |
|---|---|
| FFN1 | 16个16×16 MAC，40位精确累加，八列/每拍两个k |
| 格式 | X/W INT16，bias INT32；输出INT40符号扩展至INT64 |
| 加速器SRAM | 18×1024×16 + 2×4096×16，52KiB/20宏 |
| SoC | 固定版本真实E203，512KiB共享SRAM、64KiB ITCM、64KiB DTCM |
| 整机SRAM | 18×1024×16 + 82×4096×16，692KiB/100宏 |
| 默认仲裁 | DMA_BURST=1，HOST_BURST=0 |

这些是结构检查得到的宏数量/容量，不是标准单元面积或实测功耗。

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

将 `output/upload/undergrad_ffn1.tar.gz` 解压到当前用户Desktop，先加载
服务器提供的Synopsys环境。无需在DC脚本里做lib→db转换。

```bash
cd "$HOME/Desktop/undergrad_ffn1"
bash run_dc.sh --soc
# 仅统计加速器及接口、将CPU/共享SRAM作为边界：
bash run_dc.sh --accelerator
```

标准单元库默认RVT SS 0.99V/125℃；SRAM使用RAMSP1024X16和RAMSP4096X16
的`ss_0p99v_0p99v_125c.db`，从`$HOME/Desktop/lib/`解析，路径可以在
`config/local_config.tcl`覆盖。当前不需要128字宏库。具体路径与约束均在
`config/library_config.tcl`；EMA/EMAW沿用已确认的0，RET1N为1。

使用`compile_ultra -no_autoungroup`，目标150MHz；在报告检查前保存compiled
DDC和SDC，后续报告失败可以用`recover_reports.sh`恢复。脚本不自动添加
false/multicycle路径。当前uncertainty/外部IO预算沿用原配置，仍需按平台确认。

本机没有运行实际DC/PDK映射，不能据本地Yosys结构检查声称150MHz、面积或
功耗已达标。vectorless功耗不是正式任务平均功耗；正式结果需同任务窗口的
SAIF/VCD、活动映射及SRAM功耗模型。

`tests/preflight_stub.tcl`只测试Tcl路径/配置与数量选择；其中dummy文件不是
真实DB，位于tmp，不进入上传包，不能用于正式综合。

## 计时边界和正式平台边界

当前Host/邮箱协议为项目参考集成，不是主办方原版平台认证。每任务从Host
开始写输入/参数计时，到全部结果写回后CPU完成通知被观察为止；包含总线
等待、调度及计算，排除一次性固件装载、文件读取/格式转换和计时后结果检查。
任务之间复位不计时。正式接入仍需对照官方平台允许的接口和存储时序。

本次只做范围裁剪，没有实施后续性能优化。逐项计划见
`docs/optimization-roadmap.md`，按“之前怎么做／打算怎么做／改善指标／风险”说明。
后续先讨论ITCM取指，保持Host加载条件不变；加载器优化单独归因。
