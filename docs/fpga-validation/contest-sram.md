# 赛题存储配置的 KWT-1 FPGA 验证

[20 task/s 优化版及最新板上实测](contest-20-task.md)。以下为优化前的 40 MHz 基线，复现基线使用提交 `eea4c4b`。

本配置的整机顶层为 `kwt_encoder_soc`，System Bus 挂载 **512 KiB 共享 SRAM**（`0xa0000000` 至 `0xa007ffff`）。真实 E203 执行 RV32 固件，调度 12 层硬件编码器。加载端复用共享 SRAM 的同一组窗口，每层装入 33,408 个参数字（130.5 KiB）及 2 个配置字。输入占 25,344 字节，最后一层将全部 6,336 个 Q16 整数写回。LN2 跨层驻留，LN1 与 FFN2 结果通过片上 FIFO 交接。

与原 Z100 演示版相比，本配置使用 E203 工程的一套完整 FFN `kwt_dma/kwt_accel`，复用其两次线性层和 GELU，无 7 路副本。Q/K/V/O 每拍并行 4 个 K 元素，每个输出组的权重切成 16 个 32 位逻辑 bank。每个逻辑 bank 由 4 个 `128×16` 单端口宏组成，同一组权重 SRAM 在四次投影间复用。ASIC 参考顶层启用 `PROJECTION_K4=1`；标量注意力保留。FPGA 包装仅把 ARM GP AXI4-Lite 转为 E203 SoC 的外部加载口，PL 没有 HP DDR 主端口。ARM 的 DDR 只用于验证平台自身的 TCP 和参数源，效果与组委会加载端对应。主机的音频处理和 ARM 分类头属于演示功能。

## 逻辑容量

| 存储 | 组织 | 容量 |
| --- | --- | ---: |
| 系统共享 SRAM | 131,072 × 32 bit，独立边界 | 512 KiB |
| 加速器内部 SRAM | 76 × 128 × 16 bit | 19 KiB |
| 加速器内部 SRAM | 100 × 1,024 × 16 bit | 200 KiB |
| 加速器内部 SRAM | 2 × 4,096 × 16 bit | 16 KiB |
| **加速器内部宏合计** | **178 个单端口宏** | **235 KiB** |
| E203 自有 ITCM、DTCM | 各 64 KiB | 128 KiB |

相比原 E203 标量版本，投影 bank 的宏数增加、总位数保持不变。宏数量、外围电路和互连需要计入最终 ASIC 面积和时序。当前通用网表保留宏边界，官方工艺库映射、150 MHz STA 与 2.25 mm² 面积签收需在组委会平台上完成。

E203 RTL 回归已跑过全部 12 条冻结输入，每条完整 12 层、6,336 个输出整数，共 76,032 个整数逐位一致。在仿真的加载端条件下每次用时 10,617,875 个周期。该仿真计数包含驱动轮询和分层写入，Z100 实测采用实际 ARM 到共享 SRAM 的加载延迟。

保留 SRAM 宏边界的综合网表通过一条完整 12 层的逐位对照。FPGA 采用上游 `FPGA_SOURCE` 让 E203 时钟直通，512 KiB SRAM 的 FPGA 映射采用 128 个 `1,024×32` bank，外部接口仍是单端口。FPGA RTL 的一条完整 12 层回归和独立 SRAM bank/字节掩码用例均通过。

## Z100 实测

器件为 `xc7z035ffg900-2`，使用 Vivado 2026.1。40 MHz 路由后的 WNS 为 **+0.344 ns**，WHS 为 **+0.062 ns**，未约束内部端点为 0，bitstream DRC 无错误。资源覆盖完整 E203、两套 TCM、共享 SRAM、加速器和板卡加载桥。

| FPGA 资源 | 用量 | 使用率 |
| --- | ---: | ---: |
| LUT | 22,021 / 171,900 | 12.81% |
| 寄存器 | 8,958 / 343,800 | 2.61% |
| BRAM Tile | 252 / 500 | 50.40% |
| DSP48E1 | 83 / 900 | 9.22% |

252 个 BRAM Tile 折合 1,134 KiB 的物理资源，包含宽度、深度及映射粒度带来的空位。512 KiB 共享 SRAM 的首尾地址在实板上独立写读通过。

| 板上测试 | 结果 |
| --- | ---: |
| 固定 12 条 WAV，热 TCP 连接上连续跑 10 轮 | 120 次，49.963 s |
| 板上装载至写回中位数 | 411.22 ms，约 16,448,791 个周期 |
| WAV 到结果中位数 | 415.59 ms |
| WAV 到结果 P95 / 最大值 | 420.16 / 423.42 ms |
| 端到端吞吐 | 2.40 次/秒 |

上板回读的 12 条冻结向量共 76,032 个整数，全部逐位一致。固定 120 条验证样本中，120/120 与软件参考一致，119/120 命中真值。坏 CRC 后重连，连续两次完整回读和 12 层进度通过。性能测试包括 PS 经 GP AXI 逐字装载 12 层参数的开销。原 DDR 直读、7 路 FFN 版的约 50 ms 来自另一套架构。

[布线时序](contest-evidence/timing.rpt) · [资源](contest-evidence/utilization.rpt) · [冻结向量](contest-evidence/board-frozen.json) · [验证集](contest-evidence/board-validation.json) · [性能](contest-evidence/board-throughput.json) · [存储结构](contest-evidence/sram-audit.json)

## 重建

使用仓库固定版 E203、RV32 工具链、冻结向量、Z100 Ethernet BSP，以及原 [FPGA 报告](README.md) 指定的 lwIP 2.1.3 TCP 源码。以下命令从仓库根目录运行，按本机安装配置 Vivado、Ross 及 ARM runtime 路径。

```powershell
.\integration\z100\prepare_smoke.ps1 -Ethernet
python integration/z100/run_ross.py contest --mhz 40 --ethernet --in-process
.\.venv-model\Scripts\python.exe scripts/run_encoder.py soc --contest --input-stream 1 --tasks 12 --jobs 4
.\.venv-model\Scripts\python.exe scripts/run_encoder.py synth --contest
.\.venv-model\Scripts\python.exe scripts/run_encoder.py netlist --contest --input-stream 1 --tasks 1
Copy-Item output/encoder-design/firmware/encoder.bin output/z100/
.\.venv-model\Scripts\python.exe integration/z100/model_data.py
.\integration\z100\build_ethernet.ps1 -Contest -Frequency 40000000 -VendorExample output/z100/vendor/ethernet/XC7Z035/36_lwip_echo_server -ArmRuntime output/z100/arm-runtime/extracted/usr -LwipTcpSource output/z100/lwip213-tcp -Output output/z100/z100-contest-40-tcp.elf
.\integration\z100\program.ps1 -Image contest-40 -Firmware z100-contest-40-tcp
```

板上任务计时从 ARM 开始写输入到 E203 报告最终输出写回完成，扣除 TCP 进度帧的发送开销，包含参数装载、总线等待和 E203 调度。复测使用同一套 `verify_board.py` 和 `benchmark.py`，端到端计时覆盖 WAV 读入至结果接收。
