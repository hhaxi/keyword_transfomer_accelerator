# 提取工程检查记录

源分支：`codex/fpga-functional-validation`，源提交 `4c219d8e2e7665b57e5bb6ccf3283e9e8df9c685`。

| 检查 | 本次结果 |
| --- | --- |
| 独立 source list 与提取文件哈希 | 通过 |
| FPGA 原语、Z100 模块和 ram_style/use_dsp 属性依赖扫描 | 无匹配 |
| pyslang 12.1.0：通用顶层解析与展开 | 通过 |
| pyslang：MMIO 测试平台、物理宏适配顶层及深度 6–12 的存储测试平台 | 通过 |
| ModelSim 10.5b：行为模型、顶层及 MMIO 测试平台编译 | 通过 |
| DC Tcl 控制流测试（模拟 EDA 命令） | 通过；检查工艺配置缺失报错、13 文件清单、150 MHz 时钟及门控编译参数 |
| ModelSim 动态仿真 | 未执行；vsim 无可用许可证 |
| 十二层真实向量回归 | 未执行；必须对本目录的 SRAM 改写和新顶层重新运行 |
| DC 实际工艺映射、面积、时序与活动功耗 | 未执行；需要 Linux DC 及实际工艺库 |

Tcl 控制流测试不执行 DC，不能作为综合成功的证明。原 FPGA 数值回归是来源说明，不是本 ASIC 改写版本的验证结果。

本次没有修改 report 分支，也没有将 FPGA 的板上时延或频率缩放结果作为 ASIC 性能结果。
