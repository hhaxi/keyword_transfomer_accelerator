# Z100 XC7Z035 上板验证

Windows 上位机从 Speech Commands V2 验证集读取 WAV，或从默认麦克风录制一秒语音。上位机运行冻结 KWT‑1 的 MFCC 和嵌入，PL 在 25 MHz 执行 12 层定点编码器，ARM 执行分类头。PL 的 FFN1 来自本科生工程，GELU 和 FFN2 保持主工程的定点计算。

## 下载与演示

以下命令从仓库根目录运行。JTAG 和底板的 **PS_UART** 各用一根 USB 线。演示默认 COM8、921600 8N1。独立寄存器联调版使用 115200 8N1。

```powershell
uv pip install --python .venv-model/Scripts/python.exe pyserial==3.5 sounddevice==0.4.7 pillow==10.4.0
.\integration\z100\program.ps1 -Image kwt-25 -Firmware z100-kwt-25-921600
.\.venv-model\Scripts\python.exe integration/z100/demo.py --port COM8
```

`program.ps1` 把权重包经 JTAG 下载到 DDR。若使用 SD 版固件，把 `output/z100/kwt.bin` 放在 FAT 格式 SD 卡根目录，执行 `program.ps1 -Image kwt-25 -Firmware z100-kwt-25-sd -ModelSource sd`，上位机使用 `--baud 115200`。

如果现场需要独立验证 PL，可装载诊断固件并从上位机选择 JTAG。串口版和诊断版使用同一个 FPGA 镜像、相同模型参数和 ARM 推理函数。

```powershell
.\integration\z100\program.ps1 -Image kwt-25 -Firmware z100-kwt-25-jtag
.\.venv-model\Scripts\python.exe integration/z100/demo.py --port JTAG
```

界面展示 12 层进度、输出标签和 Top‑3 softmax 分数。板上耗时包含 ARM 的逐层参数准备、PL 编码器和 ARM 分类头。端到端耗时从选定 WAV 或开始录音计起，包含本机预处理和数据传输。

在左侧选择快捷样本，或从顶部验证样本下拉列表切换文件，会立即发起识别。也可打开本地 WAV 或录音。本地 WAV 的前一秒会转为 16 kHz 单声道，短音频补静音。验证集文件显示真值标签。输入音频支持试听和再次识别，历史记录页可导出本次窗口内成功完成的识别，CSV 包含标签、各项耗时、PL 时钟和连接地址。直接启动默认使用板卡以太网地址，串口演示可指定 `--port COM8`。

## 重建产物

```powershell
.\integration\z100\prepare_smoke.ps1
python integration/z100/run_ross.py smoke
python integration/z100/run_ross.py kwt --mhz 25
.\integration\z100\build_firmware.ps1 -Image kwt-25 -Baud 921600
.\integration\z100\build_firmware.ps1 -Image kwt-25 -JtagVerify
.\.venv-model\Scripts\python.exe integration/z100/model_data.py
```

Ross 使用本机的 Vivado MCP 原生 stdio 方式启动，`--mcp` 和 `--vivado` 可指定安装路径。板卡 DDR 和 MIO 配置由资料盘的 `1_hello_world` 和 `14_micro_sd_rw` 示例提取。生成的 FPGA 工程、报告、模型参数、ELF、bitstream 和 XSA 位于 `output/z100`。

SD 版使用 `build_firmware.ps1 -Image kwt-25 -FatFsInclude <bspinclude/include> -BspLibraries <库路径数组>`。库数组包含板卡 SD 示例的 `libxilffs.a`、`libxil.a`，以及 Cortex‑A9 的 softfp `libc.a`、`libnosys.a` 和 `libgcc.a`。

## 40 MHz 以太网版本

将 Z100 的 PS 网口接入主机，在同一网段使用 `192.168.1.11:5001`。直连测试用的 Windows 有线口地址为 `192.168.1.2/24`。TCP 版使用工程 XSA 中的 PS 初始化，其中 HP0 配置为 32 位，供 PL 访问 DDR。上位机沿用同一输入特征、CRC32、12 层进度和结果格式。

```powershell
.\integration\z100\prepare_smoke.ps1 -Ethernet
python integration/z100/run_ross.py kwt --mhz 40 --ethernet
.\integration\z100\build_ethernet.ps1 -VendorExample output/z100/vendor/ethernet/XC7Z035/36_lwip_echo_server -ArmRuntime output/z100/arm-runtime/extracted/usr -Output output/z100/z100-kwt-40-tcp.elf -DirectModel
.\integration\z100\program.ps1 -Image kwt-40 -Firmware z100-kwt-40-tcp
.\.venv-model\Scripts\python.exe integration/z100/demo.py --port 192.168.1.11:5001
```

`-ArmRuntime` 指向 Ubuntu WSL 中 ARM 裸机 GNU 工具链和 newlib 的解包目录，包含 `bin/arm-none-eabi-ld`、`include/newlib`、`lib/arm-none-eabi/newlib` 和 `lib/gcc/arm-none-eabi`。固件链接资料盘以太网例程的 Xilinx standalone BSP 和 lwIP。Vivado 可加 `--parallel-projection` 启用 K 维 4 路并行的 Q/K/V/O 投影。对照实验可用 `--build` 指定独立输出目录，并将 `vendor/ps_profile_ethernet.tcl` 放到该目录下。

DDR 直接读取参数包，ARM 每层更新参数基址。LN1 到 FFN、FFN 到 LN2 使用 PL 的 BRAM 交接缓冲，外部 DDR 顺序读取使用突发传输。FFN1、GELU 和 FFN2 复用原模块。

延迟测试可在独立构建目录中启用 `--parallel-attention --parallel-ffn`。前者为 QK 和 PV 启用 16 路乘法以及分组存储，保持相同的累加、舍入和饱和规则。后者将 99 行分到 7 路原 FFN 核并广播参数，尾路仅写回最后 3 个有效行。两项均为可选构建参数，固件继续使用相同的 MMIO、数据布局和网络协议。

```powershell
.\.venv-model\Scripts\python.exe integration/z100/verify_board.py --port 192.168.1.11:5001
.\.venv-model\Scripts\python.exe integration/z100/verify_board.py --port 192.168.1.11:5001 --validation
.\.venv-model\Scripts\python.exe integration/z100/benchmark.py --port 192.168.1.11:5001 --output output/z100/latency/tcp-benchmark.json
```

基准测试使用固定验证列表中前 12 条 WAV，先预热一次，在已建立的连接上从读取 WAV 计时到收到识别结果。录音入口另有一秒采集时间。

### 加宽编码器与片上流接口

`--wide-encoder` 启用每周期 16 个 K 元素的 Q/K/V/O 投影、每周期 32 项的注意力乘法，以及流水化 Softmax 和 LayerNorm。`--parallel-ffn --stream-handoff` 让本科生 FFN1 的各行通道在注意力计算期间预加载权重。LN1 的打包值和 FFN2 的有符号 40 位结果通过片上握手传输。构建配套以太网固件时，同时使用 `-DirectModel -StreamHandoff`。

`--held-gelu` 将 FFN1 输出保持两拍再送到 FFN2，`held_gelu.xdc` 只约束该数据寄存器至 FFN2 激活 BRAM 的多周期路径。若为该版指定 `--mhz 66`，Zynq 的 PS 时钟配置生成约 66.667 MHz 的 FCLK。固件的 `-Frequency` 要使用 XCI 中 `PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ` 对应的 Hz 值。

已上板的 66.7 MHz 版本、Vivado 工程重建、TCP 固件构建和验收记录见 [FPGA 功能验证报告](../../docs/fpga-validation/README.md)。

## 验收入口

```powershell
.\integration\z100\program.ps1 -Image smoke
python integration/z100/smoke_serial.py --port COM8
.\.venv-model\Scripts\python.exe integration/z100/prepare_ffn_traces.py
python integration/z100/run_ross.py sim
```

运行完整固件时，`verify_board.py` 默认通过串口核对 12 条冻结输入的全部最终整数输出。追加 `--validation` 运行仓库固定的 120 条验证样本。用诊断固件时，先加 `--prepare-jtag` 生成输入目录，再通过 XSDB 执行 `run_jtag_verify.tcl <输入目录>`，最后加 `--check-jtag` 检查回读并生成 JSON 报告。`--validation` 的三步均须带同一选项。

如果重建时缺少固定 120 条验证样本的软件参考，可运行以下命令。

```powershell
.\.venv-model\Scripts\python.exe scripts/evaluate_encoder.py --sample-list model/validation-samples.json --output output/encoder-validation-expanded-legacy120
```
