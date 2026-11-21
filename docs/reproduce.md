# 复现入口

| 目标 | 环境和命令 |
| --- | --- |
| 基础 Q128 FFN1 | [FFN1 工程](../projects/ffn1/README.md)提供 12 组层参数的本地回归和 DC/VCS 入口 |
| 紧凑单路编码器 | [编码器工程](../projects/encoder/README.md)提供模型向量和 12 层 E203 SoC 回归 |
| Z100 55.56 MHz | [Z100 工程](../projects/encoder/integration/z100/README.md)提供硬件、固件和上板复测 |
| 扩展软件精度 | [扩展验证](validation/encoder-validation-expanded.md)提供 4,445 条冻结记录的评估流程 |
| 早期基线和候选 | [归档索引](archive.md)提供标签和各版原入口 |

综合、软件分类与 FPGA 实测各自使用[报告结果页](results/README.md)所列的任务口径。紧凑单路 ASIC 定稿综合包的来源和当前记录也在该页。
