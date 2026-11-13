# E203 + 12 层 KWT 的 Design Compiler 入口

本分支基于实板验证的 `fpga` 提交 `8a5dcac`。ASIC 入口为 `kwt_encoder_soc`，固定 `PROJECTION_K4=1`、`WIDE_MACRO=1`、`DMA_BURST=1`、`HOST_BURST=0`，沿用同一份注意力、归一化、FFN 和 E203 调度源码。外部接口为 Host ICB，E203 从 `0xa0000000` 启动。综合源文件由 `encoder.f`、固定版 E203 和既有 `undergrad_ffn1/tech` 宏适配器组成。板卡的 Zynq PS、DDR 加载桥、以太网和上位机在该源清单之外。

## 在 DC 服务器运行

使用 `scripts/download_competition_assets.py` 准备仓库锁定的 E203 源码。将环境变量指向同一工艺角的标准单元和 SRAM `.db`。工程已有后端配置使用 SMIC40 RVT SS 0.99 V、125 °C。`KWT_SRAM_EMA` 和 `KWT_SRAM_EMAW` 取宏文档确认的配置，单位及 I/O 预算以实际库和赛题接口为准。

```bash
export KWT_STD_DB=/path/to/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
export KWT_SRAM_DB_128=/path/to/RAMSP128X16_ss_0p99v_0p99v_125c.db
export KWT_SRAM_DB_1024=/path/to/RAMSP1024X16_ss_0p99v_0p99v_125c.db
export KWT_SRAM_DB_4096=/path/to/RAMSP4096X16_ss_0p99v_0p99v_125c.db
export KWT_SRAM_EMA=0 KWT_SRAM_EMAW=0  # 按所用宏文档确认
mkdir -p output/encoder-dc
set -o pipefail
dc_shell -f integration/asic_dc/run.tcl 2>&1 | tee output/encoder-dc/dc.log
```

`encoder.sdc` 约束 6.666667 ns 周期并给出初始 I/O 预算。脚本检查链接、层次及综合前后宏数量，在 `output/encoder-dc/dc/` 写出 DDC、门级网表、SDC、建立和保持报告、约束违例、库宏面积及分层面积。`KWT_DC_OUTPUT` 可改变输出目录。`area-by-scope.rpt` 的 `added` 为面积预算范围，包含编码器、FFN、接口、DMA、互连和内部 SRAM，E203（含 TCM）与系统共享 SRAM 分列。`sram-mapped.csv` 的宏面积已包含在对应层次面积里。

| 范围 | 128×16 SP | 1024×16 SP | 4096×16 SP | 容量 |
| --- | ---: | ---: | ---: | ---: |
| 加速器内部 SRAM | 654 | 36 | 2 | 251.5 KiB |
| 512 KiB 共享 SRAM | 0 | 0 | 64 | 512 KiB |
| E203 ITCM + DTCM | 0 | 0 | 16 | 128 KiB |

共享 SRAM 保留单端口接口和字节掩码。宏适配层复用工程原有的单端口 `RAMSP` 控制，TCM 保留末次读地址写入旁路。E203 采用 ASIC 时钟门控配置。当前主机未取得完整的目标 `.db` 和可执行 DC 环境，SMIC40 的映射面积、150 MHz STA 和功耗需要在目标服务器上确认。

## 本地复测

```bash
# 先按 FPGA 验收报告生成 output/encoder-vectors 和 E203 firmware。
bash integration/asic_dc/verify_macros.sh 1
```

本地结构检查确认 [772 个 RAMSP 实例](evidence/native-macro-stat.json)。采用 RAMSP 功能模型的完整 12 层冻结用例通过，E203 调度、逐层 FFN 流交接及 6,336 个最终 Q16 整数逐位对照均通过，耗时 6,331,236 周期。[仿真日志](evidence/macro-rtl-smoke.log)[来源 FPGA 验收](../../docs/fpga-validation/contest-20-task.md)
