# 文档索引

本目录按用途分层，避免源码、证据和历史记录混在一起：

| 位置 | 内容 | 维护方式 |
| --- | --- | --- |
| `docs/*.md` | 设计、验收口径与当前各轮性能研究 | 手工维护，入口见 [README](../README.md) |
| `docs/evidence/` | 机器可读证据：逐轮验证记录、性能对照、样本清单、冻结基线引用 | 由 `scripts/collect_*.py`、`scripts/compare_*.py` 生成 |
| `docs/history/` | 被后续版本取代的历史性能报告与基线快照 | 只读归档，不再更新 |
| `docs/figures/` | 文档插图 | `scripts/draw_kwt_architecture.py` 生成架构图 SVG/HTML |
| `docs/芯片设计赛题指南.pdf` | 本科组赛题指南原文 | 只读 |

## 设计与验收

- [完整编码器设计](full-encoder.md)：执行顺序、数值契约、寄存器与内存布局。
- [完整 FFN 设计](full-ffn.md)：双线性层与 GELU。
- [基础架构与第一线性层](architecture.md)：早期接口与数据转换说明。
- [验收口径](acceptance.md)：已复核范围、待完成的正式 PPA/官方样本边界。

## 当前性能研究

- [最新输入直传](input-stream.md)：预装载、分块、单端口仲裁、背压与取消恢复。
- [主机装载优化](host-study.md)：有界主机授权与完整对照。
- [总线归因](bus-study.md)：DMA/主机/CPU 仲裁占用归因。
- [QKV 周期研究](qkv-study.md)：每层 MAC 利用率与调度收益上限。
- [第四版 FIFO 分析](fifo-study.md)：供需判断、尾段分解及单项 RTL 对照。
- [第三版前端性能](frontend-transfer.md)：16 路独立线性层、连续装载与紧凑打包。
- [第八版 FFN 调度](ffn-group-scheduling.md)：两种独立模式的当前基线。
- [第四版必做性能](parallel-packed-performance.md)：紧凑打包与必做基线。
- [扩展数值验证](encoder-validation-expanded.md)：4,445 条 validation 索引的逐层误差。

## 机器可读证据

`docs/evidence/` 中每一轮报告都对应 README 与上述文档中的引用，包括：
`design-validation.json`、`encoder-validation.json`、`encoder-validation-expanded.json`、
`input-stream-validation.json`、`host-study-validation.json`、`bus-study-validation.json`、
`qkv-study-validation.json`、`fifo-study-validation.json`、`frontend-transfer-validation.json`、
`ffn-validation.json`、`numeric-validation.json`、`cycle-analysis.json`、
`performance-comparison.json`、`ffn-performance-comparison.json`、`validation.json`；
以及冻结基线引用 `encoder-baseline-v8.json`、`fifo-study-baseline.json`、
`frontend-transfer-baseline.json` 和扩展样本清单 `encoder-validation-expanded.samples.json`。

这些 JSON 记录了对应提交、文件 SHA-256、逐任务/逐层计数和日志指纹。重新生成需先完成
`design.ps1` / `encoder.ps1` 对应阶段，再运行相应的 `collect_*.py`。

## 历史归档

`docs/history/` 保留被取代版本的材料，只用于追溯旧提交、旧口径，不能与当前版本数据混用：

- 性能报告：[第二版编码器](history/encoder-performance.md)、[第二版前端](history/frontend-performance.md)、
  [第三版 DMA](history/dma-performance.md)、[第六版完整 FFN](history/full-ffn-performance.md)、
  [第七版 FFN 重叠](history/ffn-overlap-performance.md)。
- 基线快照：`history/performance-baseline{,-v2..-v7}.json`、`history/encoder-baseline-v1.json`。

## 插图

- `figures/keyword-transformer-overview.png`：README 使用的 KWT-1 模型结构图。
- `figures/keyword-transformer-architecture.svg` / `.html` / `.png`：本工程模型、编码器与
  AI 加速器 SoC 的整体映射图，由 `scripts/draw_kwt_architecture.py` 生成（SVG/HTML 可直接编辑重生成）。
