# 已完成批次：统一面积补丁与PPA统计

此入口用于已经运行完旧版DC批次的服务器。它读取已有DDC，不重新综合。
本机没有服务器上的DDC和工艺库，因此上传包只包含脚本及测试，不包含伪造的PPA结果。
本次只整理已完成的16组SoC；用户已停止单独加速器综合，默认不读取或检查其DDC。

## 安装和一条命令

上传 `undergrad_ffn1_recover_ppa.tar.gz` 到服务器Desktop。保留原来已加载的
Synopsys环境（dc_shell在PATH中），在终端执行：

```bash
cd "$HOME/Desktop"
tar -xzf undergrad_ffn1_recover_ppa.tar.gz
cd undergrad_ffn1
bash run_recover_compare.sh --scope soc
```

以上三类命令在默认csh/tcsh下也可以执行，不含Bash的命令替换。脚本自身显式
由Bash运行，兼容Bash 4.2/4.3，不用time_ns，Python入口只依赖3.6+标准库。
不必手动修改16份配置，也不必再单独应用之前的area_fix包。

更新包只覆盖报告相关脚本、工具、文档和测试，不包含RTL、固件、PDK库、
local_config.tcl、run目录、旧结果。运行时会将常量面积补丁同步到根目录之外的
16个case及4个阶段检查点，始终不改experiments/baseline。

## 实际工作过程

1. 按旧 `experiments/results/dc_status.json` 定位每个case/scope实际使用的run。
   原先标为reused的配置沿着原报告来源查找DDC；只有完全没有对应旧记录时才
   使用该case最新run目录。存在记录却不能定位run时明确失败，绝不回退旧结果。
2. 优先读取final DDC，缺失时读取compiled DDC。只有同一份源DDC文件才复用
   恢复报告；不同run即使硬件结构相同，也保留各自的工具测量结果。
3. 以相应case的库路径链接DDC，沿用DDC已有时钟和约束，不调用compile、
   compile_ultra、analyze、elaborate，也不重新source当前SDC约束。
4. 生成新的 `run/<原批次>/report_recovered_<UUID>/`。检查设计、SRAM宏清单和
   分项面积；只对精确名称 **logic_0** / **logic_1** 常量伪单元记零面积。
   真实tie cell或其他缺失面积仍会报错。
5. 逐项打印RECOVER_START/PASS/FAILED/REUSE/RESUME。单组失败不阻止后续组，
   最后仍输出全部配置表；缺失值为空，不会填0或拿旧报告代替。

默认仅SoC的16个配置项，输出16条明细。没有或未完成的accelerator结果不会被
列成缺失/失败，不会重启其综合。SoC本身包含CPU、共享SRAM及加速器，可在同一
份SoC报告中查看新增逻辑/CPU/共享SRAM分项面积。将来需要两个范围时仍可显式
传入 `--scope both`，此时才生成32条case/scope明细。

## 结果文件

都在 `experiments/results/`：

| 文件 | 用途 |
|---|---|
| ppa_comparison.csv / .json | 主表，16行；本次只显示SoC指标 |
| ppa_recovery_long.csv / .json | 本次16行SoC明细，含来源和SHA证据 |
| ppa_summary.md | 可直接阅读的主要PPA表 |
| recovery_status.json | 新恢复状态、DDC/配置/报告/库文件散列；不覆盖原dc_status.json |
| recovery_logs/*.log | 各次dc_shell启动日志 |

主表包括：

- 总cell面积、组合/时序/宏面积、cell数量；SoC新增逻辑/CPU/共享SRAM分项面积；
  加速器本地SRAM容量及原生128/1024/4096宏数量，常量伪单元计数。
- setup WNS、TNS、违例路径数；SS-only hold WNS；约束报告中的违例行数；
  DDC保存的时钟周期、时间/面积单位，以及setup是否满足。
- dynamic、internal、switching、leakage及dynamic+leakage功率，统一换算W。
- 原有通过散列检查的任务周期、150MHz名义吞吐，以及按DDC保存时钟折算的吞吐。
- 同一scope相对其原版基线的面积/功率减少百分比；恢复状态、源DDC、报告路径。

面积保持库定义单位；仅报告明确给出时才标注um^2，不默认假设。时间明确给出
单位后才换算ns。功率来自vectorless估计，不代表ITCM/Host实际任务活动，也
不据此生成任务能量。SS hold不代替快角hold签核。报告恢复成功不等于时序满足。

功耗解析同时支持文字汇总和DC `-hierarchy` 的Switch/Int/Leak/Total表格，只读取
Design对应的顶层行，不再加总其子行。Switch和Int按Dynamic Power Units换算，
Leak按Leakage Power Units换算；动态功耗为Switch+Int。若表格有Total列，
total_power_w保留报告的Total值（单位同Dynamic），calculated_total_power_w
另存动态+漏电之和，两者可能因显示精度而有小差异。

如果上一版只有功耗解析失败，但DC已打印KWT_REPORTS_RECOVERED并正常退出，
更新本补丁后直接执行以下命令即可重建16组SoC表格，不启动DC：

```bash
bash run_recover_compare.sh --scope soc --collect-only
```

此模式会核对原DC成功标记、退出码、DDC/脚本/配置/报告/库文件散列，再重新解析；
不会因为旧recovery_passed=false就重新跑DC。真正的DC失败或散列变化仍会报错。

## 中断、重试和只汇总

再次运行同一命令会核对DDC、报告脚本、配置、报告和库文件散列，跳过仍有效的
恢复；若报告被改动则重新恢复。解析器更新只重新解析，不必再次读取DDC。
分别运行两个scope不会清掉另一scope的恢复记录，但汇总表只展示本次选中的范围。

```bash
bash run_recover_compare.sh --scope soc
# 仅重建表格，不启动DC；要求已有当前有效的恢复记录
bash run_recover_compare.sh --scope soc --collect-only
# 仅列出计划读取的源DDC，不修改文件、不启动DC
bash run_recover_compare.sh --scope soc --dry-run
# 强制重新生成报告（仍不综合）
bash run_recover_compare.sh --scope soc --force
```

旧dc_status.json和原报告保持原样；新脚本不把旧失败记录伪装成原批次成功。
若有失败，先看主表error/launch_log列或对应recovery日志；无需重新运行
run_compare.sh。服务器运行结束后，将ppa_comparison.csv、ppa_recovery_long.json
和ppa_summary.md带回即可继续比较具体数值。
