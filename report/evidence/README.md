# 形式等价验证摘要来源

`formal-equivalence-summary.txt` 保存用户于 2026-11-11 在本次对话中转发的队友验证输出片段，未重新运行工具。记录日期为收到摘要的日期，不代表工具实际运行日期。

摘要显示 Verification SUCCEEDED，16,025 个比较点通过、0 个失败，另有 60 个时钟门控锁存器列入未比较项。保留 synopsys_auto_setup 和 RTL interpretation 提示，以及原输出末尾的 `1`；末尾 `1` 不作为额外验证结论。

当前尚未收到完整运行日志、Auto Setup Summary、RTL interpretation 详情、工具版本、运行脚本、读入文件/网表清单、库模型和约束、源文件哈希及黑盒设置。参考设计名中的 DMA_BURST1_HOST_BURST0 与报告选定 reference_sleep 配置的对应关系仍需核对，不能仅凭该设计名确认配置一致。

报告将此项记录为已取得的形式等价通过摘要，并与门级动态功能回归、SDF 时序回归、STA hold 收敛和拓展编码器验证分别表述。

## FFN1 服务器 PPA

ffn1-layer04-ppa.txt 收录 2026-11-13 的 Q128 reference_sleep 服务器报告摘要。活动来自从 0 编号的第 4 层，含整机与分层功耗、时序、面积、宏清单和活动覆盖率。

十二组层任务的平均周期和 DMA 阶段计数来自 undergrad_ffn1/q128_reference_sleep/cases/reference_sleep/output/verification/continuous.log。压缩传输字数来自同一案例的 x_transport.json 和 weight_transport.json。

## 紧凑单路 Transformer 综合

`encoder-compact1-ppa.txt` 整理用户提供的 2026-11-19 最新综合摘要。包含工艺与约束、面积范围、宏清单、带符号的时序裕量、最差路径、层次功耗和 SAIF 覆盖率。功耗窗口对应一条输入执行完整 12 层。新增宏面积由新增宏数量与 DC 报告的单宏面积相乘得到。
