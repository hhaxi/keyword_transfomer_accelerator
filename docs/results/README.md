# 设计报告结果

本页采用 `report@26f715d` 的第 5、6、10、11、13 章口径。下表中的两类 ASIC 结果采用 150 MHz 约束和 RTL-SAIF 功耗估算，FPGA 结果来自 Z100 布线和 55.56 MHz 实板运行。[设计报告 PDF](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/26f715dc25a873ccb3f865f132093745b9ce3939/report/kwt-design-report.pdf)

## ASIC 综合与任务计量

| 指标 | 基础 FFN1 · Q128 `reference_sleep` | 拓展编码器 · 紧凑单路 |
| --- | ---: | ---: |
| 任务定义 | 一组层参数的 FFN1 | 一条输入的完整 12 层编码 |
| 周期 | 12 组连续任务平均 32,006.83 拍 | 4,206,337 拍 |
| 150 MHz 折算吞吐 | 4,686.50 任务/秒 | 35.660 任务/秒 |
| 新增综合单元面积 | 0.505555 mm² | 1.489217 mm² |
| 整机综合单元面积 | 2.738203 mm² | 3.727416 mm² |
| Setup WNS / SS Hold WNS | 0.00 ns / −0.17 ns | 0.00 ns / −0.17 ns |
| 整机功耗窗口 | 第 4 层，30,540.5 拍 | 一条输入从 Host 开始写入到观察到完成 |
| RTL-SAIF 整机功耗 | 37.346 mW | 100.643 mW |
| 整机任务能量 | 7.6038 µJ | 2.822 mJ |

新增面积由加速器、接口、DMA 和内部 SRAM 构成。紧凑单路版内部 SRAM 为 128 个宏、222.5 KiB，另有 512 KiB 系统共享 SRAM 和 E203 TCM。紧凑版功耗窗口覆盖逐层参数装载、计算与最终 DMA 写回，随后通过 Host 回读比对 6,336 个结果。两个配置均有 SS 保持时间违例。综合报告的互连面积未定义，能量由该窗口的整机估算功耗乘以 150 MHz 折算任务时长得到。

- 基础 FFN1 的第 4 层数据来自 2026-11-13 的[服务器综合与功耗摘要](../evidence/report/ffn1-layer04-ppa.txt)。源工程见 [Q128 reference_sleep](../../undergrad_ffn1/candidates/q128_reference_sleep/README.md)，12 组层任务的周期见[本地回归](../../undergrad_ffn1/candidates/q128_reference_sleep/LOCAL_RESULTS.md)。
- 同一 `task00` 的轮询／IRQ/WFI 对照中，整机动态功耗从 33.877 降到 31.908 mW，能量从 8.3561 降到 7.9802 µJ，单任务能量降低 **4.50%**。[同条件对照](../../undergrad_ffn1/candidates/q128_reference_sleep/reports/RESULTS.md)
- 紧凑单路 RTL 取自 [`fpga@d9b7a03`](https://github.com/hhaxi/keyword_transfomer_accelerator/tree/d9b7a03f08f8aa6ecf319d66eabc7e8e52940e1c)。2026-11-19 的综合包另含 E203 ICB LINK-3 位宽适配，使用 `KWT_COMPACT=1`、`PROJECTION_K4=1`、`WIDE_MACRO=1`。[综合、宏清单和功耗摘要](../evidence/report/encoder-compact1-ppa.txt)

## FPGA 实测

报告第 11 章采用 Z100 XC7Z035-2FFG900 的 **55.56 MHz 紧凑单路版**。板上时延覆盖输入装载、逐层参数装载、十二层计算及末层写回。端到端计时还覆盖上位机预处理、TCP 和 Cortex-A9 分类。

| 测试 | 结果 | 数据 |
| --- | --- | --- |
| 逐条新建 TCP，110 条 WAV 和 10 条静音记录 | 平均 **4,200,869.7 拍**，板上中位数 **75.62 ms**。端到端中位数／P95／最大值 **80.26／82.09／82.80 ms**，0/120 超过 100 ms | [逐请求时延](../evidence/report/z100-compact1-board-desktop.json) |
| 复用单 TCP 连接，12 条 WAV × 10 轮 | **12.66 条输入/秒**，120 次请求共 9.482 s | [连续吞吐](../evidence/report/z100-compact1-board-throughput.json) |
| Vivado 2026.1 布线后 PL 实现 | **33,126** 个 Slice LUT，17,584 个寄存器、215 个 BRAM Tile、179 个 DSP48E1。Setup WNS／Hold WHS／脉宽 WPWS 为 +0.182／+0.038／+8.232 ns | [报告上板摘要](../evidence/report/fpga-compact1-summary.md) |

150 MHz 等效吞吐为 35.707 任务/秒，按新建连接测试的板上平均周期折算。

12 条冻结输入共核对 76,032 个编码器输出，全部与定点参考逐位一致。另有 120 条分类记录与定点软件预测逐条一致，119 条命中真实标签。板测 RTL 为 `f21921d`，上位机与硬件导出脚本为 `7483539`。[板卡构建与验证](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03f08f8aa6ecf319d66eabc7e8e52940e1c/docs/fpga-validation/compact-area.md) · [冻结向量](../evidence/report/z100-compact1-board-frozen.json) · [分类记录](../evidence/report/z100-compact1-board-validation.json)

## 报告插图

以下 PNG 由同一报告提交中的 PDF 渲染生成。图 9.1 展示首层输入、中间层 LN2 驻留与末层写回。

| 报告图号 | 插图 | 定稿图源 |
| --- | --- | --- |
| 图 1.1 | [KWT-1 语音指令识别流程](../figures/report/kwt1-recognition-flow.png) | [PDF](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/26f715dc25a873ccb3f865f132093745b9ce3939/report/figures/integrated/1-1.pdf) |
| 图 2.1 | [E203 与 FFN1 加速器](../figures/report/ffn1-soc.png) | [PDF](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/26f715dc25a873ccb3f865f132093745b9ce3939/report/figures/integrated/ffn1-system-palette.pdf) |
| 图 7.1 | [拓展 SoC 总体架构](../figures/report/encoder-soc.png) | [PDF](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/26f715dc25a873ccb3f865f132093745b9ce3939/report/figures/7-1.pdf) |
| 图 9.1 | [十二层编码器的特征与参数流](../figures/report/encoder-layer-schedule.png) | [PDF](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/26f715dc25a873ccb3f865f132093745b9ce3939/report/figures/9-1.pdf) |
