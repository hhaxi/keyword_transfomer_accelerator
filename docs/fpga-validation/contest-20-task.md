# 12 层 KWT 的 20 task/s 周期目标

目标是每个任务最多 7,500,000 个 PL 周期，按 150 MHz 折合 50 ms。板上周期从测试加载器开始将输入写入共享 SRAM 到 E203 确认最终结果写回，包含全部 12 层参数装载、E203 调度和 SRAM 仲裁，扣除 TCP 进度帧发送。WAV 到结果另计，包含主机预处理、TCP、板上推理和分类头。

## Z100 实测结果

Vivado 2026.1 在 `xc7z035ffg900-2` 上实现。PL 配置为 **40 MHz**。JTAG 实测 PL 寄存器和 512 KiB 共享 SRAM 首尾地址读写通过。

| 指标 | 结果 |
| --- | ---: |
| 连续性能测试 | 12 条固定 WAV × 10 轮，单 TCP 连接 |
| 板上任务平均周期 | 5,830,108.37 |
| 板上任务最大周期 | 5,840,571（120/120 低于 7,500,000） |
| 150 MHz 等效吞吐量、平均时延 | **25.73 task/s、38.87 ms** |
| 150 MHz 等效最大时延 | 38.94 ms |
| 40 MHz 板上平均时延、吞吐量 | 145.75 ms、6.86 task/s |
| WAV 到结果中位数、P95、最大值 | 150.31 ms、154.90 ms、168.81 ms |
| WAV 到结果吞吐量 | **6.62 task/s**（120 次 / 18.126 s） |
| 12 条冻结输入 | 76,032 个最终整数逐位一致 |
| 固定 120 条验证集 | 120/120 与定点软件参考一致，119/120 命中真值 |

上一版 40 MHz 赛题配置的板上中位数为 411.22 ms，WAV 端到端吞吐量为 2.40 task/s。本版分别为 145.75 ms 和 6.62 task/s，对应 2.82 倍板上加速和 2.76 倍端到端吞吐提升。坏 CRC 后重连，两次完整回读与每次 12 条进度消息均通过。

末次恢复测试的 JTAG 周期分解为 5,830,097 个总周期，输入装载 16,920 周期，12 层参数装载 1,068,961 周期，E203 调度、计算和写回等其余阶段 4,744,216 周期。

| 路由后实现 | 结果 |
| --- | ---: |
| WNS / WHS | +0.157 ns / +0.060 ns |
| TNS / THS | 0 / 0 ns |
| 未约束内部端点 / DRC 错误 | 0 / 0 |
| Slice LUT | 63,591 / 171,900（36.99%） |
| Slice 寄存器 | 26,793 / 343,800（7.79%） |
| BRAM Tile | 183 / 500（36.60%） |
| DSP48E1 | 419 / 900（46.56%） |

FPGA 资源覆盖 E203、加速器、512 KiB 共享 SRAM、E203 TCM 和板卡加载桥。DRC 仍报告 DSP 流水及 RAM 异步控制相关警告。

[逐请求周期和端到端数据](contest-20-task-evidence/board-throughput.json) · [冻结向量](contest-20-task-evidence/board-frozen.json) · [固定验证集](contest-20-task-evidence/board-validation.json) · [布线时序](contest-20-task-evidence/timing.rpt) · [FPGA 资源](contest-20-task-evidence/utilization.rpt) · [SRAM 结构](contest-20-task-evidence/sram-audit.json) · [周期分解](contest-20-task-evidence/board-profile.log) · [CRC 恢复](contest-20-task-evidence/board-recovery.log)

## RTL 和存储

- Q/K/V/O 投影每拍处理 16 个 K 元素。注意力内积每拍处理 32 个元素，Softmax 使用两组单端口 SRAM，依次存放分数、指数和归一化结果。定点运算和舍入规则沿用原实现。
- `kwt_encoder_soc` 的 `0xa0000000–0xa007ffff` 仍是 **512 KiB 单端口共享 SRAM**。每层复用同一参数窗口，装载 33,408 个 32 位参数字和 2 个配置字。输入和最终完整写回各 6,336 个 32 位 Q16 字。FFN 沿用上一版赛题 SoC 的单套 `kwt_dma` / `kwt_accel` 源码，仍由 E203 逐层调度。
- ASIC 结构综合保留 692 个加速器单端口 SRAM 宏（654 × `128×16`、36 × `1024×16`、2 × `4096×16`），共 **251.5 KiB**。这部分独立于 512 KiB 系统共享 SRAM 及 E203 的 ITCM、DTCM。FPGA 将浅 bank 映射到 LUTRAM，较深 bank 使用 BRAM。
- Z100 的 ARM 启动板卡测试加载器。加载器经 PS HP0 从测试夹具的 DDR 读取数据，再从原 Host ICB 端口写进共享 SRAM。测试加载器位于赛题 SoC 顶层之外。E203 和计算核通过原来的共享 SRAM 访问参数和数据。

## 验证

宏版 E203 RTL 的 12 条冻结向量均完成完整 12 层，每条耗时 **6,331,236 周期**，全部 **76,032** 个最终 Q16 整数逐位一致。独立测试覆盖加载器 4 KiB 突发边界、总线背压、目标范围检查、AXI 错误和重试。

150 MHz 等效值是用实测任务周期除频率得到的换算。组委会工艺库的宏映射、2.25 mm² 面积和 150 MHz STA 仍待 ASIC 后端验证。

## 复测

从仓库根目录运行。Vivado、Ross、板卡 BSP、ARM runtime、TCP 源码与原 [512 KiB 赛题配置](contest-sram.md) 相同。按本地安装调整路径，若使用独立构建目录，将该目录传给 `program.ps1 -BuildDir` 并将 `kwt.bin`、`encoder.bin` 和 ARM ELF 放在同目录。

```powershell
.\integration\z100\prepare_smoke.ps1 -Ethernet
python integration/z100/run_ross.py contest --mhz 40 --ethernet --in-process
.\.venv-model\Scripts\python.exe scripts/run_encoder.py soc --contest --input-stream 1 --tasks 12 --jobs 4
.\.venv-model\Scripts\python.exe scripts/run_encoder.py synth --contest
Copy-Item output/encoder-design/firmware/encoder.bin output/z100/
.\.venv-model\Scripts\python.exe integration/z100/model_data.py
.\integration\z100\build_ethernet.ps1 -Contest -Frequency 40000000 -VendorExample output/z100/vendor/ethernet/XC7Z035/36_lwip_echo_server -ArmRuntime output/z100/arm-runtime/extracted/usr -LwipTcpSource output/z100/lwip213-tcp -Output output/z100/z100-contest-40-tcp.elf
.\integration\z100\program.ps1 -Image contest-40 -Firmware z100-contest-40-tcp
.\.venv-model\Scripts\python.exe integration/z100/verify_board.py --port 192.168.1.11:5001 --output output/z100/board-frozen.json
.\.venv-model\Scripts\python.exe integration/z100/benchmark.py --port 192.168.1.11:5001 --passes 10 --output output/z100/board-throughput.json
.\.venv-model\Scripts\python.exe integration/z100/verify_board.py --port 192.168.1.11:5001 --validation --output output/z100/board-validation.json
```
