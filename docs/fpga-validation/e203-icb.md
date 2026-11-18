# E203 ICB 地址分发器版本的 Z100 验证

2026-11-18 在 `xc7z035ffg900-2` 上验证。以 `fpga@8a5dcac` 为基线，采用 `codex/e203-icb-bus@2fbf799` 的完整 `integration/kwt_bus_fabric.sv`。CPU、Host 与 DMA 经 KWT 仲裁后，送入固定 HBirdv2 版本的 `sirv_icb1to8_bus`，由其分发至 32 位共享 SRAM、控制寄存器和错误响应端点。此接法使用上游分发器，仍保留项目自己的主设备仲裁、共享 SRAM 控制和 E203 CPU 顶层，正式平台集成按组委会要求另行核验。

Vivado 2026.1 综合入口为 `z100_wrapper`。板卡加载器通过原 Host 口逐层装入权重。512 KiB 共享 SRAM、12 层 KWT 的注意力和 FFN 配置、模型参数和板级协议沿用对照版。用于实测的 ARM ELF 和 E203 固件均与对照版逐字节一致。

## 实板结果

| 测量 | 新总线 40 MHz | 原版 40 MHz |
| --- | ---: | ---: |
| 12 条冻结输入整张输出逐位一致 | 76,032 / 76,032 | 76,032 / 76,032 |
| 固定 120 条 WAV 与软件参考预测一致 | 120/120 | 120/120 |
| 与真实标签一致 | 119/120 | 119/120 |
| 板上平均周期 | 5,845,235.70 | 5,830,108.37 |
| 板上平均时延 | 146.13 ms | 145.75 ms |
| 等效 150 MHz 板上吞吐 | 25.66 task/s | 25.73 task/s |
| WAV 到结果中位数 / P95 | 149.86 / 155.53 ms | 150.31 / 154.90 ms |
| WAV 到结果连续吞吐 | 6.65 task/s | 6.62 task/s |

连续测试使用同一 TCP 连接，12 条固定 WAV × 10 轮。120 次均在 750 万板上周期以内。板上计时包含输入及逐层装载、E203 调度和写回，沿用原固件扣除 TCP 进度回调的口径。等效频率仅用于周期比较。两轮实验的主机预处理和 TCP 耗时有波动。

JTAG 验证 PL 寄存器与共享 SRAM 首尾地址。坏 CRC 后重连，连续两次回读完整输出并按顺序收到各 12 条进度帧。RTL 回归同样逐位通过 12 条冻结输入，仿真加载条件下每条 6,353,387 周期。专项总线测试覆盖连续请求、仲裁公平性、响应背压、授权保持、地址保护与复位。

## 实现结果

| 指标 | 路由后结果 |
| --- | ---: |
| WNS / WHS | +0.452 / +0.049 ns |
| TNS / THS | 0 / 0 ns |
| 未约束内部端点 / 布线错误网络 | 0 / 0 |
| Slice LUT / 寄存器 | 63,642 / 26,808 |
| BRAM Tile / DSP48E1 | 183 / 419 |

[冻结向量实板记录](e203-icb-evidence/board-frozen.json) · [固定验证集](e203-icb-evidence/board-validation.json) · [120 次性能原始记录](e203-icb-evidence/board-throughput.json) · [时序](e203-icb-evidence/timing.rpt) · [资源](e203-icb-evidence/utilization.rpt) · [产物校验值](e203-icb-evidence/SHA256SUMS.txt)

## 复现

依赖、构建和测试入口见[原版板卡说明](contest-20-task.md)。Vivado 工程需要随清单加载锁定版本 E203 的 `rtl/e203/fab/sirv_icb1to8_bus.v`。本次 Ross 创建工程后，首轮单进程综合异常退出；最终位流由同一工程的 `synth_1` 和 `impl_1` 独立运行完成。复测使用 `verify_board.py` 的冻结与 `--validation` 两个模式，`benchmark.py --passes 10`，端口均为 `192.168.1.11:5001`。
