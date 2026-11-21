# Z100 FPGA · 55.56 MHz 紧凑单路

目标为 XC7Z035-2FFG900。PL 内的 E203 调度十二层编码器，PS Cortex-A9 提供 TCP 服务和分类头。构建参数 `--mhz 55` 请求 55 MHz，PS 的实际分频约为 55.56 MHz。[报告数据](../../../../docs/results/README.md#fpga-实测)

## 重建硬件和固件

在 `projects/encoder/` 完成[编码器环境](../../README.md)，准备 Vivado/Vitis 2026.1、Ross、7-Zip、Z100 板卡资料盘、ARM 裸机工具链与 lwIP TCP 源码。把下列路径替换为本机安装位置。板卡资料提供 PS DDR/MIO 配置和以太网 BSP。

```powershell
. .\env.ps1
.\encoder.ps1 all
.\integration\z100\prepare_smoke.ps1 -Ethernet -BoardArchive 'D:\vendor\XC7Z035.rar'
python integration/z100/run_ross.py contest --ethernet --compact 1 --mhz 55
Copy-Item output/encoder-design/firmware/encoder.bin output/z100/
python integration/z100/model_data.py
.\integration\z100\build_ethernet.ps1 -Contest -Frequency 55555557 -VendorExample 'output/z100/vendor/ethernet/XC7Z035/36_lwip_echo_server' -ArmRuntime 'D:\toolchains\arm-runtime' -LwipTcpSource 'D:\vendor\lwip213-tcp' -Output output/z100/monitor.elf
```

可通过 `run_ross.py --vivado` 和 `--mcp` 显式传入工具路径。默认输出在 `output/z100/`，包含 `z100-contest-55.bit`、`.xsa`、时序与资源报告、`encoder.bin`、`kwt.bin` 和 `monitor.elf`。ARM 固件的频率参数应与实际 PL 时钟一致。

## 烧录与复测

连接 JTAG 与板卡 PS 网口，并让主机与板卡处于同一网段。下列命令使用示例板卡地址 `192.168.1.11:5001`。

```powershell
.\integration\z100\program.ps1 -Image contest-55 -Firmware monitor
python integration/z100/verify_board.py --port 192.168.1.11:5001 --output output/z100/retest-frozen.json
python integration/z100/verify_board.py --port 192.168.1.11:5001 --validation --output output/z100/retest-validation.json
python integration/z100/benchmark.py --port 192.168.1.11:5001 --all-validation --new-connection --output output/z100/retest-desktop.json
python integration/z100/benchmark.py --port 192.168.1.11:5001 --passes 10 --output output/z100/retest-throughput.json
```

第一项回读核对 12 条向量的完整 Q16 输出。新建连接的时延与单连接连续吞吐各自写入结果文件。历史 40 MHz、七路和双路配置的记录见[归档索引](../../../../docs/archive.md)。
