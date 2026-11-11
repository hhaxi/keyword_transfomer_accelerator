# FFN1 门控时钟候选：一参考＋四候选

以 q64_bank1_fmt1 为冻结参考，保持 pause64 固件、64 个乘法器、INT40 输出、
37 KiB 本地 SRAM 和所有调度不变。验收要求每个任务的严格周期和全部性能计数
完全不变。当前前端结果见 `reports/RESULTS.md`；本机没有实际 ICG 库映射或 PPA 结果。

| 候选 | 改动 | 计划新增 ICG | 受控数据寄存器位 |
|---|---|---:|---:|
| fmt1_ref | 原 q64_bank1_fmt1 RTL 原样复测 | 0 | 0 |
| fmt1_cg_result | 结果缓冲按 4 行分组，发布时开时钟 | 4 | 1280 |
| fmt1_cg_mac | 累加器按 4 行分组，有效乘加/清空时开时钟 | 4 | 1280 |
| fmt1_cg_formatter | 3 个组装分片＋1 个已完成分组分别门控 | 4 | 311 |
| fmt1_cg_combined | 合并上述三项 | 12 | 2871 |

控制、DMA、SRAM、E203 和测试向量保持相同。没有新唤醒状态或额外拍。
门控使能使用低电平锁存，保留 LAST 和融合首乘积；清空时对应门控必须开启。
SoC 功能模式的 test_en 固定为 0；时钟门控组件另外验证测试覆盖行为。

## 队友运行服务器

解压到新目录；包内包含全部独立 case、固定固件、12 套向量和完整日志，不需要上一轮目录：

```bash
tar -xzf ffn1_clock_gating_2026-11-06.tar.gz
cd ffn1_clock_gating
python3 tools/verify_package.py
# 加载现有 VCS/DC、许可证和工艺库环境
bash run_server.sh --quick --group all --check
bash run_server.sh --quick --group all
# 后续对全部 12 个任务进行复核
bash run_server.sh --full --group all
```

默认 all 即全部五组；也可用 `--group result/mac/formatter/combined` 做单因素对照。
`--case` 可重复，入口自动加入 fmt1_ref。支持既有 `--sim`、`--dc`、`--resume`
和工具路径参数。快速结果在 `vcs_quick_study/server/comparison.*`，完整结果在
`study/server/comparison.*`。每次 DC 前先比较同一次 VCS 参考和候选的逐任务周期、
全部计数与门控监测；变化即停止，不会只比较有利的平均值。

## 实际 ICG 映射

前端 latch 模型只供仿真和结构检查。DC 的 SYNTHESIS 路径使用
`KWT_USE_LIBRARY_ICG`，由 `script/clock_gating.tcl` 在已加载 .db 中寻找
`latch_posedge` 类 ICG，通过 `clock_gate_*_pin` 属性识别端口，生成实例头文件。
没有可验证的兼容单元时直接失败，不能回退成普通 AND 门或行为模型后宣称完成。
默认在可用单元中选面积最小者；也可指定已核对的库单元：

```bash
export KWT_ICG_LIB_CELL='实际库名/实际ICG单元名'
bash run_server.sh --quick --group all
```

请使用服务器实际名称，不要原样复制占位符。驱动/负载是否合适以时序和扇出报告为准。
四个时钟分组保持独立，综合网表核对对应 ICG 数量。E203 的既有门控不纳入新增数量。
各组必须使用相同库单元选择和约束；不对整个 SoC 开启额外自动门控，以保持归因。
库默认目录仍为 `$HOME/Desktop/lib`，私有配置仍支持 `KWT_GLOBAL_LOCAL_CONFIG`。

后端验收必须同时满足：

1. 逐任务周期/计数与 fmt1_ref 一致；RTL 输出正确。
2. `icg_library_mapping.rpt`、`icg_instances_final.rpt` 与计划一致。
3. 150 MHz setup/hold、门控使能与脉宽检查合格；不得新增 false path 隐藏违例。
4. 进行综合后功能等价或门级仿真，使用实际 ICG/标准单元模型；前端模型验证不能代替。
5. 检查 `clock_gating.rpt`、SAIF 映射和每个门控输出的活动传播，确认关钟行为真实；
   SRAM 与未直接标注的电路不能按零功耗处理。必要时以门级 VCD/SAIF 交叉核对。
6. 同一严格窗口统计 SoC 总功耗和能量，包含新增 ICG 和缓冲开销。结果必须优于同次参考才保留。

所有脚本完成标记均不自动表示后端验收通过。当前服务器参考摘录为 168.105 mW、
62.105275 uJ/task、added area 335530.49（库单位）、SS hold WNS -0.16 ns、覆盖待审，
仅 task00；新参考必须同环境复跑。竞赛要求综合阶段评估，不额外要求布局布线。

## 前端复现和证据

仓库中的 study 可再生；独立压缩包已包含它，无需 prepare：

```bash
python3 tools/prepare.py
python3 tools/test_components.py
python3 tools/simulate.py --tasks 12 --jobs 2 --build-jobs 2
python3 tools/check_structure.py
python3 tools/test_backend_adapter.py
python3 tools/check_server.py
python3 tools/handoff.py --package
```

需要 Icarus、Verilator、Yosys；adapter 测试需要 Python tkinter/Tcl，不需要 DC。
prepare 使用上一轮归档的固定 SHA256，拒绝覆盖；完整源码差异在 reports/design_diffs。
reports 中保留逐任务仿真、门控沿统计、哈希、四状态测试、结构检查、适配器模拟测试
及旧服务器驱动的继承证据。旧版 verification/baseline.json 仅作历史追溯。
门控沿统计不是功耗估计；12 层整数一致性也不替代官方 600 样本精度验收。
