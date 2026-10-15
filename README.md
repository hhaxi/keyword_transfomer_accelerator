# KWT-1 关键词识别加速器（本科生组：必做与完整编码器拓展）

本项目以 KWT-1 模型和 E203 蜂鸟 SoC 为参考，保留本科必做第一线性层和第八版完整 FFN，并增加第 4—7 项完整编码器拓展：注意力 → 残差/LN1 → FFN1/GELU/FFN2 → 残差/LN2，按模型顺序执行 12 层。

**当前阶段：已实现本科组线性加速器 RTL、冻结数值模型、参数转换、E203 驱动与 System Bus 集成，并完成本地功能和通用综合验证。正式工艺时序、面积、功耗及官方平台验收仍待官方服务器和工艺资料，不能将当前结果称为全部赛题验收通过。** `environment/smoke/` 仅用于环境检查，实际设计位于 `rtl/`。

完整编码器新增独立 `ENC1` 伴随引擎和 `kwt_encoder_soc` 顶层；原 KWT5 两种模式继续保留。新流程运行 `.\encoder.ps1 all`，旧 FFN 流程仍运行 `.\design.ps1 all`。新设计说明见 [完整编码器](docs/full-encoder.md)，实测结果见 [编码器性能](docs/encoder-performance.md) 和 [验证记录](docs/encoder-validation.json)。本地 120 条验证样本预测与浮点模型全部一致，两者均正确 119 条；内部 SRAM 增至 235 KiB，正式面积仍需确认。第八版归档保存在本地 `deliverables/full-ffn-v8-baseline.zip` 和 `v8-source-baseline.zip`。

**第八版通过重叠组间读取和 MAC 初始化优化完整 FFN。** 保持 16 个 MAC、1 个 GELU、88.5 KiB 内部 SRAM 和 40 个宏，完整任务由第七版 310,289 降至 **306,709 周期**，减少 **1.15%**；按 150 MHz 目标折算 **2.04473 ms、489.06292 任务/秒**。独立第一层仍为 **271,678 周期/任务**。详见 [第八版组间调度优化](docs/ffn-group-scheduling.md)。

第四版必做基线固定在提交 `d501f0d`；本地历史交付包为 `deliverables/undergraduate-v4-baseline.zip`，源代码归档为 `deliverables/v4-source-baseline.zip`。第五版完整 FFN 基线为 `aa344f9`，本地另存 `deliverables/full-ffn-v5-baseline.zip` 和 `v5-source-baseline.zip`。第六版基线为 `411a151`，本地保存在 `deliverables/full-ffn-v6-baseline.zip`、`deliverables/v6-source-baseline.zip`。第七版基线为 `eefe431`，本地保存在 `deliverables/full-ffn-v7-baseline.zip`、`deliverables/v7-source-baseline.zip`。正式时序、面积和功耗仍待工艺验证。

## 设计复现入口

在完成下文环境配置和资源下载后：

```powershell
.\design.ps1 all
```

依次执行：24 条训练样本的无梯度标定检查、120 条验证样本的逐层参考提取与数值检查、数值边界测试、MAC、Icarus 四态检查、12 层计算核 RTL、DMA 异常恢复、总线吞吐/仲裁、真实 E203 固件仿真、GELU 数值与硬件检查、完整 FFN 两种模式切换，以及计算核、DMA、总线和 E203 整机的通用综合/网表验证。完整回归可能需要十几分钟或更久，日志保存在 `output/design/`。

- [设计说明与寄存器协议](docs/architecture.md)：数值格式、存储布局、驱动及计时范围。
- [本科必做项验收记录](docs/acceptance.md)：已验证项目和官方验收缺口。
- [第八版组间调度优化](docs/ffn-group-scheduling.md)：当前性能、周期归因、资源与验证。
- [第七版搬运与 GELU 调度优化](docs/ffn-overlap-performance.md)：后台 GELU 与参数预取的历史基线。
- [第六版性能与资源对比](docs/full-ffn-performance.md)：双项乘加并行的历史基线。
- [完整 FFN 基础设计](docs/full-ffn.md)：第五版两种模式、冻结数值格式及 KWT5 协议。
- [第四版性能分析](docs/parallel-packed-performance.md)：保留的本科必做基线。
- [第三版 DMA 与周期分析](docs/dma-performance.md)：历史 DMA 和总线优化记录。
- [第二版优化记录](docs/frontend-performance.md)：流水 MAC 和 FIFO 的历史基线。
- `rtl/`：MAC、矩阵控制器、自主 DMA 和 SRAM 工艺边界。
- `integration/`：E203 CPU、三方轮转 System Bus 与 512 KiB 共享 SRAM 集成。
- `firmware/`：实际由 E203 执行的驱动、启动代码和链接脚本。
- `model/`：两种模式冻结的逐层指数、整数模型与固定样本文件清单。
- `tests/`：组件、矩阵、整机测试平台。
- `constraints/`：150 MHz 目标 SDC，无掩盖违例的路径例外。

按需运行 `calibrate`、`export`、`export-ffn`、`numeric`、`mac`、`fourstate`、`accel`、`dma`、`gelu`、`ffn`、`bus`、`soc`、`soc-ffn`、`synth`、`synth-dma` 或 `synth-soc`，例如 `.\design.ps1 soc`。SoC 仿真在停止计时后请求周期快照；`scripts/collect_results.py` 汇总为 `docs/cycle-analysis.json`。`tools.ps1` 保留为环境自检入口，不能替代设计验证。

当前 SoC 基址仍为 `0x40000000`，控制器 ID 为 `KWT5`（`0x4b575435`），模式寄存器 `0x38` 选择 0=第一线性层、1=完整 FFN。X/W 每个 32 位字传输两个相邻 int16 元素，先出现的元素放在低半字；b/Y 格式不变。使用配套固件和 `x_packed.hex/w_packed.hex`，旧 KWT3/KWT4 驱动不兼容。独立计算核原 MMIO 保留每字一个元素。

`export_vectors.py` 和 `convert_task.py` 自动生成紧凑文件；已有旧向量时运行 `python scripts/pack_vectors.py` 即可无损生成，无需重新量化。

任意实际层输入可用以下命令转换；输入 NPZ 包含浮点 `x[99,64]`、`w[64,256]`、`b[256]` 和可选参考 `y[99,256]`：

```powershell
.venv-model\Scripts\python.exe scripts/convert_task.py input.npz --layer 0 --output output/custom-task
.venv-model\Scripts\python.exe scripts/decode_output.py hardware-output.hex --layer 0 --output output/decoded.npy --reference input.npz
.venv-model\Scripts\python.exe scripts/evaluate_numeric.py evaluation-manifest.json --output output/evaluation.json
```

评测清单格式为 `[{"layer": 0, "npz": "sample_000_layer_00.npz"}, ...]`，覆盖 12 层且各层样本数相同；路径相对清单文件。该入口支持未来官方 600 条样本提取结果，不修改冻结数值配置。

官方音频清单可表示为相对数据集的路径 JSON 数组，静音用 `"silence"`；以下命令按指定源码的测试划分及标签索引核对清单，并保存全部逐层参考：

```powershell
.venv-model\Scripts\python.exe scripts/export_vectors.py --split testing --sample-list official-samples.json --save-all --output output/official
.venv-model\Scripts\python.exe scripts/evaluate_numeric.py output/official/evaluation-manifest.json --output output/official-evaluation.json
```

该流程只评估冻结配置，不能用测试结果回调量化尺度。

生成完整任务活动文件（可较大，GTKWave 需提供 `fst2vcd.exe`）：

```powershell
.venv-model\Scripts\python.exe scripts/capture_activity.py --netlist --tasks 1 --compressed
```

输出 `output/design/soc.fst` 和 `soc.vcd.gz`，日志给出计时窗口。改为 `--tasks 12` 可记录全部本地性能任务。活动文件需在正式工具中检查映射和覆盖，并补全 SRAM 功耗模型后才能用于正式功耗估算。

验证完成后运行 `python scripts/collect_results.py` 汇总记录并校验独立第一层相对第四版的性能回归，并单独汇总完整 FFN 结果，再运行 `python scripts/package_submission.py` 生成本地交付包 `deliverables/undergraduate-local-submission.zip`。包内含源码、约束、真实测试向量、固件、四类通用网表和验证记录；若为当前版本采集了整机活动波形，大文件作为独立附属文件保留在 `output/design/`。第一版活动文件位于 `output/baseline-v1/`，第二、三版报告和日志分别位于 `output/baseline-v2/`、`output/baseline-v3/`，第四、五、六版报告和日志分别在 `output/baseline-v4/`、`output/baseline-v5/`、`output/baseline-v6/`；第七版记录在 `output/baseline-v7/`；历史波形不作为第八版活动证据。这份包标记为本地实现交付，官方 PPA/平台验收仍待完成。

## 赛题范围

依据仓库中的 [赛题指南](芯片设计赛题指南.pdf)，本科生组必做第 1—3 项，核心计算为：

```text
Y = X × W + b
X: 99 × 64    W: 64 × 256    b: 256    Y: 99 × 256
支持 12 个编码器层的参数切换，并完成 SoC 集成及验证。
```

记录的约束包括 150 MHz 时钟、512 KB 共享 SRAM、加速器面积不超过 2.25 mm²、必做 NRMSE 不超过 3%；完整定义及验收口径以指南和官方后续通知为准。GELU、第二线性层、注意力、残差与 LayerNorm 属于选做，当前完整编码器按用户选定的第 4—7 项实现；官方分类精度和 PPA 验收仍待评测。机器可读范围见 [project-context.json](environment/project-context.json)。

官方 SoC 参考为 [riscv-mcu/e203_hbirdv2](https://github.com/riscv-mcu/e203_hbirdv2)。本项目固定其提交作为开发基线，不代表组委会指定了该提交。正式后端环境由官方后期提供服务器，届时对接工艺库、SRAM 宏及评测条件。

## 工程结构

```text
README.md                         使用说明及开发状态
芯片设计赛题指南.pdf                原始赛题指南
assets/resources.lock.json        公开资源版本、下载来源与校验值
environment/
  project-context.json            已确认的本科组范围
  requirements-model.in           模型依赖声明
  requirements-model.lock.txt     固定版本和包哈希
  local-tools.example.json        外部工具路径配置模板
  smoke/                          工具环境检查电路、测试平台和 Tcl
scripts/
  download_competition_assets.py  模型、数据集、SoC 和 SDK 下载校验
  fetch_model_wheel.py            TensorFlow 安装包下载校验
  install_native_toolchain.py     Nuclei GCC / Make 下载及安装
  check_model_environment.py      模型权重、特征和推理检查
  check_environment.py            HDL、综合、SDK 等环境检查
  clean-project.ps1               项目内缓存清理
docs/validation.json              本机环境验证结果快照
env.ps1                           当前终端的环境变量
setup.ps1                         创建模型环境及项目私有工具链
tools.ps1                         环境检查入口
```

模型、音频、第三方源码保存在本地 `assets/sources/`、`assets/datasets/`、`assets/references/`；工具和 Python 环境在 `.tools/`、`.venv-model/`；运行输出在 `output/`。这些可重新获取的内容不提交 Git。外部工具的本机路径保存在被忽略的 `environment/local-tools.json`。

## 首次配置

当前脚本面向 **Windows x64 + PowerShell + WSL Ubuntu**。先准备 Git 和 [uv](https://docs.astral.sh/uv/)，以及以下外部工具：

| 工具 | 本机已验证版本 | 用途 |
| --- | --- | --- |
| Icarus Verilog | 12.0 | RTL 与综合后仿真 |
| ModelSim | 2020.4，需可用许可证 | RTL 仿真 |
| WSL Ubuntu | 24.04 | 运行 Linux EDA 工具 |
| Yosys | 0.67 | 通用门级综合 |
| Verilator | 5.020 | RTL lint |
| OpenSTA | 3.1.0 | 启动检查，正式 STA 待工艺库 |
| GTKWave（可选） | 复用本机安装 | 查看 VCD 波形 |

`setup.ps1` 自动配置 Python 3.8.20、模型依赖、Nuclei GCC 14.2.1（2025.10 工具包）及 GNU Make 4.4.1。它复用上表的工具，不负责安装 WSL、仿真器、Linux EDA 或商业许可证。模型检查使用 CPU，无需 CUDA。

```powershell
git clone https://github.com/hhaxi/keyword_transfomer_accelerator.git
cd keyword_transfomer_accelerator

# 首次在新机器配置；已有 local-tools.json 时直接编辑，保留本机路径。
Copy-Item environment/local-tools.example.json environment/local-tools.json
notepad environment/local-tools.json
```

填写 Windows 工具的 `bin` 目录，以及 WSL 发行版名称和 Linux 可执行文件路径；Linux 工具也可填写 PATH 中的命令名。不要把本机配置提交到仓库。

下载公开资源（下载脚本使用 Python 3.13，与模型环境分离）：

```powershell
uv run --no-project --python 3.13 scripts/download_competition_assets.py
```

默认获取模型源码及权重、Speech Commands V2、E203 和 HBird SDK。可分开执行：

```powershell
uv run --no-project --python 3.13 scripts/download_competition_assets.py --components model hardware
uv run --no-project --python 3.13 scripts/download_competition_assets.py --components dataset
```

数据集压缩包约 2.43 GB，GCC 安装包约 1.54 GB；下载、解压及安装期间建议预留至少 20 GB 空间。数据集支持分段续传并验证 SHA-256；仓库快照逐文件验证 Git blob。运行元数据保存在 `assets/metadata/`，版本和校验基线见 [resources.lock.json](assets/resources.lock.json)。重新运行下载脚本会重新解压选中的参考源码，请将自己的代码放在独立目录中。

随后安装项目依赖并执行自检：

```powershell
.\setup.ps1
```

脚本仅设置项目内环境和当前终端 PATH，不替换系统 Python。若 PowerShell 的执行策略阻止运行，请按本机管理要求允许这些已审阅的项目脚本。

## 日常使用和验证

已配置的机器直接运行：

```powershell
. .\env.ps1
.\tools.ps1 all
```

`tools.ps1` 自身也会加载环境。分项检查如下：

| 命令 | 检查内容 |
| --- | --- |
| `.\tools.ps1 versions` | 工具版本 |
| `.\tools.ps1 model` | best_weights、全部模型权重、MFCC 和少量音频推理 |
| `.\tools.ps1 rtl` | Icarus 与 ModelSim 的有符号 MAC、复位和使能仿真 |
| `.\tools.ps1 synth` | Yosys 通用综合和综合后仿真 |
| `.\tools.ps1 sdk` | 上游 E203 SDK Hello World 编译、链接及 ELF32 检查 |
| `.\tools.ps1 lint` | Verilator lint |
| `.\tools.ps1 sta` | OpenSTA 启动检查 |

完整报告为 `output/environment/environment-report.json`，日志及波形同在 `output/environment/` 下。版本化的 [验证快照](docs/validation.json) 记录整理工程时的检查结果。

SDK 编译器前缀为 `riscv64-unknown-elf-`，支持 RV32 多库；检查采用 `rv32imac_zicsr_zifencei`、`ilp32` 和上游 `ddr200t` 参考配置。编译在输出目录中的 SDK 副本进行，产物包括 ELF、BIN、HEX、反汇编及 Verilog 存储文件。此检查尚未在 SoC 或板卡上执行程序。

## 模型与数据注意事项

- 使用 [ARM-software/keyword-transformer](https://github.com/ARM-software/keyword-transformer) 提交 `237e4097afd4f6851e0b82f0a8d65c2dfe8eae30` 下的 `models_data_v2_12_labels/kwt1/best_weights`。原始 `checkpoint` 默认指向 `last_weights`，必须显式选择 `best_weights`。
- 上游 README 表格的 KWT-1 `mlp-dim=128` 与指定 `flags.json` 不一致；该模型配置实际为 256，与本项目赛题维度一致。
- 上游要求 TensorFlow `2.4.0rc1`，配置时 PyPI 无法获取该版本，因此使用 **2.4.0 开发替代版**。NumPy 为 1.19.5，TensorFlow Addons 为 0.12.1；完整版本见依赖锁文件。与官方浮点参考的数值等价性仍需验证。
- 自检使用原始 Session 图模式、推理设置，关闭训练增强和 Dropout；607,308 个模型参数对应的 162 个权重张量均与 checkpoint 逐项精确匹配。旧版 checkpoint 可能显示无权重 GELU 层对象别名警告，实际权重不匹配会使检查失败。
- Speech Commands V2 保留完整词类、背景噪声、许可及官方划分列表：105,835 个 WAV（含 6 个背景噪声文件），验证列表 9,981 条、测试列表 11,005 条。十二分类映射、unknown 和 silence 处理应沿用指定源码。
- 环境自检包含静音及 3 条验证音频的重复推理；设计验证进一步覆盖 120 条验证样本的全部 12 层，导出 12 个硬件任务及逐层浮点参考。尚未执行官方 600 条样本评测。测试集不用于调节量化参数。

模型背景论文：[Keyword Transformer: A Self-Attention Model for Keyword Spotting](https://arxiv.org/abs/2104.00769)。论文 PDF 不属于自动下载及构建的必需输入。

## 清理和版本管理

先预览，再执行：

```powershell
.\scripts\clean-project.ps1 -WhatIf
.\scripts\clean-project.ps1
```

清理范围是项目内下载压缩包、TensorFlow wheel 缓存、临时输出、运行时下载元数据和源码的 Python 缓存。版本化的资源校验清单、验证快照、已安装环境、工具、解压的数据集及参考源码保留。请先保存需要长期留存的 `output/` 结果；这些输出不受 Git 保护。清理后日常自检仍可运行，重新执行安装或下载脚本可能重新获取已删除的安装包。

第三方源码、权重、数据集和工具遵循各自上游许可；仓库仅记录来源并提供获取脚本，不随 Git 分发这些大文件。原始许可文件保留在下载内容中。

## 后续官方验收

1. 接入组委会最终平台地址、参数加载环境和 SRAM 宏接口。
2. 在官方服务器完成指定工艺映射和 150 MHz STA，核验面积不超过 2.25 mm²。
3. 用统一条件和覆盖检查通过的活动文件估算整机功耗及单任务能耗。
4. 对齐官方浮点环境，执行冻结后发布的 600 条评测样本及 12 个性能任务。

当前数值精度和功能结论限于仓库记录的本地测试集；Yosys 为通用门级综合，尚不能据此判定正式工艺频率、面积和功耗达标。
