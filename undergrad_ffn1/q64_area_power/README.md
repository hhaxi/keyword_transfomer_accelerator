# q64_fused_pause 面积与功耗候选交付

以已验证的 `q64_fused_pause` 为冻结参考，仅修改本科 FFN1 RTL。
真实 E203、Host 装载、共享存储、SRAM 数量、64 个 MAC、pause64 固件和
12 层权重/合成 X 保持相同。功能结果和严格周期见 `reports/RESULTS.md`。
本机没有工艺映射、面积、功耗或时序闭合结果；这些候选的 PPA 收益待服务器验证。

## 候选与归因

| 名称 | 相对父项的变化 | 父项 |
|---|---|---|
| q64_ref | 原 q64_fused_pause RTL/固件原样保留 | — |
| q64_seq | 用顺序计数器替代 64×15 位结果地址存储 | q64_ref |
| q64_bank2 | 两个固定 32 结果分组，替代动态循环 FIFO 批量写入 | q64_seq |
| q64_bank1 | 只保留一个 32 结果分组，最后一次读出时可同时写入下一组 | q64_bank2 |
| q64_bank1_mac38 | 精确的 33 位乘积对和、38 位累加器，输出仍为 INT40 | q64_bank1 |
| q64_bank1_fmt1 | 打包器的已完成分组缓冲从两组降为一组，保留独立组装 | q64_bank1 |
| q64_lean | 单组结果缓冲＋精确位宽＋单组打包缓冲 | q64_bank1_mac38 |
| q64_lean_earlyfree | 最后乘加完成即释放旧 X tile，提前启动后续装载 | q64_lean |

累加器位宽来自完整 INT16×INT16、64 项和 INT32 bias 的范围界限；没有截断、
饱和或重新量化。队列/地址发生器限定 4 行×8 列、KPAR=2 的当前几何结构。
单组缓冲减少弹性，可能付出少量周期；请对照实测值选择，不能假定全部候选更快。

## 服务器运行

将压缩包解压到新目录，无需 RISC-V 编译器，也无需上一轮工程：

```bash
tar -xzf ffn1_q64_area_power_2026-11-06.tar.gz
cd ffn1_q64_area_power
python3 tools/verify_package.py
# 加载现有 VCS/DC、许可证和工艺库环境后
bash run_server.sh --quick --group all --check
bash run_server.sh --quick --group all
```

`all` 比较全部 8 组；默认 `recommended` 选择参考、顺序地址、双组、单组窄位宽、
组合版，共 5 组。`controls` 用于结果队列的逐项归因；`arithmetic` 比较位宽；
`formatter` 比较打包缓冲；`schedule` 比较 X tile 提前释放。`--case` 可重复并覆盖分组选择。

```bash
# 筛选后，用相同 12 个任务复核候选和参考
bash run_server.sh --full --case q64_ref --case q64_bank2 --case q64_lean
```

快速结果在 `vcs_quick_study/server/comparison.md` 及 CSV/JSON，完整结果在
`study/server/comparison.*`。支持原驱动的 `--sim`、`--dc`、`--resume` 和工具路径参数。
工艺库默认从 `$HOME/Desktop/lib` 解析；私有路径使用 `KWT_GLOBAL_LOCAL_CONFIG`
或各 case 的 `config/local_config.tcl`。保留完整面积、setup/hold、活动映射和 SRAM
引脚覆盖报告。不要用 vectorless 功耗替代任务能量；task00 不能代表 12 层平均能耗。
上一轮参考的 SS hold WNS 为 −0.19 ns，本轮仍需完整检查 hold 修复后的面积和功耗。

## 验证与复现

- `reports/qualification_*.json` 和 `reports/logs/`：逐任务窗口、输出、DMA/MAC 计数和输入散列。
- `reports/components/`：四状态 MAC 极值/随机、队列背压/尾块/清空/复位、打包器测试。
- `reports/structure_*.json`：Yosys 通用 RTL 展开统计；寄存器位数/选择器位数不是工艺面积。
- `reports/design_diffs/`：每组相对父项的 RTL/文件列表差异，便于独立审查。
- `reports/server_driver_reuse.json`：公共 VCS/SAIF/DC 驱动与上一轮已测版本逐字节相同的证据。
- `reports/server_integration.json`：本轮 seed、快速目录克隆和新入口参数分组检查。
- `reports/source_reference.json`：冻结源归档及原始参考文件散列。
- `reports/server_reference_task00.json`：用户提供的上一轮 PPA 摘录，未获得原始报告独立复核。

独立交付包含完整 `study/cases`，无需生成。仓库中 `study` 是可再生目录：

```bash
python3 tools/prepare.py
python3 tools/test_components.py
python3 tools/simulate.py --tasks 12 --jobs 2 --build-jobs 2
python3 tools/check_structure.py
python3 tools/check_server.py
python3 tools/handoff.py --package
```

`prepare.py` 依赖仓库上一轮已提交归档，校验 SHA256，拒绝覆盖现有 case。
组件使用 Icarus；整机使用 Verilator；结构使用 Yosys。所有 12 层输出逐位相等
只验证本整数合同，不能替代官方音频准确率评测。150 MHz 吞吐仅为同频折算。
