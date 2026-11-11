# 服务器 VCS 仿真 → 活动功耗 → DC 综合对比

这份交付只带四组源码、真实 E203、12 层测试向量、已验证固件镜像和脚本。
不需要上传以前 8GiB 的 VCD 包，也不需要在服务器安装 RISC-V GCC。
四组为 flat 基线、flat 暂停轮询、dual32 融合＋WFI、dual32 无损40位打包。
RTL、INT16/INT32/INT40 数值规则及原先测试结果保持不变。

## 一次执行

把交付目录整体上传到当前用户 Desktop 下的新目录，保留 `sources/` 分卷子目录。
每卷不超过 8MiB，小于10MB。进入上传目录，加载服务器已有的 VCS/DC 环境及许可证后执行：

```bash
bash restore.sh
cd activity_power_ffn1
bash run_vcs_power.sh --check
bash run_vcs_power.sh
```

入口使用 Bash，可从服务器默认的 csh/tcsh 调用。还原需要 Python3.6+；完整流程还需要
`vcs`、`g++`、`vcd2saif`、`dc_shell` 在 PATH 中。
正式运行开始前会检查完整请求链的工具和输入；`--check` 只执行这项预检，不消耗仿真/综合时间。
该预检不会申请商业许可证，也不加载db；许可证和库模型由后续真实VCS/DC调用检验。
标准单元和原生 SP SRAM 的 SS db 默认仍在 `$HOME/Desktop/lib`。
不包含 lib→db 转换。私有库路径可使用已有 `KWT_GLOBAL_LOCAL_CONFIG` Tcl 覆盖机制。

依次完成：

1. 校验四组源码、72份/组向量和固件镜像散列，按镜像字数生成 `size.vh`。
2. VCS 编译整机和独立测试平台，运行每组12个复位任务；逐元素比对全部输出，检查 DMA/MAC 计数。
3. 生成整机 DUT VCD，并按每个任务的严格时间窗口裁剪和压缩。通过验证后释放原始长 VCD。
4. 用 `vcd2saif` 转成12份 SAIF，为每组重新综合整个 SoC，并逐任务导入活动分析功耗。
5. 生成面积、严格周期、吞吐、动态/漏电/总功耗、平均能量/任务以及 setup/hold WNS 对比表。

VCS 的编译和仿真日志会实时输出。输出或计数检查失败时停止，不会继续拿该组的活动算功耗。
每次使用独立的 build/activity/DC 目录，保留先前结果和失败日志。

## 结果与日志

```text
vcs_power_study/server/comparison.md
vcs_power_study/server/comparison.csv
vcs_power_study/server/comparison.json
vcs_power_study/cases/版本名/output/activity/attempt_*/compile.log
vcs_power_study/cases/版本名/output/activity/attempt_*/simulation.log
vcs_power_study/cases/版本名/output/activity/capture.json
```

时钟为6.666667ns，精度1fs。任务计时从第一笔 Host 输入/参数装载请求，到最后一个 DMA
输出写响应；包含总线传输、调度、等待和计算，排除任务前复位、一次性固件预装载和输出读回检查。
平均功耗按任务持续时间加权；平均能量为 `sum(P_i*T_i)/12`。
沿用原 `compile_ultra -no_autoungroup`、0.1ns uncertainty 和 I/O 约束。

功耗是 RTL 活动应用到综合结果的估计。SRAM 功能仿真采用现有独立编写的同步 SP 接口模型，
综合时用实际 SRAM db。VCS 四态输出检查保留。没有启用强制寄存器清零或全局 MDA 内存数组转储。
需检查实际 VCS 波形、SAIF 名称映射、CPU/FIFO 寄存器与 SRAM 引脚覆盖；覆盖率审核和时序通过
分别记录。详细活动/DC 报告方式见同目录 `power-server.md`。

本轮向量为12层真实权重配合合成 X；不代表官方冻结后指定样本。
本机没有 VCS/DC 许可证环境，因此本地验证不等于实际服务器商业工具执行通过。

## 分阶段运行与重试

```bash
bash run_vcs_power.sh --sim
bash run_vcs_power.sh --sim --resume
bash run_vcs_power.sh --dc
bash run_vcs_power.sh --case dual32_f1_p0_o0_w2_b1_d1_h0
bash run_vcs_power.sh --resume
```

`--sim` 只生成并验证 VCS 活动；`--dc` 只分析当前通过验证的 VCS 活动，仍重新综合。
`--resume` 只复用完整且当前源码、工具、固件、日志、可执行文件和 VCD 均匹配的 VCS 采集。
它不会把本地旧 Verilator 采集当成服务器 VCS 结果，也不表示跳过新 DC 综合。
默认在首个失败处停止，修复后可按 `--case` 单独重试。

工具不在 PATH 时，可使用 `--vcs /路径/vcs --cxx /路径/g++` 或 `VCS`/`CXX` 环境变量。
转换和综合工具也可使用 `--vcd2saif /路径/vcd2saif --dc-shell /路径/dc_shell` 指定，
这些参数会传递到实际的活动转换和DC入口。
