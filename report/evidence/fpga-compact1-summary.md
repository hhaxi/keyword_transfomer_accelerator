# Z100 紧凑单路版上板结果

上板配置为 FPGA 分支提交 `d9b7a03` 选择的 `compact=1`。RTL 提交为 `f21921d`，上位机及硬件导出脚本提交为 `7483539`。Vivado 2026.1，器件 XC7Z035-2FFG900，`clk_fpga_0` 约束周期 18.000 ns，实际频率约 55.56 MHz。

| 项目 | 单路结果 |
| --- | ---: |
| Slice LUT / 存储类 LUT | 33,126 / 1,026 |
| Slice 寄存器 / BRAM Tile / DSP48E1 | 17,584 / 215 / 179 |
| Setup WNS / Hold WHS / 脉宽 WPWS | +0.182 / +0.038 / +8.232 ns |
| Setup、Hold、脉宽失败端点 | 均为 0 |
| 板上周期均值 / 时延中位数 | 4,200,869.7 拍 / 75.62 ms |
| 新建 TCP 连接端到端中位数 / P95 / 最大值 | 80.26 / 82.09 / 82.80 ms |
| 新建 TCP 连接超过 100 ms | 0/120 |
| 复用 TCP 连接连续吞吐 | 120 次 / 9.4818997 s = 12.66 次/秒 |
| 最终编码输出逐位核对 | 12 × 6,336 = 76,032 个整数一致 |
| 分类预测 | 与定点参考 120/120 一致，真实标签 119/120 命中 |

板上周期均值和新建连接时延来自 110 条音频和 10 条静音测试。连续吞吐另用 12 条 WAV 在同一 TCP 连接上顺序执行 10 轮。论文中的四张上位机截图保存自此前的板卡联调。40 MHz 截图中的时延属于该历史批次。

原始数据见 [紧凑版上板记录](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03/docs/fpga-validation/compact-area.md)、[单路新建连接数据](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03/docs/fpga-validation/compact-area-evidence/lane1/board-desktop.json)、[单路连续吞吐](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03/docs/fpga-validation/compact-area-evidence/lane1/board-throughput.json)、[时序报告](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03/docs/fpga-validation/compact-area-evidence/lane1/contest-55-timing.rpt)和[资源报告](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03/docs/fpga-validation/compact-area-evidence/lane1/contest-55-utilization.rpt)。
