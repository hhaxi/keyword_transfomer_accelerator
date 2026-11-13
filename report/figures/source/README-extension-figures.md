# 拓展篇绘图源文件

统一配色参考基础篇：蓝色 `#BBD5F1`、绿色 `#C4E3BA`、粉红色 `#E7A8BC`，浅蓝色 `#D9E9F8` 用于数据交接。

| 图号 | 当前绘图源 | PDF |
| --- | --- | --- |
| 7.1 | `7-1.drawio` | `../7-1.pdf` |
| 7.2 | `build_ffn_full.py`、`ffn-full.drawio` | `../ffn-full.pdf` |
| 7.3 | `build_attention.py`、`7-2.drawio` | `../7-2.pdf` |
| 7.4 | `softmax-row.tex` | `../softmax-row.pdf` |
| 8.1 | `build_postnorm.py`、`8-1.drawio` | `../8-1.pdf` |
| 8.2 | `layernorm-row.tex` | `../layernorm-row.pdf` |
| 8.3 | `dual-engine-flow.tex` | `../dual-engine-flow.pdf` |
| 9.1 | `9-1.drawio` | `../9-1.pdf` |
| 9.2 | `layer12-flow.tex` | `../layer12-flow.pdf` |
| 9.3 | `layer-residency.drawio` | `../layer-residency.pdf` |
| 9.4 | `9-2.drawio` | `../9-2.pdf` |

Python 生成脚本在仓库根目录运行，需要 ReportLab。三个 TeX 图使用 XeLaTeX 编译，将产出的 PDF 放回 `report/figures/`。7.4、8.2、8.3、9.2 的当前版本以 TeX 为准，旧同名 drawio 为历史稿。
