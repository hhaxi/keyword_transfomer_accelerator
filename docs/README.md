# 文档索引

[项目首页](../README.md) · [主分支复现](reproduce.md) · [赛题指南](芯片设计赛题指南.pdf)

| 目录 | 内容 |
| --- | --- |
| [`results/`](results/README.md) | 设计报告口径、配置来源、指标边界和插图出处 |
| `design/` | 主分支基线的数值契约、接口和存储布局 |
| `validation/` | 基线验收记录、冻结定点模型的扩展数值评估 |
| `studies/` | 各轮调度、搬运与总线性能对照 |
| `evidence/` | 机器可读验证记录、性能对照、样本清单和冻结基线 |
| `evidence/report/` | 随报告结果归档的 ASIC 服务器摘要与 Z100 紧凑单路实测记录 |
| `figures/report/` | 从报告定稿导出的框架图，来源见[报告插图索引](results/README.md#报告插图) |
| `history/` | 早期性能报告与基线快照 |

## 接口与验证

- [完整编码器](design/full-encoder.md) · 执行顺序、数值契约、寄存器与内存布局。
- [完整 FFN](design/full-ffn.md) · 双线性层与 GELU。
- [第一线性层与基础架构](design/architecture.md) · 早期接口与数据转换。
- [基线验收记录](validation/acceptance.md) · 记录所述版本对应的验证范围。
- [扩展数值验证](validation/encoder-validation-expanded.md) · 4,445 条验证记录的逐层误差与分类一致性。
- [本科 FFN1 独立工程](../undergrad_ffn1/README.md) · 初始基线、组合对照和后续候选。

## 性能研究

| 对象 | 文档 |
| --- | --- |
| 完整编码器 | [输入直传](studies/input-stream.md) · [主机装载](studies/host-study.md) · [总线仲裁归因](studies/bus-study.md) · [QKV 周期](studies/qkv-study.md) |
| FIFO 与传输 | [FIFO 供需和尾段](studies/fifo-study.md) · [输出 FIFO、16 路线性层及紧凑打包](studies/frontend-transfer.md) |
| FFN 与第一线性层 | [FFN 组间调度](studies/ffn-group-scheduling.md) · [第一线性层紧凑打包](studies/parallel-packed-performance.md) |
| 早期迭代 | [跨层驻留对照](history/encoder-performance.md) · [前端传输](history/frontend-performance.md) · [DMA](history/dma-performance.md) · [完整 FFN](history/full-ffn-performance.md) · [FFN 重叠调度](history/ffn-overlap-performance.md) |

验证脚本按原文件名写入 `evidence/`，可从各研究文档追溯到提交、输入指纹和日志校验值。[本地运行与归档位置](reproduce.md)
