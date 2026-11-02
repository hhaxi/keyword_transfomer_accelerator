# 服务器批量对照运行

**旧批次已经跑完，需要统一修复面积并统计所有PPA：**使用
`bash run_recover_compare.sh --scope soc`，仅处理已完成的16组SoC，不重新综合。上传补丁及完整说明见
[recover-comparison.md](recover-comparison.md)。原dc_status.json和原报告保留。

## 上传和配置

解压 undergrad_ffn1_sweep.tar.gz 到当前用户的 `$HOME/Desktop`，进入
`$HOME/Desktop/undergrad_ffn1`。加载服务器自己的Synopsys环境，确认
`dc_shell`、`python3`可用。只综合不需要NumPy或本地仿真工具。

DC遍历脚本兼容Python 3.6的标准库接口，日志名使用UUID。如果使用早期上传包
遇到 `AttributeError: module 'time' has no attribute 'time_ns'`，这是遍历器在
启动DC前生成日志名失败。在上传根目录执行以下补丁后重跑即可，无需改RTL或约束：

```bash
sed -i 's/time\.time_ns()/__import__("uuid").uuid4().hex/g' tools/sweep.py
bash run_compare.sh --dc --scope both
```

所有variant的库和约束使用同一配置。服务器差异写在根目录
`config/local_config.tcl`（路径始终使用Tcl的file join），批量工具通过环境变量
传给每个case，不必修改16份。例如：

```tcl
set std_db [file join $env(HOME) Desktop lib S40 S40 smic YOUR_RVT_SS.db]
set sram_root [file join $env(HOME) Desktop lib SRAM_Lib_2025]
set sram_db_128 [file join $sram_root RAMSP128X16 db RAMSP128X16_ss_0p99v_0p99v_125c.db]
set sram_db_1024 [file join $sram_root RAMSP1024X16 db RAMSP1024X16_ss_0p99v_0p99v_125c.db]
set sram_db_4096 [file join $sram_root RAMSP4096X16 db RAMSP4096X16_ss_0p99v_0p99v_125c.db]
```

默认标准单元路径延续原RVT SS目录，可自动查找指定basename。上述std_db只是
覆盖示例，必须换成实际文件。lib→db转换仍由用户事先完成，不进入正式综合脚本。
紧凑X或bias需要128宏。只有使用的宏会加载DB并检查引脚，未使用宏不要求存在。

## 一条命令

```bash
cd "$HOME/Desktop/undergrad_ffn1"
bash run_compare.sh --dc --scope both
```

16种配置由i/h/x/b四个独立开关构成；每个配置测试12层参数，任务为一次FFN1。
两种范围：soc包含CPU、512KiB共享SRAM和128KiB TCM；accelerator只含新增
引擎和接口。默认每个范围综合4种不同硬件，共8次DC，其余模式记录复用来源。
ITCM改变固件运行位置，Host改变仿真加载驱动，两者不改变静态网表；功能周期
必须分别仿真，不能复用。同一硬件的vectorless功耗不代表真实活动相同。

若想每份脚本都独立运行（可能很慢）：

```bash
bash run_compare.sh --dc --scope both --repeat-identical-hardware
```

逐项入口：`dc/00_baseline.tcl`、`01_itcm.tcl`、`02_host.tcl`、`03_small_x.tcl`、
`04_bias.tcl`。在根目录可直接 `dc_shell -f dc/03_small_x.tcl`，使用对应case的
完整源文件。可设置 `KWT_GLOBAL_LOCAL_CONFIG`为根目录覆盖文件的绝对路径，
否则单独入口使用case内默认库配置。批量入口会自动设置该变量。

## 对比结果

- `experiments/results/comparison.csv`、`comparison.json`：每种配置一行，含
  开关、检查点、任务周期、启动等待、Host装载、总线统计、本地容量和各范围PPA。
- `experiments/results/dc_status.json`：每个case/scope的成功状态、是否复用、
  真实报告来源；失败不复用，不填0，也不会悄悄换用旧报告。
- 各case的`run/<时间戳>_<PID>_<范围>/report/`：原始报告，含面积、setup、
  SS-only hold、约束、单位、宏清单和vectorless功耗。
- 编译DDC/SDC在报告检查前保存；报告失败后仍可用该case的
  `recover_reports.sh`恢复，不必重综合。

面积单位以.db/report_units为准。setup slack、约束违规和SS-only hold需要
分别检查；SS最小延时不是快角hold签核。时钟约束保持150MHz等原配置，脚本
完成不等于时序收敛。功耗列明确是vectorless估计，不输出伪装成实测的任务能量。

## 功能验证

### 常量伪单元面积补丁及已有DDC恢复

早期脚本把DC保留名 `**logic_0**` / `**logic_1**` 计入未知面积，可能导致
`area_scope.rpt` 为INCOMPLETE。修复仅将这两个精确匹配的常量连接伪单元计零，
新增constant_pseudo计数；真正的tie cell、SRAM或标准单元仍需实例/库面积。
其他UNKNOWN和空分类仍会失败。修复不改RTL、映射策略、约束或工艺库。

小补丁包 `undergrad_ffn1_area_fix.tar.gz` 以undergrad_ffn1为顶级目录，只覆盖
根目录及16个case/4个检查点的面积报告脚本，并附带回归测试。请在批量入口
停止后应用，避免正在执行的配置指纹与脚本不一致；已完成的DDC不会被删除。

```bash
bash
cd "$HOME/Desktop"
tar -xzf undergrad_ffn1_area_fix.tar.gz
cd undergrad_ffn1
export KWT_GLOBAL_LOCAL_CONFIG="$PWD/config/local_config.tcl"
ddc="$(ls -t "$PWD"/experiments/cases/i0_h0_x0_b0/run/*_soc/netlist/*_compiled.ddc | head -n 1)"
bash experiments/cases/i0_h0_x0_b0/recover_reports.sh "$ddc"
```

恢复入口只read_ddc/link并重新输出报告，不运行compile。结果保存在原run目录
下新的 `report_recovered_*` 中。若仍有非上述伪单元的UNKNOWN_AREA，恢复会继续
报错并保留其他报告。该步骤不会自动把旧批次失败记录改成成功，也不自动复用
旧DDC参与新一轮综合。后续批量入口仍是 `bash run_compare.sh --dc --scope both`。

上传包保留本机全部16模式的12组参数复位/连续运行记录。服务器具备Python+
NumPy、RV32 GCC、Verilator、Make时，可重跑：

```bash
bash run_compare.sh --sim --jobs 2 --resume
# 或者仿真之后立即综合
bash run_compare.sh --all --scope both --jobs 2
```

--resume检查源码/测试工具/向量散列、任务数、开关及两种运行记录。每个配置
独立工作目录，Host两种模式仅在完整源码/固件签名相同时复用构建产物，并由
verify --skip-build复核。复用的是二进制，两个Host时序仍各自运行。

计时从实际Host输入/参数请求开始，到最后结果写响应成功、CPU通知被Host观察。
固件初次装载、CPU启动就绪等待、文件解析及结果核对另计。boot_wait_cycles
含固定500拍稳定等待，不等于纯ITCM复制开销；冷启动时间须另行合计。
12组真实权重配合本地合成输入用于回归，不冒充官方数据/正式平台认证。
