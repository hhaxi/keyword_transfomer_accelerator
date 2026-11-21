# Q128 FFN1 · IRQ/WFI

报告基础任务采用 `reference_sleep`。计算核为 8 × 8 输出驻留阵列、每个 PE 双路乘加，共 128 路 MAC。输入与权重为 INT16，内部以 INT40 累加，输出经就近取偶舍入及饱和写回 INT16。E203 通过 IRQ/WFI 等待 Host 和 DMA 事件。[报告结果](../../docs/results/README.md)

`reference_sleep/` 保留完整封包。源码、向量、服务器配置和 `SHA256SUMS` 使用原始字节。以下命令从仓库根目录开始。

## 本地 RTL 回归

准备 Python 3、Verilator、Make 和支持 `rv32imac_zicsr_zifencei` 的 RISC-V GCC 工具链。在 Windows 上可以使用 WSL。Ubuntu 软件包安装的 Verilator 可在工具配置中填写 /usr/bin/verilator_bin。

```bash
cd projects/ffn1/reference_sleep
sha256sum -c --quiet SHA256SUMS
mkdir -p cases/environment
cp -n environment/local_tools.example.json cases/environment/local_tools.json
${EDITOR:-vi} cases/environment/local_tools.json
cd cases/reference_sleep
python3 verify.py --tasks 12 --cycle-breakdown
```

回归覆盖逐任务复位和连续运行两种模式，各自检查 12 组层参数和 304,128 个输出。生成文件位于案例目录的 `output/` 和 `tmp/`。需保留原始封包时，在工作树外复制 `reference_sleep/`，并在副本中运行。[原始回归记录](reference_sleep/LOCAL_RESULTS.md)

## DC/VCS 服务器

加载 VCS 和 Design Compiler，并按部署环境配置原封包需要的工艺库与宏模型。

```bash
cd projects/ffn1/reference_sleep
sha256sum -c --quiet SHA256SUMS
bash run_combined.sh --resume
bash run_combined.sh --report-only
```

服务器封包默认对 `task00` 采集 RTL-SAIF。报告第 6 章中的 37.346 mW 和 7.6038 µJ 来自另外的第 4 层任务。[服务器结果](reference_sleep/reports/RESULTS.md) · [第 4 层原始摘要](../../docs/evidence/report/ffn1-layer04-ppa.txt)
