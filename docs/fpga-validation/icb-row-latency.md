# Z100 上的 12 层 KWT 延迟验证

2026-11-18，在 Z100（XC7Z035-2）上通过千兆以太网实测。上位机每次选取一个验证样本，读取音频，完成 MFCC、嵌入和 Q16 转换，发送特征并接收类别及 logits。55.56 MHz 版在这 120 次请求中最慢 **86.24 ms**，相对 100 ms 限值留有 **13.76 ms**。模型与数据索引已在应用启动时初始化。录音入口另外采集一秒音频。计时终点是上位机收到结果。

## 同一批输入的实测

| 固定验证集，逐次新建 TCP 连接 | 原系统 40 MHz | 50 MHz | 55.56 MHz |
| --- | ---: | ---: | ---: |
| 板上中位耗时 | 146.13 ms | 64.22 ms | 58.05 ms |
| WAV 到结果中位数 | 166.51 ms | 79.44 ms | 67.19 ms |
| WAV 到结果 P95 | 182.79 ms | 88.09 ms | 83.06 ms |
| WAV 到结果最大值 | 260.75 ms | 91.72 ms | 86.24 ms |
| 实测端到端吞吐 | 5.97 次/秒 | 12.95 次/秒 | 14.17 次/秒 |
| 100 ms 内完成 | 0/120 | 120/120 | 120/120 |

固定清单包括 110 个 WAV 条目和 10 个静音条目。每条请求均重新生成并发送 6,336 个特征值。P95 采用就近秩，吞吐按总请求数除以整批墙钟时间计算。Windows 的调度和网络负载会影响单次耗时。[40 MHz 对照](icb-row-evidence/40mhz-desktop.json) · [50 MHz 原始记录](icb-row-evidence/50-board-desktop.json) · [55.56 MHz 原始记录](icb-row-evidence/board-desktop.json)

复用同一 TCP 连接时，12 条 WAV 连续执行 10 轮，55.56 MHz 版中位数 **61.12 ms**，P95 **66.67 ms**，最大 **80.21 ms**，吞吐 **16.09 次/秒**。桌面程序的实际识别入口另测 yes、no、stop、go，均收到 12 次层进度，显示的识别耗时为 62.48 至 77.17 ms。[连续请求](icb-row-evidence/board-throughput.json) · [桌面程序记录](icb-row-evidence/board-gui.json)

## 板上数据流

- E203 经现有 HBirdv2 ICB 分发器访问 512 KiB 系统共享 SRAM。行调度器把 99 行分给 7 个本科生 FFN1 实例，前 6 路各处理 16 行。末路计算补齐到 8 行，只提交 3 行有效结果。所有实例均引用仓库内同一份本科生 RTL。行调度配置使用模式 4 的输入、输出流。原有单引擎构建入口仍可单独选择。
- 12 层参数仍由加载器逐层写入共享 SRAM。行引擎读完 FFN 权重才接收 LN1 输入，Front 完成后 E203 写入当前层的释放标记。加载器收到对应标记才复用这三个权重窗口，下一层的参数传输与当前层剩余计算重叠。每条新任务清除标记并重新装入全部权重。共享 SRAM、E203 的存储器及并行计算核的局部缓存分别计数。
- 55.56 MHz 固定验证集每条平均 **3,225,025 个 PL 周期**。一次板上计数为 3,224,884 周期，其中输入搬运 17,576 周期，全部权重搬运累计 1,113,257 周期，11 次预取共占用加载器 1,020,894 周期。预取与计算共享一段墙钟时间。板上计时从输入装载到第 12 层写回，按原口径扣除进度回调。上位机端到端计时包含进度通信、分类及结果回传。[板上计数](icb-row-evidence/board-profile.log)
- 上位机并行进行 TCP 握手与 WAV 准备，对 PCM16 单声道验证音频直接解码并执行原模型特征提取。已与原音频流程比对固定清单的全部 760,320 个 Q16 特征。[逐位检查记录](icb-row-evidence/rtl-validation.txt)

## 正确性和实现

两种频率均通过 12 条冻结输入，逐条比对第 12 层输出的全部 6,336 个 Q16 整数，总计 76,032 个一致。固定验证集 120/120 条与软件定点预测一致，119/120 条与真实标签一致。RTL 回归另逐层核对 LN1 输入和 FFN 输出，并验证每个任务完成 11 次提前装载。坏 CRC 后重连，连续两次完整输出和 12 层进度均通过。[冻结输入](icb-row-evidence/board-frozen.json) · [固定验证集](icb-row-evidence/board-validation.json) · [错误恢复](icb-row-evidence/board-recovery.log)

| 55.56 MHz 布线后指标 | 实测或报告值 |
| --- | ---: |
| PL 周期 | 18.000 ns |
| WNS / WHS | 0.000 / +0.054 ns |
| TNS / THS | 0 / 0 ns |
| 负 setup / hold 端点 | 0 / 0 |
| 未约束内部端点 / 布线错误网络 | 0 / 0 |
| Slice LUT / 寄存器 | 86,608 / 43,650 |
| BRAM Tile / DSP48E1 | 296.5 / 633 |

55.56 MHz 版经过布线后物理优化，最终 WNS 在报告精度下为零。对应的最终检查点为交付目录中的 `routed.dcp`。原 `impl_1` 路由步骤的报告保留了物理优化前的状态。50 MHz 版使用 20 ns 周期，WNS **+0.332 ns**、WHS **+0.031 ns**。两版都经板上计算周期和独立计数器交叉核对实际时钟。GELU 输入在写激活 BRAM 前保持两拍，55.56 MHz 版中相关数据路径的实际 setup 要求为 36 ns。FPGA DRC 报告包含 DSP 流水和 RAM 异步控制告警，位流生成通过。[最终时序](icb-row-evidence/timing.rpt) · [50 MHz 时序](icb-row-evidence/50-timing.rpt) · [GELU 路径](icb-row-evidence/held-gelu-path.rpt) · [资源](icb-row-evidence/utilization.rpt) · [布线](icb-row-evidence/route.rpt)

## 复现

1. 依照原板卡说明准备 E203 依赖、冻结模型、工具链及 Z100 的以太网 PS 配置。运行 `python scripts/run_encoder.py soc --contest --contest-row-ffn --input-stream 1 --tasks 12 --jobs 3` 构建 E203 固件并回归。[板卡环境](contest-20-task.md)
2. 在已准备好 `vendor/ps_profile_ethernet.tcl` 的构建目录，用 `python integration/z100/run_ross.py contest --ethernet --contest-row-ffn --mhz 55 --build <build>` 生成工程、位流和 XSA。该 PS 配置中请求 55 MHz 得到 55,555,557 Hz。50 MHz 的实分频为 50,000,000 Hz。使用 `build_ethernet.ps1 -Contest -Frequency <实际Hz>` 及其板级依赖参数构建 ARM 固件。本机由 Ross 创建工程并生成 managed run 脚本，分别执行综合、实现和最终物理优化。
3. 在同一目录放置 `encoder.bin`、`kwt.bin`、位流、对应 ELF 及提取的 `ps7_init.tcl`。设置 `Z100_BUILD` 后，以 XSDB 运行 `integration/z100/boot_smoke.tcl z100-contest-55 z100-contest-55-tcp jtag`。串口与 JTAG 可用于调试，本报告的延迟测量使用 `192.168.1.11:5001` 的以太网连接。
4. 用模型环境运行 `integration/z100/demo.py --port 192.168.1.11:5001`。性能复测使用 `benchmark.py --port 192.168.1.11:5001 --all-validation --new-connection --max-end-to-end-ms 100 --output desktop.json`。连续请求去掉 `--all-validation --new-connection`，加 `--passes 10`。正确性回归分别运行 `verify_board.py` 的默认模式及 `--validation`，均传入同一端口。[交付文件校验值](icb-row-evidence/SHA256SUMS.txt)
