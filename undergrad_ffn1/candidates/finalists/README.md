# FFN1 候选版本与服务器复现

这里保留四个值得继续比较的本科 FFN1 版本。每组均包含真实 E203、独立 ITCM/DTCM、
512KiB共享 SRAM 和 `Y[99,256] = X[99,64] × W[64,256] + bias[256]` 加速器。
保持 INT16 输入/权重、INT32 bias 和 INT40 精确累加，不包含 Attention、GELU 或 FFN2。

| 版本 | 目录名 | 选择原因 |
|---|---|---|
| 16 MAC 基线 | flat_f0_p0_o0_w0_b1_d1_h0 | 作为较小计算结构的面积与性能基准 |
| 16 MAC 暂停轮询 | flat_f0_p0_o0_w1_b1_d1_h0 | 比较同类硬件上 CPU 调度和总线竞争的影响 |
| 32 MAC 融合＋WFI | dual32_f1_p0_o0_w2_b1_d1_h0 | 两行共享权重广播，组间预取/首项融合，中断等待 |
| 32 MAC 无损打包 | dual32_f0_p0_o1_w1_b1_d1_h0 | 40位无损打包与暂停轮询，保留吞吐较高的候选 |

周期、验证证据和结论范围见 [测试报告](reports/RESULTS.md)。
新增 [单任务快速筛选](docs/quick-screen.md)：`bash run_quick_screen.sh`，四组统一使用task00，
结果写入独立 `vcs_quick_study`；原12任务流程保留。
源码位于 `vcs_power_study/cases/`，各组配置位于自己的 `case.json` 和 `config/`。
只提交复现所需源码、向量、固件镜像、日志及报告；大体积波形、工艺库、综合网表和私有配置不在仓库中。

## 服务器一键执行

在当前用户 Desktop 的仓库副本中，加载已有 Synopsys 环境及许可证，进入本目录：

```bash
cd undergrad_ffn1/candidates/finalists
bash run_vcs_power.sh --check
bash run_vcs_power.sh
```

需要 Python3.6+、VCS、g++、vcd2saif 和 DC。固件镜像已随各组源码固定，无需服务器 RISC-V GCC。
默认使用 `$HOME/Desktop/lib` 中现有 SS 标准单元/SP SRAM db；正式流程不转换 lib。
`--check` 只检查工具是否可找到、源码/向量/固件和DC入口是否齐全，不启动仿真或综合；
商业许可证和工艺库加载仍在真实工具执行时检查。正式运行也会先进行这项预检。
工具路径可用 `--vcs`、`--cxx`、`--vcd2saif`、`--dc-shell` 指定。

流程为 **VCS 编译 → 每组12任务功能/计数检查 → VCD任务窗口裁剪 → SAIF转换 → 新SoC综合 → 功耗/面积/时序对比**。
只有通过检查的活动才会进入分析。VCS/DC 的真实执行结果由服务器产生，本机未宣称商业工具通过。

生成的对比表为 `vcs_power_study/server/comparison.md`，同时生成 CSV/JSON。
完整说明和分阶段命令见 [VCS流程](docs/vcs-power.md)、[活动/DC分析](docs/power-server.md)。

```bash
bash run_vcs_power.sh --sim                 # 只采集并验证VCS活动
bash run_vcs_power.sh --dc                  # 对已验证的VCS活动重新综合分析
bash run_vcs_power.sh --resume              # 复用仍匹配的VCS采集，重新综合
bash run_vcs_power.sh --case dual32_f0_p0_o1_w1_b1_d1_h0
```

本轮权重来自现有12层 W1/bias，输入 X 为合成向量；无损指与现有整数模型逐位一致，
不等同 FP32 无误差或官方分类准确率。保留每个依赖的许可证和固定源码信息。
