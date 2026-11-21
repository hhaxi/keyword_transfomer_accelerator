# 主分支复现

本页命令在 `main` 的仓库根目录运行，用于基线 FFN／编码器的本地验证。报告的 Q128、紧凑单路 ASIC 和 Z100 分别使用对应的工程入口与配置。[报告结果与源码版本](results/README.md)

## 安装环境

脚本面向 Windows x64、PowerShell 和 WSL Ubuntu。准备 Git、uv、WSL 中的 Verilator 与 Yosys，以及 Windows 的 Icarus Verilog。完整环境自检还会调用配置中的 ModelSim 与 OpenSTA。模型运行在 CPU 上，`setup.ps1` 安装仓库私有的 Python 环境和 RISC-V 工具链。模型与数据版本由[资源清单](../assets/resources.lock.json)锁定。

```powershell
# 首次配置，已有 local-tools.json 时编辑现有文件。
Copy-Item environment/local-tools.example.json environment/local-tools.json
notepad environment/local-tools.json

uv run --no-project --python 3.13 scripts/download_competition_assets.py
.\setup.ps1
```

模型环境使用 Python 3.8.20、TensorFlow 2.4.0 和 NumPy 1.19.5。下载及安装建议预留至少 20 GB。[模型依赖锁文件](../environment/requirements-model.lock.txt)

## 运行验证

```powershell
# 先生成基础模型／FFN 向量并执行独立模式验证。
.\design.ps1 all

# 再执行完整编码器流程，包含耗时的综合与网表回归。
.\encoder.ps1 all
```

编码器默认样本选择依赖 `output/vectors/` 和 `output/calibration/`。已有向量时可单独运行以下阶段。

| 命令 | 内容 |
| --- | --- |
| `.\encoder.ps1 input-single` | 单层同固件 SRAM／直传对照 |
| `.\encoder.ps1 input-protocol` | 输入分块、背压、取消和四态恢复 |
| `.\encoder.ps1 input-full` | 12 条直传输入的十二层回归及 SRAM 对照 |
| `.\encoder.ps1 component`、`transfer`、`fourstate`、`faults`、`lint` | 算子、中间值、传输、故障及结构检查 |
| `.\encoder.ps1 compat`、`soc` | 两种独立 FFN 模式及 E203 编码器 RTL 回归 |
| `.\encoder.ps1 synth`、`netlist`、`compat-netlist` | 保留 SRAM 边界的通用综合及网表回归 |
| `.\encoder.ps1 collect`、`package` | 汇总本地输入直传证据并生成交付包 |

整机回归可按样本并行。默认使用 SRAM 输入与输出 FIFO，`--input-stream 1` 启用输入直传。

```powershell
. .\env.ps1
.venv-model\Scripts\python.exe scripts/run_encoder.py soc --tasks 12 --jobs 4
```

[输入直传复现与协议](studies/input-stream.md) · [定点模型全量样本复现](validation/encoder-validation-expanded.md)

## 产物与清理

构建、固件、向量和日志写入 `output/`，本地归档写入 `deliverables/`。打包以 Git 已跟踪和已暂存源码为输入。下载的模型权重、音频、第三方源码及本地环境由安装流程准备。

清理前可运行 `.\scripts\clean-project.ps1 -WhatIf` 预览。脚本清理下载缓存、临时目录和可重建的构建目录，保留已安装环境、数据集、下载后的参考源码、验证证据与交付归档。
