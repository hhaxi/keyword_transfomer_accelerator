# 四候选单任务快速筛选

四组统一运行 `task_00`：每组1次完整FFN1、25,344项输出比对、1份VCD/SAIF，然后分别重新综合SoC。
总计4个仿真任务、4份任务波形，原12任务入口仍保留。
所有整数计算、RTL、固件和输入参数不变，只减少本轮采样任务数。

独立压缩包请解压到新目录，避免覆盖服务器正在运行的旧脚本：

```bash
tar -xzf ffn1_quick_screen.tar.gz
cd activity_power_ffn1_quick
# 先加载服务器已有VCS/DC环境与许可证
bash run_quick_screen.sh --check
bash run_quick_screen.sh
```

服务器已存在 `$HOME/Desktop/activity_power_ffn1` 时，也可只上传小工具包 `ffn1_quick_tools.tar.gz`：

```bash
cd "$HOME/Desktop"
tar -xzf ffn1_quick_tools.tar.gz
cd ffn1_quick_tools
bash run_quick_screen.sh --check
bash run_quick_screen.sh
```

小工具包默认从原目录只读复制合格源码、固件及向量，不需要再次上传这些数据。
原目录不在上述位置时，使用 `--source-study /原工程/vcs_power_study` 指定。

已有Git副本则进入 `undergrad_ffn1/finalists`，运行同一 `run_quick_screen.sh`。
需要 Python3.6+、VCS、g++、vcd2saif、DC，以及 `$HOME/Desktop/lib` 中现有SS库。
工具路径可通过 `--vcs`、`--cxx`、`--vcd2saif`、`--dc-shell` 指定。

入口只复制源码、固件和向量到独立的 `vcs_quick_study`，不复制旧VCD、旧DC结果或simv。
它不会改动原 `vcs_power_study` 中的12任务结果；失败日志和每次尝试独立保留。
每组运行任务0，通过功能和DMA/MAC计数检查后才发布该次活动。
VCD导出显示扫描、压缩、完成进度。

输出对比表：

```text
vcs_quick_study/server/comparison.md
vcs_quick_study/server/comparison.csv
vcs_quick_study/server/comparison.json
```

表内比较新增/SoC面积、周期、吞吐、动态/漏电/总功耗、能量/任务及setup/SS hold WNS。
`Sample=task_00_only` 明确表示单任务估算。能量使用本任务的实际功耗×持续时间，不再除以12。
名称映射与活动覆盖率仍需核查，不产生官方得分或12层平均功耗结论。

快速模式显著减少仿真、波形扫描/压缩和SAIF转换工作量；DC仍需综合四组，综合耗时不会按1/12缩短。
最后保留的候选可以通过原入口做完整12任务复核。

```bash
bash run_quick_screen.sh --sim       # 只做四组单任务VCS采集
bash run_quick_screen.sh --dc        # 用已通过验证的单任务活动重新综合
bash run_quick_screen.sh --resume    # 复用仍匹配的单任务采集，再重新综合
bash run_vcs_power.sh                # 保留原来的12任务完整流程
```

不要在旧任务运行期间将新版工具覆盖到旧目录；活动与源码散列绑定，覆盖会使一致性检查失败。
本机只验证脚本逻辑及独立打包，真实单任务VCS/DC结果由服务器运行产生。
