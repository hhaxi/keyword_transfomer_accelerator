# KWT-1 关键词识别加速器

面向本科生组芯片设计赛题，基于 **E203 蜂鸟 SoC** 实现第一线性层、完整 FFN 和 **12 层 PostNorm Transformer 编码器**。工程包含可综合 RTL、冻结整数模型、参数转换、RISC-V 固件、SoC 集成及自动化验证。

**当前版本：编码器第二版 + FFN 第八版。** 完整编码器实测 **14,808,628 周期/次**，相对编码器第一版减少 **4.68%**；两种独立 FFN 模式性能保持不变。当前已完成本地 RTL、四态仿真和通用网表验证，正式工艺时序、面积、功耗及官方平台评测待官方环境提供后完成。

[设计与接口](docs/full-encoder.md) · [最新性能](docs/encoder-performance.md) · [验证记录](docs/encoder-validation.json) · [赛题指南](芯片设计赛题指南.pdf) · [第三方来源](NOTICE.md)

## 1. 实现范围

| 工作模式 | 计算内容 | 当前状态 |
| --- | --- | --- |
| 第一线性层独立模式 | `X[99,64] × W[64,256] + b[256]` | 保留本科必做功能，支持 12 层参数切换 |
| 完整 FFN 独立模式 | 第一线性层 → GELU → 第二线性层，维度 `64 → 256 → 64` | 保留第八版实现与性能 |
| 完整编码器 | 注意力 → 残差/LN1 → 完整 FFN → 残差/LN2，连续执行 12 层 | 已实现第 4—7 项拓展涉及的编码器功能及本地验证流程 |

固定模型配置为 **99 token、64 维特征、单头注意力、256 维 FFN 隐层、12 层编码器**。它不是可动态配置任意尺寸的通用 Transformer 加速器。

```text
软件：音频前处理 / MFCC / 嵌入
                 │
                 ▼ X [99,64]
       ┌─────────────────────────────────────────────┐
       │ Q/K/V → QKᵀ / 8 → 行 Softmax → PV → Wo + bo │
       │                  ↓                          │
       │            残差相加 → LN1                   │
       │                  ↓                          │
       │     FFN1 [64,256] → GELU → FFN2 [256,64]    │
       │                  ↓                          │
       │            残差相加 → LN2                   │
       └─────────────────────────────────────────────┘
                 │ 重复 12 层，跨层复用驻留结果
                 ▼
软件：class token 分类头
```

注意力、两次残差、两次 LayerNorm 和 FFN 算子均由硬件计算。E203 固件负责配置地址、启动、等待完成及读取状态；音频前处理、嵌入和最后分类头属于软件参考边界。当前已集成真实 E203 CPU 和共享总线，不只是孤立的计算核。

## 2. 最新性能与优化

以下为相同输入、参数、固件及计时边界下的整机仿真周期：

| 工作负载 | 优化前 | 当前 | 变化 |
| --- | ---: | ---: | --- |
| 完整 12 层编码器 | 15,535,024 | **14,808,628** | 周期减少 **4.68%**，同频吞吐提升 **4.91%** |
| 第一线性层独立任务 | 271,678 | **271,678** | 无回退 |
| 完整 FFN 独立任务 | 306,709 | **306,709** | 无回退 |

编码器计时包含初始输入加载、12 次参数加载、CPU 调度与统计、硬件计算、最终写回确认及通知观察；不含固件初次装载和计时后的输出比较。三个工作负载的计算量不同，不能直接用其周期比作为相互加速比。

按目标 **150 MHz** 折算，完整编码器为 **98.724 ms/次、10.129 次/秒**；该折算不代表已完成正式工艺的频率验证。

本轮优化包括：

- **矩阵组间预读与初始化重叠**：QKV、QK、PV、输出投影在保存当前结果时准备下一组，累计节省 **420,456 周期**；主矩阵段有效乘法周期占比由 **92.93% 提升至 97.33%**。
- **连续 DMA**：分离请求和响应游标，支持两笔顺序在途事务；输入/参数整段读取、输出整段写回。理想总线测试中连续读写各 6,336 字，达到 **每拍一个 32 位字**。FFN 结果以每组 8 字连续读取，组间保留残差 SRAM 读写拍。
- **细分周期计数**：覆盖 QKV、QK、Softmax、PV、输出投影/残差1、LN1、LN2、输入/参数 DMA、FFN 结果 DMA/残差2和输出 DMA；另有请求背压、响应等待及同拍收发计数。
- **数值与兼容性保持**：整数格式、舍入位置、乘法器数量、DMA 字数和内部 SRAM 访问量不变；原 FFN RTL 与固件保留。

十项阶段计数互斥，求和等于编码器命令总周期。DMA 等待诊断已经包含在对应阶段中，不能再累加至总周期。完整数据及计时口径见 [性能报告](docs/encoder-performance.md)。

## 3. 硬件组织与接口

| 模块 | 主要文件 | 职责 |
| --- | --- | --- |
| 编码器伴随引擎 | `rtl/kwt_encoder.sv` | 注意力、残差、LayerNorm、编码器 DMA 和周期计数 |
| FFN 引擎 | `rtl/kwt_accel.sv`、`rtl/kwt_dma.sv` | 两种独立模式、矩阵计算、GELU、输入/权重加载与结果写回 |
| 数学与存储模块 | `rtl/kwt_exp_negative.sv`、`kwt_udiv64.sv`、`kwt_isqrt64.sv`、`kwt_vecmem32.sv` | 指数近似、整数除法/平方根及同步 SRAM 接口 |
| 扩展总线 | `integration/kwt_extended_system_bus.sv`、`kwt_dma_arbiter.sv` | CPU、主机与共享 SRAM 连接，两个 DMA 的公平仲裁 |
| 完整 SoC 顶层 | `integration/kwt_encoder_soc.sv` | E203 CPU 与两个硬件引擎集成 |
| RISC-V 驱动 | `firmware/kwt_encoder_driver.c`、`kwt_driver.c` | 按模型顺序启动编码器与 FFN |

资源配置保持 **16 路 FFN MAC、1 个 GELU、4 路编码器共享 32 位乘法通路**；指数插值等另有辅助算术，不能将这些主通路数当作整个 SoC 的全部乘法器数。

完整加速器内部 SRAM 为 **235 KiB / 240,640 B / 122 个 16 位宏**，其中原 FFN 占 88.5 KiB。System Bus 的 **512 KiB 共享 SRAM** 与 E203 自有存储边界单独统计。Q/K/V/O 复用一组投影权重缓存，分数/概率复用单行缓存，LN2 结果可驻留供下一层使用。

| 寄存器窗口 | 标识 | 操作 |
| --- | --- | --- |
| `0x40000000` | `KWT5` | 模式寄存器 `0x38`：0=第一线性层，1=完整 FFN |
| `0x40080000` | `ENC1` | 操作寄存器 `0x38`：0=注意力至 LN1 并写出 FFN 输入，1=读取 FFN 结果并完成残差/LN2 |

ENC1 的新增计数位于偏移 `0x60—0x90`。地址布局、状态位、中止/错误排空、驻留控制及数值格式详见 [编码器接口文档](docs/full-encoder.md)；FFN 协议见 [基础架构](docs/architecture.md)。

## 4. 验证结果与适用边界

| 验证项目 | 已完成的本地结果 |
| --- | --- |
| 编码器 RTL 整机 | **12 条输入 × 12 层**，每条最终 6,336 个整数输出逐位一致 |
| 编码器通用网表整机 | 1 条输入执行全部 12 层，输出、周期及固件采集的性能计数与 RTL 一致 |
| 两种独立 FFN 模式 | RTL 与网表各执行 12 个任务，结果正确、周期无回退 |
| 中间矩阵 | 12 层 Q/K/V、分数、概率、PV、输出投影和残差/LN 逐位核对 |
| 数学与边界 | 除法 1,029 例、平方根 1,031 例、指数近似 34,855 例；覆盖常量输入、零方差等边界 |
| 总线与异常 | 覆盖背压、连续收发、两笔在途中止排空、错误后受阻请求保持、读写错误、复位及重启 |
| 软件数值参考 | 120 条本地验证样本中，浮点与整数模型均正确 **119/120**，预测一致 **120/120**；最大逐层聚合 NRMSE **0.171713%** |

软件数值验证的 120 条样本与 RTL 整机的 12 条输入是不同验证范围。模型与整数格式保持冻结，不使用测试集调节尺度。

机器可读证据、源文件和日志校验值见 [encoder-validation.json](docs/encoder-validation.json)。通用网表仿真不含工艺延时；正式 **150 MHz、≤2.25 mm²、功耗、能耗及官方 600 条样本评测**仍待完成。

## 5. 首次配置

当前复现脚本面向 **Windows x64 + PowerShell + WSL Ubuntu**。先安装 Git、uv，并准备以下工具：

| 工具 | 用途 / 配置方式 |
| --- | --- |
| Verilator（WSL）、Icarus Verilog（Windows） | RTL/网表仿真、四态检查及 lint；按配置模板填写对应路径 |
| Yosys | WSL 中的通用综合与结构检查 |
| ModelSim、OpenSTA | 当前完整环境自检会调用；ModelSim 需要可用许可证，OpenSTA 自检仅检查工具启动 |
| Python 模型环境、Nuclei GCC、GNU Make | 由 `setup.ps1` 安装到项目内；GCC 用于 RV32 固件编译 |
| GTKWave | 可选，用于查看波形 |

`setup.ps1` 不负责安装 WSL、外部 EDA 软件或商业许可证。模型运行使用 CPU，无需 CUDA。

```powershell
git clone https://github.com/hhaxi/keyword_transfomer_accelerator.git
cd keyword_transfomer_accelerator

# 仅在首次配置时复制；已有配置应直接编辑。
Copy-Item environment/local-tools.example.json environment/local-tools.json
notepad environment/local-tools.json

# 下载固定版本的模型、权重、Speech Commands V2、E203 和 SDK。
uv run --no-project --python 3.13 scripts/download_competition_assets.py

# 创建模型环境、安装项目私有工具链并执行环境自检。
.\setup.ps1
```

模型环境使用 **Python 3.8.20、TensorFlow 2.4.0、NumPy 1.19.5**；下载辅助脚本使用独立的 Python 3.13。上游原环境为 TensorFlow 2.4.0rc1，本机采用 2.4.0 开发替代版，与官方浮点运行环境的等价性仍需确认。完整依赖见 [依赖锁文件](environment/requirements-model.lock.txt)。

资源版本、来源和哈希见 [resources.lock.json](assets/resources.lock.json)。模型固定使用 `best_weights`，FFN 隐层维度以该 checkpoint 的 `flags.json` 为准。下载和安装期间建议预留至少 20 GB 空间，长时间仿真及波形可能需要更多空间。下载脚本会重新解压所选第三方源码，自研代码应保存在项目的 `rtl/` 等独立目录。

## 6. 运行与复现

所有命令均在仓库根目录执行。首次生成完整验证证据时，按以下顺序运行：

```powershell
. .\env.ps1

# 生成基础模型/FFN 向量，并完成原两种模式的验证。
.\design.ps1 all

# 生成编码器向量，执行功能、兼容性、整机、网表、性能对比及打包。
.\encoder.ps1 all
```

编码器默认样本选择依赖基础流程生成的 `output/vectors/` 和 `output/calibration/` 记录；兼容回归也使用原 FFN 向量。新克隆工程应先完成基础流程。已有完整环境和向量时，可按需执行：

| 命令 | 内容 |
| --- | --- |
| `.\encoder.ps1 component` | 12 层中间矩阵、连续 DMA 和常量输入检查 |
| `.\encoder.ps1 fourstate` | Icarus 四态数学与组件检查 |
| `.\encoder.ps1 faults` | DMA/寄存器异常、中止恢复与仲裁检查 |
| `.\encoder.ps1 lint` | 扩展总线和加速器严格 lint |
| `.\encoder.ps1 compat` | 两种独立 FFN 模式的 RTL 兼容与性能回归 |
| `.\encoder.ps1 soc` | 12 条输入的真实 E203 编码器整机 RTL 回归 |
| `.\encoder.ps1 profile` | 同配置跨层驻留 A/B 及内存访问统计 |
| `.\encoder.ps1 synth` | 生成保留 SRAM 边界的通用网表 |
| `.\encoder.ps1 netlist` | 1 条输入、12 层网表整机回归，需先综合 |
| `.\encoder.ps1 compat-netlist` | 两种独立 FFN 模式的网表回归，需先综合 |
| `.\encoder.ps1 collect` / `package` | 校验证据并生成报告 / 本地交付包 |

整机回归较长，可将 12 条输入分为四个独立仿真进程；并行只缩短宿主机运行时间，不改变硬件周期：

```powershell
.venv-model\Scripts\python.exe scripts/run_encoder.py soc --tasks 12 --jobs 4
```

`tools.ps1 all` 是环境自检入口，报告位于 `output/environment/`；它不能替代 `design.ps1` 和 `encoder.ps1` 的设计验证。前端日常开发可先执行 `component`、`faults`、`lint`、`compat` 和 `soc`，需要完整交付证据时再完成其余步骤。

官方样本清单到位后的编码器导出入口：

```powershell
.venv-model\Scripts\python.exe scripts/export_encoder.py --split testing --sample-list official-samples.json --output output/encoder-official
```

清单为数据集相对音频路径组成的 JSON 数组，静音项为 `"silence"`。此命令生成参考与硬件向量；官方硬件评测还需对接对应平台的加载、运行和读取流程。自定义第一线性层数据转换见 [架构文档](docs/architecture.md)。

## 7. 工程目录与交付

```text
rtl/                        自研计算核、DMA、数学模块及 SRAM 接口
integration/                E203 集成、共享 SRAM、System Bus 与 DMA 仲裁
firmware/                   RISC-V 启动代码、驱动和整机测试程序
model/                      冻结整数格式、参考模型及样本选择
scripts/                    资源获取、模型转换、构建、验证和打包
tests/                     RTL 测试平台、数值检查与性能观察器
constraints/                目标时钟和顶层接口约束
docs/                      架构、性能、验证证据与历史基线
environment/               工具配置模板、依赖锁定及环境自检
assets/resources.lock.json  上游资源版本与校验值
encoder.ps1                 完整编码器验证入口
design.ps1                 第一线性层与完整 FFN 验证入口
setup.ps1 / env.ps1          首次安装 / 当前终端环境
```

本地产物位置：

| 路径 | 内容 |
| --- | --- |
| `output/design/` | 仿真、lint、综合日志及构建目录 |
| `output/encoder-design/` | 编码器固件、通用网表与综合记录 |
| `output/encoder-vectors/`、`output/encoder-calibration/` | 编码器验证/训练检查向量与数值报告 |
| `docs/encoder-performance.md`、`docs/encoder-validation.json` | 最新可读性能报告与机器可读证据 |
| `deliverables/undergraduate-encoder-local-submission.zip` | 完整编码器本地交付包 |
| `deliverables/encoder-submission-sha256.txt` | 交付包 SHA-256 |

`collect` 检查测试完整性、RTL/网表一致性、源文件与向量校验值，以及两种 FFN 模式性能；证据缺失或过期时拒绝生成完整报告。`package` 在此基础上打包源码、参数、向量、日志、固件和通用网表，并校验归档内容。新增工程文件应先纳入 Git 暂存区，打包仅采集已跟踪/已暂存的源码文件。

第三方源码、模型权重、音频、工具、Python 环境、`output/` 与 `deliverables/` 均不随 Git 分发。新机器需要执行下载和复现流程，本机已有交付包不等于远端仓库中保存了这些大文件。

## 8. 保留基线与进一步阅读

| 基线 | 提交 | 说明 |
| --- | --- | --- |
| 第四版本科必做 | `d501f0d` | 保留第一线性层必做基线 |
| 第八版完整 FFN | `3461cf7` | 当前两种独立模式的功能与性能对照 |
| 第一版完整编码器 | `ccc7641` | 15,535,024 周期的编码器优化对照 |
| 第二版完整编码器 | `08b1969` | 本 README 所述调度、连续 DMA 与细分计数实现 |

本机分别保留 `deliverables/undergraduate-v4-baseline.zip`、`full-ffn-v8-baseline.zip` 和 `encoder-v1-baseline.zip` 等历史归档。第五至第七版 FFN 的过程记录仍保留在 Git 历史和对应文档中。

- [完整编码器设计](docs/full-encoder.md)：执行顺序、数值契约、寄存器和内存布局。
- [最新编码器性能](docs/encoder-performance.md)：版本对比、阶段周期及跨层驻留 A/B。
- [第八版 FFN 调度](docs/ffn-group-scheduling.md)：两种独立模式的当前基线。
- [完整 FFN 基础设计](docs/full-ffn.md)：双线性层与 GELU。
- [第四版必做性能](docs/parallel-packed-performance.md)：紧凑打包与必做基线。
- [赛题范围记录](environment/project-context.json)：已确认的本科组范围、参考平台与约束。

## 9. 清理与来源

清理前先预览：

```powershell
.\scripts\clean-project.ps1 -WhatIf
```

确认后去掉 `-WhatIf` 执行。该脚本会删除 **整个 `output/`**、临时文件和下载缓存，包括其中的日志、向量及历史输出备份；请先保存需要保留的验证证据。已安装工具、模型环境、解压的数据集和参考源码会保留。清理后需重新生成输出才能再次汇总或打包。

官方 SoC 参考为 [riscv-mcu/e203_hbirdv2](https://github.com/riscv-mcu/e203_hbirdv2)，模型来自 [ARM-software/keyword-transformer](https://github.com/ARM-software/keyword-transformer)，数据集为 Speech Commands V2。固定提交、下载地址和校验值均记录在资源清单中；上游许可文件随下载内容保留。自研与第三方边界见 [NOTICE.md](NOTICE.md)。
