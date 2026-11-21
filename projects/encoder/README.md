# KWT-1 紧凑单路编码器

ENC1 和 FFN 行引擎在 E203 SoC 上执行 12 层 PostNorm 编码器。层内采用双向 FIFO，层间保留 LN2 结果。SoC 和 Z100 入口来自 `fpga@d9b7a03`，`rtl/ffn1_row/` 保留该版本的 FFN 行核与配置。[报告结果与源码版本](../../docs/results/README.md)

## 环境

以下命令从 `projects/encoder/` 运行。使用 Windows x64、PowerShell、WSL Ubuntu、Git 和 uv。在 WSL 中准备 Verilator、Make 和 Yosys，在 Windows 中准备 Icarus Verilog。完整环境自检还检查配置中的 ModelSim 与 OpenSTA。

```powershell
# 首次配置。已有 local-tools.json 时编辑现有文件。
Copy-Item environment/local-tools.example.json environment/local-tools.json
notepad environment/local-tools.json

uv run --no-project --python 3.13 scripts/download_competition_assets.py
.\setup.ps1
```

模型环境使用 Python 3.8.20、TensorFlow 2.4.0 和 NumPy 1.19.5。上游 E203、KWT-1 和 Speech Commands V2 由[资源清单](assets/resources.lock.json)锁定。首次安装与下载建议预留至少 20 GB。

## 复现 12 层 RTL

```powershell
.\encoder.ps1 all
```

`all` 使用 `model/validation-samples.json` 的前 12 条记录导出固定输入和参考值，随后以 `--contest --compact 1 --input-stream 1` 运行 E203 SoC 回归。各条输入执行全部 12 层，比对 6,336 个整数输出。`.\encoder.ps1 export` 仅生成向量，`.\encoder.ps1 soc -Jobs 4` 使用已有向量运行回归。

日志写入 `output/design/`，固件写入 `output/encoder-design/firmware/`。若默认向量目录已有不同样本集，用 `scripts/export_encoder.py --output` 导出到新目录，并在确认后把指定样本集放到 `output/encoder-vectors/`。

[Z100 工程生成与上板](integration/z100/README.md) · [软件全量数值评估](../../docs/validation/encoder-validation-expanded.md)

## 本地产物

工具、数据和生成文件保存在工程本地。用 `.\scripts\clean-project.ps1 -WhatIf` 查看可清理的下载缓存、仿真构建目录和 Python 缓存。证据、冻结向量、已安装工具和交付归档保留在各自目录。
