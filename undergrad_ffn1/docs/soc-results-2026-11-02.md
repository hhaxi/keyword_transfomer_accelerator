# FFN1 优化结果（2026-11-02）

已实施：ITCM取指、连续Host加载、小X行双缓冲、bias缩容。保持16个MAC及
INT16 X/W、INT32 bias、INT40累加、INT64传输。中断/WFI、packed40、PE阵列、
增加MAC及改变量化仍为候选。

| 累加配置 | 每任务周期 | 加速器SRAM宏容量 |
|---|---:|---:|
| 原版 | 167134 | 52 KiB |
| +ITCM | 152827 | 52 KiB |
| +连续Host | 131922 | 52 KiB |
| +小X双缓冲 | 128317 | 37 KiB |
| +bias缩容 | 128317 | 34 KiB |

16种组合均完成12组参数的复位、连续验证，共384任务，每任务25344项输出与
整数模型一致。测试用真实12层W1/b1和合成输入，不是官方完整音频评测。模式对比
见experiments/results/comparison.csv；历史证据见verification/及verification/matrix/。
全开任务周期减少23.2%，按150MHz折算约1169 task/s（原版约897）。任务是一次
99x64乘64x256加bias的FFN1，包含装载、等待、写回，冷启动另计。折算频率不
等于时序已收敛。

## 服务器SoC观察

下表转录自用户提供的16组汇总截图，按四种硬件归并；不是服务器原始CSV或
签核报告，保留截图显示精度。面积单位以库为准。每行对应i/h的四种组合；
i=ITCM、h=连续Host，两者不改变静态网表。

| 小X | 小bias | SoC cell面积 | 新增面积 | setup WNS(ns) | SS hold WNS(ns) | 动态(mW) | 漏电(mW) |
|---|---|---:|---:|---:|---:|---:|---:|
| 关 | 关 | 2.50803e6 | 269752 | 0 | -0.16 | 10.531 | 4.16 |
| 关 | 开 | 2.50049e6 | 262203 | 0 | -0.16 | 10.533 | 4.15 |
| 开 | 关 | 2.46427e6 | 225961 | 0 | -0.15 | 10.297 | 4.09 |
| 开 | 开 | 2.45533e6 | 218147 | 0 | -0.13 | 10.783 | 4.08 |

全开新增面积约减少19.1%，整机约减少2.1%。动态功耗估计没有随容量同步下降，
x1_b0保留为对照。功耗是vectorless，不代表真实任务活动或实测能量。setup显示0
没有体现正裕量；SS hold仍为负，需核对最差路径/接口预算并完成快角及物理验证。
服务器原始DDC/报告未下载到本机，不上传Git。统一面积/功耗解析与恢复操作见
docs/recover-comparison.md；已有报告使用 `--scope soc --collect-only` 重建表，不启动DC。

## 从Git复现

Git保留当前源码、冻结基线、模型/向量和验证证据，忽略工具、工艺库、私有配置、
编译缓存、上传包、服务器run及可生成的case/checkpoint副本。基线保持原始字节
以维持SHA；仅私有本机工具配置不进入版本控制。

在undergrad_ffn1目录运行：

```bash
python3 tools/sweep.py prepare
# 配置自己的config/local_config.tcl，然后运行DC：
bash run_compare.sh --dc --scope soc
# 或具备仿真工具后重做16组合验证和打包：
bash run_compare.sh --sim --jobs 2
python3 tools/verify.py --tasks 12
python3 tools/verify.py --tasks 12 --continuous --skip-build
python3 tools/check_components.py
python3 tools/check_structure.py
for case_name in i0_h0_x0_b0 i0_h0_x0_b1 i0_h0_x1_b0 i0_h0_x1_b1; do
  (cd "experiments/cases/$case_name" && python3 tools/check_components.py && python3 tools/check_structure.py) || exit 1
done
python3 tools/package.py
```

prepare生成16个完整case和5个阶段DC入口。历史中间快照仅在本地上传包保留；
Git统一DC入口使用生成case。run_dc.sh可直接综合当前全开版本，不必先prepare。
verification/matrix保留历史case证据，其中相对路径以原生成case为基准；
optimization_matrix.json记录当时本机完整验收，不代表新checkout无需重验即可打包。
