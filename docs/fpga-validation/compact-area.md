# Z100 KWT 面积优化与 100 ms 实板验收

2026-11-19，XC7Z035-2，PL 实际分频 55.56 MHz。选择 1 路本科生 FFN1 配置。面积比较使用 Vivado 布线后的整机资源。以下延迟来自同型号实板上的完整 12 层模型。

| 指标 | 七路参考 | 单路 | 双路 |
| --- | ---: | ---: | ---: |
| Slice LUT | 86,608 | 33,126 | 37,570 |
| 寄存器 | 43,650 | 17,584 | 20,537 |
| BRAM Tile | 296.5 | 215 | 233 |
| DSP48E1 | 633 | 179 | 212 |
| WNS（ns） | +0.000 | +0.182 | +0.078 |
| WHS（ns） | +0.054 | +0.038 | +0.057 |
| 板上中位数（ms） | 58.05 | 75.62 | 65.49 |
| WAV 到结果中位数（ms） | 62.08 | 80.26 | 69.74 |
| WAV 到结果 P95（ms） | 63.78 | 82.09 | 78.99 |
| WAV 到结果最大值（ms） | 64.78 | 82.80 | 83.06 |

桌面口径为已初始化模型、每条输入新建 TCP 连接，从读取 WAV 到收到板卡识别结果。固定 120 个验证条目由 110 个 WAV 和 10 个静音条目组成，每条均重新计算特征。单路有 0 条超过 100 ms，双路有 0 条超过。另以 12 个 WAV 重复 10 轮、同一连接连续推理，吞吐分别为 12.66 和 14.50 次/秒。麦克风采集窗口另计。

两版的 12 条冻结输入均完成 12 层，全量核对各 6,336 个输出，合计每版 76,032 个整数逐位一致。120 条板上预测与软件定点参考逐条一致，两版均有 119/120 条与真实标签相符。两版通过坏 CRC 后重连及连续推理。最终留板版本另用连续音频流验证，物理串口收到 yes、no、stop、go、yes 五个事件。[串口记录](compact-area-evidence/realtime-validation.json)

单路版在原建连流程下，21/120 条超时，最大 103.58 ms。定稿入口在调用线程发起非阻塞 IPv4 握手，再处理 WAV，在发送特征前检查连接成功。每次均重新建连，计时覆盖 SYN 发起、WAV 解码和特征生成、板上推理、分类与收包。单路按同一入口追加 240 次复测，最大 82.41 ms。上表七路参考亦使用改进后的相同主机入口重新上板测试。[原建连流程](compact-area-evidence/lane1/desktop-threaded-before.json) · [240 次复测](compact-area-evidence/lane1/desktop-repeat-240.json) · [工作台入口实测](compact-area-evidence/selected-gui.json)

## 面积从哪里节省

- X、Q、K、V 共用一组按地址分区的单端口 SRAM。64 个 1024×16 宏提供 32 个 32 位数据通道。每区内部上端的空闲地址存放当前投影权重，查询行与投影输入行分时使用同一组寄存器。投影和注意力分时复用 32 个乘法器，保留定点累加、舍入和饱和规则。
- 实例化一套或两套原本科生 FFN1。双路时按输入行奇偶分配。GELU 与 FFN2 使用交替的激活页，计算当前块时可填下一块。每路使用两个行槽按原顺序回传结果，末层仍写回 99×64 个值。E203、512 KiB 共享 SRAM、系统总线、12 层权重逐层装载及上位机协议继续使用原工程实现。

| 加速器内部显式 SRAM | 128×16 | 1024×16 | 4096×16 | 容量 KiB | 宏面积小计（库面积单位） |
| --- | ---: | ---: | ---: | ---: | ---: |
| 用户提供的上一轮 DC | 12 | 108 | 2 | 235 | 1,075,199.88 |
| 七路 FPGA 参考 | 708 | 238 | 0 | 653 | 4,072,699.16 |
| 单路 | 26 | 100 | 2 | 222.5 | 1,039,489.94 |
| 双路 | 40 | 144 | 0 | 298 | 1,424,468.88 |

新配置的宏小计由展开后的宏实例数乘用户给出的单宏面积得到。七路参考还含 RTL 数组形式的行输入及结果存储，显式宏表只统计其宏边界。上一轮 DC 的新增部分含逻辑共 1,250,784.46 个库面积单位，整机为 3,489,017.90。赛题 2.25 mm² 预算计新增接口、计算逻辑及内部 SRAM，固定平台单列。本次按要求仅使用 Vivado，实现资源和表中宏小计不能给出新版标准单元总面积或 ASIC 150 MHz 签核。[赛题指南的面积统计范围](../芯片设计赛题指南.pdf)

## 复现与记录

RTL 版本为 `f21921d`，上位机和硬件导出脚本版本为 `7483539`。完整 RTL 回归用 `python scripts/run_encoder.py soc --contest --compact 1 --input-stream 1 --tasks 12 --jobs 3`。准备以太网 PS 配置后，以 `python integration/z100/run_ross.py contest --ethernet --compact 1 --mhz 55 --build <build>` 重建硬件。双路将两条命令中的 `--compact 1` 改为 `--compact 2`。两版复用相同的 ARM 监测固件、E203 固件与参数包。桌面性能入口为 `integration/z100/benchmark.py --port 192.168.1.11:5001 --all-validation --new-connection --max-end-to-end-ms 100 --output desktop.json`。

[七路实板对照](compact-area-evidence/seven-lane-desktop.json) · [单路时序](compact-area-evidence/lane1/contest-55-timing.rpt) · [双路时序](compact-area-evidence/lane2/contest-55-timing.rpt) · [单路逐条计时](compact-area-evidence/lane1/board-desktop.json) · [双路逐条计时](compact-area-evidence/lane2/board-desktop.json) · [资源及宏数量汇总](compact-area-evidence/summary.json)
