# 本科 FFN1 前端候选交付

本轮只修改前端RTL/配置及等待固件，保留原有数值合同和真实E203集成。
原四候选与冻结基线未改动。`reports/RESULTS.md`、`comparison.csv/json`
给出功能仿真的实测周期与结构数据；面积、功耗、时序等待服务器执行。

## 设计与分组

| 目录名 | 设计 | 用途 |
|---|---|---|
| ref32_packed_pause | 原32 MAC packed40＋暂停轮询 | 同条件复测基准 |
| q32_pause | 仅新增组装/发送并行的输出队列 | 单因素对照 |
| q32_fused_pause | 输出队列＋组间首乘积融合 | 32 MAC速度候选 |
| q32_fused_wfi | 同上＋中断/WFI固件 | 32 MAC能耗候选 |
| q64_fused_pause | 四行权重广播、64 MAC＋队列＋融合 | 吞吐候选 |
| q64_fused_wfi | 同上＋中断/WFI固件 | 64 MAC能耗候选 |
| q64_pipe_pause | 64 MAC版增加乘积和寄存级 | 时序探索候选 |

每组位于 `study/cases/<目录名>/`，包含独立RTL、固件源码/固定镜像、12套向量、
文件列表、宏封装、VCS测试平台、DC配置及脚本。服务器不需要RISC-V编译器。
公共服务器驱动在 `study/tools`，正式功耗分析脚本在 `study/script`。

所有组都包含输入/权重/偏置实际装载和结果写回，没有省略跨任务加载，没有新增
绕过共享SRAM的结果直传路径。输出仍是无损packed40，整数算术不变。

## 队友如何运行

将 `ffn1_frontend_candidates_2026-11-05.tar.gz` 解压到一个**新目录**：

```bash
tar -xzf ffn1_frontend_candidates_2026-11-05.tar.gz
cd ffn1_frontend_candidates
python3 tools/verify_package.py

# 加载服务器现有VCS/DC环境、许可证及工艺库后：
bash run_server.sh --quick --group recommended --check
bash run_server.sh --quick --group recommended
```

默认 `--quick --group recommended`：同一task00比较原版、32 MAC融合版、
64 MAC融合版和64 MAC流水版，共4组。结果写入
`vcs_quick_study/server/comparison.md`，另有CSV/JSON；不会覆盖完整12任务目录。

```bash
# 加入WFI版比较活动功耗（原版＋两组32 MAC＋两组64 MAC）
bash run_server.sh --quick --group energy
# 全部7组，包含输出队列单因素对照
bash run_server.sh --quick --group all
# 单独指定候选；--case可重复，此时覆盖分组选项
bash run_server.sh --quick --case q64_fused_pause --case q64_pipe_pause
# 对筛选留下的候选进行12任务完整复核
bash run_server.sh --full --case q32_fused_pause --case q64_fused_pause
```

`--group controls`选择原版→仅队列→队列＋融合，便于解释逐项收益。
未指定quick/full时默认quick。支持既有 `--sim`（只VCS采集）、`--dc`（分析已验证活动）、
`--resume`，以及 `--vcs`、`--cxx`、`--dc-shell`、`--vcd2saif` 路径参数。

完整流程为 VCS功能/计数检查→严格任务窗口VCD→SAIF→SoC综合→面积/时序/任务功耗。
完整12任务结果在 `study/server/comparison.*`。请保留活动映射与SRAM引脚覆盖报告。
默认工艺库与旧工程相同，从 `$HOME/Desktop/lib` 解析；私有路径可在自己的
`config/local_config.tcl` 或 `KWT_GLOBAL_LOCAL_CONFIG` 指定，详见各case库配置。
不要将不同任务窗口的功耗和周期混用。单task00不能代表12层平均能量。

## 仿真记录和复现

- `reports/qualification_*.json`：每组12次复位＋12次连续运行的窗口、计数、源码/固件/向量散列。
- `reports/logs/<设计>/reset.log`、`continuous.log`：完整逐任务通过记录。
- `reports/structure_*.json`：Yosys前端展开后的MAC和SRAM实例统计，无工艺映射。
- `reports/formatter/`：Icarus四状态随机数据/背压、清空和非法索引检查。
- `reports/source_reference.json`：原最快候选的只读源文件散列。
- `PLAN.md`：逐项优化的旧行为、改法、收益预期与风险。
- `package_manifest.json`：交付包每个文件的SHA256；压缩包旁有整体SHA256。

仓库中 `study/` 为可再生目录，交付压缩包已包含所有独立case。首次从仓库生成：

```bash
python3 tools/prepare.py
python3 tools/simulate.py --jobs 1 --build-jobs 4 --gcc /path/to/riscv64-unknown-elf-gcc
python3 tools/check_structure.py
python3 tools/test_formatter.py
python3 tools/test_server_flow.py
python3 tools/test_native_exporter.py  # Linux/WSL g++；补测原测试中固定Windows路径的native导出器
python3 tools/handoff.py --package
```

`prepare.py`依赖仓库现有finalists且拒绝覆盖已有候选目录；解压交付包无需运行它。
本机通过WSL Verilator执行整机仿真，暂停轮询候选保留原镜像，WFI候选使用GCC 13.2
编译；相关命令已记录。服务器以固定镜像重新验证，不依赖本地编译缓存。
原脚本测试中因WSL缺少tkinter而跳过的5项Tcl模拟测试，已在Windows Python/Tcl环境补跑，
结果见 `reports/server_tcl_tests.log`；这些测试不需要DC许可证。

150MHz折算吞吐不等于已达成时序；输出双缓冲增加寄存器，64 MAC增加计算资源和
2 KiB本地SRAM，流水增加寄存级。只有服务器真实库对照后才能判断PPA是否更优。
