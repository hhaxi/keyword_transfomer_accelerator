# 设计来源

- `projects/encoder/rtl/kwt_*`、`projects/encoder/integration/kwt_*`、`projects/encoder/firmware/`、数值模型、转换脚本及测试平台为本项目新增实现。
- E203 CPU 来自 Nuclei 的 [e203_hbirdv2](https://github.com/riscv-mcu/e203_hbirdv2)，固定提交见 `projects/encoder/assets/resources.lock.json`。使用原始源码，不复制或删除上游版权声明。该项目采用 Apache-2.0；具体文件以原始声明为准。
- KWT-1 模型及预训练权重来自 ARM 的 [keyword-transformer](https://github.com/ARM-software/keyword-transformer)，固定提交 `237e4097afd4f6851e0b82f0a8d65c2dfe8eae30`。提取器调用其原始音频处理、网络和 checkpoint，没有训练、微调或蒸馏。上游许可文件随下载源码保留。
- Speech Commands V2 来自指南规定的公开数据源，许可和出处保留在本地数据集目录及资源清单中。
- `projects/encoder/integration/e203_ram_boundary.v` 是匹配上游 RAM 端口的综合边界声明，不包含 SRAM 工艺实现；正式宏由组委会提供后替换。
- Q128 工程保留原封包及其中的第三方源文件声明。编码器的 FFN 行核来自 `fpga@d9b7a03` 的独立 16 路行实现，源文件在 `projects/encoder/rtl/ffn1_row/`。
- 自检用数值参考和预期输出只由仿真比较器读取，不参与加速器计算。公开 IP 不列为自主创新成果。

尚未取得官方 PDK、标准单元库、SRAM 工艺模型及最终平台工程。通用综合结果与正式工艺评测必须分别记录。
