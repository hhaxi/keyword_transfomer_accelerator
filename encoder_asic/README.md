# 十二层编码器 ASIC/DC 工程

本目录从 FPGA 验证分支 `4c219d8` 提取加速器计算部分，作为**独立 ASIC 综合对象**。不包含 Cortex-A9、PS、AXI DDR 桥、以太网、Vivado Block Design、XDC 或 FPGA 原语。无需先构建 Z100 工程。

## 固定计算配置

| 模块 | 本工程配置 |
| --- | --- |
| 注意力/投影/残差/归一化引擎 | `PROJECTION_K4=2`：每组 4 个输出、归约并行度 16；`ATTENTION_K16=2`：32 路注意力与流水化分数、Softmax/LayerNorm 路径 |
| 完整 FFN | 7 路行调度：6 路各处理 16 行，第 7 路处理 3 行；每路复用原 FFN1、GELU、FFN2 算术 |
| 模块交接 | LN1 直送 FFN，FFN INT40 结果直送尾段；开启预加载许可，GELU 保持两拍 |
| 层间数据 | ENC1 内部保留 LN2 输出，末层写回外部共享存储 |
| 数值 | 保留源 RTL 的定点格式、移位、RNE 与饱和规则，不重新标定 |
| 目标频率 | 150 MHz，DC 约束周期 6.666667 ns |

注意：这里复用的 FFN1 行核是上板分支的 `undergrad_ffn1/rtl/kwt_ffn1_core.sv`，并非报告基础篇的 Q128 定版核。不能将基础篇面积/能耗，或 FPGA 的 46.2 ms/48.7 次每秒，直接当成本工程综合结果。

## 顶层与系统边界

综合顶层 `kwt_encoder_dc_top` 包括两个计算引擎、7 路 FFN 控制、直传链路、MMIO 译码及 DMA 仲裁。外部接口均为同一时钟域的 valid/ready 请求与响应：

- `c_*`：配置接口。FFN 基址 `0x40000000`，编码器基址 `0x40010000`。每次只允许一笔配置响应在途，响应背压时保持数据。
- `m_*`：32 位外部共享存储接口。地址沿用 `0xA0010000` 起的特征和参数布局，提供单端口从设备即可。不能接入原 Z100 的 `0x43C...` MMIO 地址。
- E203、512 KiB 系统共享 SRAM 与系统总线不在本加速器顶层内。整机 DC 面积和功耗需在实际 E203 平台接入此模块后单列，不将此加速器面积写作 SoC 总面积。
- `firmware/encoder_driver.c` 提供 CPU 无关的十二层命令/参数装载流程，可接入 E203。输入 6,336 个 Q16 元素，每层参数 33,410 字，十二层后读取 6,336 个输出；无 ARM、网络或分类头依赖。

## 存储移植

宽投影权重、FFN 输入与结果缓冲已经改为 `kwt_sram16` 边界，读延迟仍为同步一拍。`sim/kwt_sram16.sv` 是行为模型，`dc/kwt_sram16.sv` 是实际宏适配器，**两者不能同时编译**。

ASIC 适配使用已有 RAMSP128X16、RAMSP1024X16、RAMSP4096X16 单端口宏及其 CEN/GWEN/WEN/EMA/EMAW/RET1N 端口。逻辑深度向上补齐至 128/1024/4096 字，计入完整物理宏面积。EMA=0、EMAW=0 沿用现有工程配置，换库时按宏手册设置。宽版分数缓存为 128×32 的同步读写寄存器阵列，保留其独立读写语义，不假定工艺提供双端口 SRAM。较小流水和偏置寄存器由 DC 映射标准单元。

`provenance.json` 记录源提交、源文件和提取文件哈希；改写集中在存储边界与顶层集成，来源 RTL 仍保留在原目录，便于逐项对照。

## 运行

```powershell
# 不需要 Vivado；Python 仅用于源清单检查，可选安装 pyslang 做语法/展开检查。
python encoder_asic/scripts/check.py
python encoder_asic/tests/test_dc_flow.py
# ModelSim/Questa：含配置接口背压、错误译码及物理 SRAM 补齐检查。
python encoder_asic/scripts/check.py --simulate --modelsim-bin /path/to/modelsim/bin
```

在 Linux DC 服务器配置工艺库后运行：

```sh
cp encoder_asic/config/library.example.tcl encoder_asic/config/local.tcl
# 编辑 std_db、sram_dbs：必须对应实际库文件，库本身不入仓库。
dc_shell -f encoder_asic/dc/run.tcl | tee encoder-dc.log
```

输出位于 `encoder_asic/output/dc/`：网表、DDC、SDC、SDF，以及层级面积、setup/hold、约束违例、时钟门控和实例引用报告。DC 不放行 link/check_design 失败。只有配置真实 SAIF 和实例路径时才输出功耗报告，避免无活动数据时生成可被误用的功耗数字。

## 报告衔接

第七章以本工程的投影/注意力/7 路 FFN 描述计算结构；第八章描述直传及流水处理；第九章使用 CPU 无关驱动说明十二层参数调度；第十章使用本配置重新运行后的整数结果、完整任务周期与存储统计。第十一章仍只承担 FPGA 功能验证。

本工程计时应从首个输入/参数装载请求开始，到末层输出全部写回结束；由平台侧计数包含参数装载、总线等待与 E203 调度。分类头与上位机预处理在任务外。目标频率不等于时序收敛，源 FPGA 的测试记录不替代 ASIC 存储改写后的完整功能回归。

本次实际执行范围见 [VALIDATION.md](VALIDATION.md)。
