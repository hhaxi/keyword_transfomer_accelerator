# 本科 FFN1 候选方案

| 方案 | 复现入口 |
| --- | --- |
| Q128 IRQ/WFI | [实测 PPA 与服务器复现](q128_reference_sleep/README.md) |
| 时钟门控 | [Q64 周期等价门控与后端交付](clock_gating/README.md) |
| Q64 面积与功耗 | [输出队列、累加位宽和格式化器对照](q64_area_power/README.md) |
| 前端候选 | [Q32/Q64 调度、等待与流水线对照](frontend_candidates/README.md) |
| 首轮四个候选 | [16/32 路 MAC、VCS 功耗及快速筛选](finalists/README.md) |

从各自目录执行其中的命令。前端候选以 `finalists/` 的冻结方案为输入，Q64 面积与功耗方案使用前端交付包，时钟门控方案使用 Q64 交付包。准备脚本会检查所需包的哈希。

[本科 FFN1 主工程](../README.md) 提供 16 路 MAC 和四项优化的 16 组合复现。
