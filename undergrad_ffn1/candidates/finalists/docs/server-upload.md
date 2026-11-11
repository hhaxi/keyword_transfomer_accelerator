# 独立服务器上传包

本包包含四组候选的 RTL、真实 E203 及其许可证、SRAM功能仿真模型、12层向量、固定固件镜像、
VCS/DC 脚本和对比工具。无需依赖原工程目录，也不需要上传本地生成的VCD。

## 上传哪些文件

使用分卷时，整体上传 `upload_parts/` 目录，保留以下结构：

```text
upload_parts/
  README.md
  restore.sh
  restore_power.py
  delivery.json
  SHA256SUMS
  sources/
    parts.json
    archive.part0001
    archive.part0002 ...
```

每卷不超过8MiB。不要只上传 `.sh` 或 `.tcl`，它们还依赖包中的源码、固件和向量。
也可以单独上传完整的 `ffn1_vcs_server.tar.gz`，直接解压后进入 `activity_power_ffn1`。
完整压缩包和分卷任选一种即可。

## 服务器执行

把目录放到当前用户 Desktop 下的新目录中。先加载服务器已有的 Synopsys 工具环境与许可证，
再进入上传的 `upload_parts/` 目录执行：

```bash
bash restore.sh
cd activity_power_ffn1
bash run_vcs_power.sh --check
bash run_vcs_power.sh
```

默认 shell 是 csh/tcsh 时，也直接使用以上 `bash 脚本名` 命令。
还原会核验分卷和完整文件散列；正式入口按四组顺序完成 VCS 仿真、功能验证、VCD导出、
SAIF转换、新SoC综合及指标汇总。

需要 Python3.6+、VCS、g++、vcd2saif、DC。固件已提供，不需要服务器 RISC-V GCC。
标准单元及 RAMSP128/1024/4096X16 的SS db仍使用 `$HOME/Desktop/lib` 下的现有库。
包内不含工艺库；正式综合脚本不做 lib→db 转换。

`--check` 检查完整请求链的可执行工具和源码/固件/向量/DC入口；不启动商业工具、不检验许可证或加载db。
工具未加入PATH时可指定：

```bash
bash run_vcs_power.sh --vcs /实际路径/vcs --cxx /实际路径/g++ --vcd2saif /实际路径/vcd2saif --dc-shell /实际路径/dc_shell
```

## 查看结果和重试

主对比表为 `vcs_power_study/server/comparison.md`，同时保存CSV/JSON，列出面积、周期、吞吐、
动态/漏电/总功耗、能量/任务和setup/SS hold WNS。原始日志和每任务功耗/覆盖率报告保留。
完整说明见 `docs/vcs-power.md`。

```bash
bash run_vcs_power.sh --sim       # 只做VCS采集
bash run_vcs_power.sh --dc        # 用已通过检查的VCS活动重新综合
bash run_vcs_power.sh --resume    # 复用仍匹配的VCS采集，再重新综合
```

本机已检查包的独立还原、源码/固件/向量完整性及工具流程测试。
实际 VCS/DC 命令、许可证和工艺库模型仍需由服务器执行验证，活动覆盖率需审核。
