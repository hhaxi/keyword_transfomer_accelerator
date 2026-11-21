# 历史工程归档

旧工程使用带注释的 Git 标签固定。检出对应标签后，按快照内的原 README、文件清单和工具配置复现。快照保留已提交的实验、日志、数据与交付包。

```bash
git fetch origin tag archive/pre-restructure tag archive/fpga-2026-11-19
git worktree add --detach ../kwt-archive-main archive/pre-restructure
git worktree add --detach ../kwt-archive-fpga archive/fpga-2026-11-19
```

| 方案 | 快照内入口 |
| --- | --- |
| 16 路 FFN1 基线、四项优化、16 组合和冻结实验 | [本科 FFN1 工作根](https://github.com/hhaxi/keyword_transfomer_accelerator/tree/38ada51d0857663606e46ae3f45a6e116769bcbe/undergrad_ffn1) |
| Q32/Q64、时钟门控、前端候选和归档 tar.gz | [候选索引](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/38ada51d0857663606e46ae3f45a6e116769bcbe/undergrad_ffn1/candidates/README.md)；封包在各候选目录的 `output/` |
| 早期编码器、独立 FFN 和搬运／调度对照 | [当时的文档索引](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/38ada51d0857663606e46ae3f45a6e116769bcbe/docs/README.md) |
| Z100 早期 40 MHz、七路、双路与实时验证 | [FPGA 验证索引](https://github.com/hhaxi/keyword_transfomer_accelerator/blob/d9b7a03f08f8aa6ecf319d66eabc7e8e52940e1c/docs/fpga-validation/README.md) |
| 早期独立编码器 DC 提取工程 | [`codex/encoder-dc@ffd1d2a`](https://github.com/hhaxi/keyword_transfomer_accelerator/tree/ffd1d2a/encoder_asic) |

本地 `output/` 和 `deliverables/` 中被 Git 忽略的文件以原工作目录为准。随 Git 保存的交付包可从上述快照按原路径读取。
