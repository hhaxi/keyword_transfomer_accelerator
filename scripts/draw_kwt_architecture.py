"""Draw the repository's KWT-1 model and accelerator as editable SVG."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)
parts = []


def text(x, y, value, size=22, color='#243449', weight=400, anchor='middle'):
    parts.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>')


def rect(x, y, w, h, fill='#ffffff', stroke='#dbe4ef', rx=16, dash=False):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"' + (' stroke-dasharray="9 7"' if dash else '') + '/>')


def line(points, color='#576b83', dash=False, both=False, arrow=True, width=3):
    parts.append('<polyline points="' + ' '.join(f'{x},{y}' for x, y in points) + f'" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"' + (' stroke-dasharray="8 7"' if dash else '') + (' marker-end="url(#' + ('green' if color == GREEN else 'blue' if color == BLUE else 'arrow') + ')"' if arrow else '') + (' marker-start="url(#' + ('green' if color == GREEN else 'blue' if color == BLUE else 'arrow') + ')"' if both else '') + '/>')


def box(x, y, w, h, title, sub=(), kind='neutral', size=24):
    fill, border, color = {
        'neutral': ('#f5f7fa', '#d7e0ea', '#31445c'),
        'enc': ('#eef5ff', '#91b9f0', '#245da0'),
        'ffn': ('#eaf8f3', '#83c5ad', '#207b5b'),
        'control': ('#f4effc', '#baa3df', '#6b479b'),
        'mem': ('#fff7e9', '#e7c687', '#91651e'),
    }[kind]
    rect(x, y, w, h, fill, border, 13)
    n = 1 + len(sub)
    first = y + h / 2 - (n - 1) * 17 + 8
    text(x + w / 2, first, title, size, color, 650)
    for i, s in enumerate(sub):
        text(x + w / 2, first + 34 * (i + 1), s, 20, color)


def add(x, y, color):
    parts.append(f'<circle cx="{x}" cy="{y}" r="26" fill="white" stroke="{color}" stroke-width="3"/>')
    text(x, y + 9, '+', 35, color, 500)


def section(y, number, title, subtitle):
    rect(60, y, 1880, 58, '#edf2f8', '#edf2f8', 12)
    text(83, y + 38, number + '  ' + title, 27, '#1f3654', 650, 'start')
    text(1915, y + 37, subtitle, 19, '#60758c', 400, 'end')


BLUE = '#3678c5'
GREEN = '#29916e'
parts.append('''<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1940" viewBox="0 0 2000 1940" role="img" aria-labelledby="title desc">
<title id="title">Keyword Transformer（KWT-1）模型与 AI 加速器结构框图</title>
<desc id="desc">依据本项目实际 RTL：12 层单头 PostNorm 编码器，由 ENC1 注意力归一化引擎与 KWT5 FFN 引擎复用执行，经双路 DMA 仲裁器、System Bus 和 512 KiB 共享 SRAM 交接数据。</desc>
<defs>''')
for name, color in [('arrow', '#576b83'), ('blue', BLUE), ('green', GREEN)]:
    parts.append(f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>')
parts.append('</defs><g font-family="Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif">')
rect(0, 0, 2000, 1940, '#ffffff', '#ffffff', 0)
text(65, 73, 'Keyword Transformer', 44, '#172e4c', 700, 'start')
text(65, 118, 'KWT-1 关键词识别 · 模型数据流与 AI 加速器映射', 29, '#526a84', 400, 'start')
rect(1410, 42, 525, 80, '#eef5ff', '#d5e5f9', 15)
text(1672, 76, '12 层  /  1 个注意力头  /  d = 64', 23, '#245da0', 650)
text(1672, 106, '99 tokens  ·  FFN 64 → 256 → 64', 20, '#526a84')

section(156, '01', '模型整体结构', '灰色：软件参考边界    蓝色 / 绿色：硬件编码器')
box(85, 249, 230, 124, '语音输入', ['1 s · 16 kHz', '16,000 个采样点'])
box(360, 249, 230, 124, 'MFCC 特征', ['98 帧 × 40 维', '时间维 token 化'])
box(635, 232, 350, 158, '线性嵌入 40 → 64', ['加入 [CLS] 与位置编码', '98 + 1 = 99 tokens', 'X₀ ∈ ℝ⁹⁹ˣ⁶⁴'])
box(1030, 232, 350, 158, 'Transformer Encoder × 12', ['PostNorm · 层间参数切换', '同一套硬件逐层复用', '各层输入 / 输出：99 × 64'], 'enc', 23)
box(1425, 249, 230, 124, '提取 [CLS]', ['第 0 个 token', '64 维向量'])
box(1700, 249, 215, 124, '分类头', ['Linear 64 → 12', '12 类关键词结果'])
for x1, x2 in [(315, 360), (590, 635), (985, 1030), (1380, 1425), (1655, 1700)]:
    line([(x1, 311), (x2, 311)])

section(430, '02', '单层编码器展开', 'PostNorm：先残差相加，再 LayerNorm；下图展示硬件数值转换')
rect(80, 510, 1840, 256, '#fbfdff', '#c6d9f1', 18)
text(104, 545, 'ENC1 / FRONT  ·  注意力 + 残差 + LN1', 23, '#245da0', 650, 'start')
box(100, 620, 120, 98, 'X', ['99 × 64'], 'enc')
box(270, 620, 220, 98, 'Q / K / V 投影', ['各 99 × 64'], 'enc', 23)
box(535, 620, 180, 98, 'QKᵀ / 8', ['99 × 99'], 'enc')
box(760, 620, 180, 98, 'Softmax', ['逐行归一化'], 'enc')
box(985, 620, 160, 98, 'P × V', ['99 × 64'], 'enc')
box(1190, 620, 180, 98, '输出投影', ['× Wₒ + bₒ'], 'enc')
add(1435, 669, BLUE)
box(1530, 620, 180, 98, 'LayerNorm 1', ['沿 64 维特征'], 'enc', 22)
box(1770, 620, 120, 98, 'Z', ['99 × 64'], 'enc')
for a, b in [(220,270),(490,535),(715,760),(940,985),(1145,1190),(1370,1409),(1461,1530),(1710,1770)]:
    line([(a,669),(b,669)], BLUE)
line([(240,669),(240,577),(1435,577),(1435,643)], BLUE)
text(1000, 568, '残差 1：X', 20, '#245da0')
text(1690, 747, 'P = softmax(QKᵀ / √64)', 18, '#60758c')

rect(80, 790, 1840, 250, '#fcfefc', '#c6e0d5', 18)
text(104, 826, 'KWT5 / FFN  ·  两层线性 + GELU', 23, '#207b5b', 650, 'start')
text(1530, 826, 'ENC1 / TAIL  ·  残差 + LN2', 23, '#245da0', 650)
box(100, 910, 120, 98, 'Z', ['Q16'], 'enc')
box(270, 910, 230, 98, 'FFN 1：64 → 256', ['int16 输入 / 权重'], 'ffn', 22)
box(550, 910, 180, 98, 'GELU', ['512 B 行缓冲'], 'ffn')
box(780, 910, 230, 98, 'FFN 2：256 → 64', ['int40 累加'], 'ffn', 22)
box(1060, 910, 180, 98, '输出重标定', ['int64 → Q16'], 'enc', 22)
add(1435, 959, BLUE)
box(1530, 910, 180, 98, 'LayerNorm 2', ['沿 64 维特征'], 'enc', 22)
box(1770, 910, 120, 98, 'Xₗ₊₁', ['99 × 64'], 'enc')
for a,b in [(220,270),(500,550),(730,780),(1010,1060),(1240,1409),(1461,1530),(1710,1770)]:
    line([(a,959),(b,959)], GREEN if b <= 1060 else BLUE)
text(242, 1030, '量化', 17, '#207b5b')
line([(240,959),(240,866),(1435,866),(1435,933)], BLUE)
text(1000, 857, '残差 2：Z', 20, '#245da0')
line([(1830,718),(1830,779),(64,779),(64,959),(100,959)], BLUE)
text(680, 774, 'Z → FFN；残差 Z 保留在 ENC1 内部', 18, '#526a84')
text(100, 1077, '调度顺序：FRONT → FFN → TAIL，重复 12 层；LN2 输出驻留复用为下一层 X，最后一层写回。', 22, '#435d77', 400, 'start')

section(1110, '03', 'AI 加速器 SoC 结构', '对应顶层：integration/kwt_encoder_soc.sv')
box(90, 1210, 330, 116, 'E203 RISC-V CPU', ['切换层参数 / 下发命令', '轮询状态 / 读取计数器'], 'control')
box(90, 1362, 330, 94, 'Host 加载接口', ['装载输入、固件与参数'], 'neutral')
box(510, 1210, 510, 246, '32-bit System Bus', ['CPU / Host / DMA 三方轮转', 'MMIO 地址译码与响应路由', 'KWT5：0x40000000', 'ENC1：0x40080000'], 'control', 27)
box(1105, 1210, 300, 126, '双路 DMA 仲裁器', ['ENC1 / FFN 轮转', '记录请求与响应归属'], 'control', 23)
box(1500, 1210, 410, 150, '512 KiB 共享 SRAM', ['输入 / 本层权重 / FFN 交接数据', '最终编码器输出', '0xA0000000 – 0xA007FFFF'], 'mem', 26)
line([(420,1268),(510,1268)], both=True)
line([(420,1409),(510,1409)], both=True)
line([(1020,1273),(1105,1273)], both=True)
line([(1020,1425),(1450,1425),(1450,1285),(1500,1285)], both=True)
text(1710, 1402, '经共享 SRAM 完成两个引擎间的数据交接', 18, '#60758c')

rect(485, 1570, 665, 275, '#eef5ff', '#91b9f0', 18)
text(817, 1611, 'ENC1 注意力 / 归一化引擎', 27, '#245da0', 650)
text(817, 1647, 'rtl/kwt_encoder.sv', 19, '#526a84')
text(817, 1688, '4 路共享 32 × 32 乘法器 · 72-bit 累加器', 23, '#245da0')
text(817, 1727, 'Q/K/V/O · QKᵀ · PV · 残差 · LayerNorm', 23, '#245da0')
text(817, 1765, 'Softmax 查表插值 · 整数平方根 / 除法', 23, '#245da0')
text(817, 1804, '内部 SRAM：146.5 KiB · 内置 DMA 主接口', 22, '#245da0')
rect(1210, 1570, 700, 275, '#eaf8f3', '#83c5ad', 18)
text(1560, 1611, 'KWT5 FFN 引擎', 27, '#207b5b', 650)
text(1560, 1647, 'rtl/kwt_dma.sv + rtl/kwt_accel.sv', 19, '#526a84')
text(1560, 1688, '16 路 16 × 16 MAC · 40-bit 累加器', 23, '#207b5b')
text(1560, 1727, 'FFN1 / FFN2 复用 MAC · 1 个 GELU 单元', 23, '#207b5b')
text(1560, 1765, '512 B 行缓冲 · 16 项输出 FIFO · 自主 DMA', 23, '#207b5b')
text(1560, 1804, '内部 SRAM：88.5 KiB · 保留独立 FFN1 模式', 22, '#207b5b')

line([(1200,1336),(1200,1495),(817,1495),(817,1570)], BLUE, both=True)
line([(1320,1336),(1320,1495),(1560,1495),(1560,1570)], GREEN, both=True)
text(1030, 1483, 'ENC1 DMA', 19, '#245da0')
text(1465, 1483, 'FFN DMA', 19, '#207b5b')
line([(600,1456),(600,1527),(525,1527),(525,1570)], '#576b83', dash=True)
line([(600,1527),(1250,1527),(1250,1570)], '#576b83', dash=True)
text(185, 1542, '实线：数据传输', 21, '#526a84')
text(185, 1576, '虚线：MMIO 控制', 21, '#526a84')
text(185, 1640, '硬件复用 12 次', 23, '#243449', 650)
text(185, 1675, '逐层加载权重', 21, '#526a84')
text(185, 1710, 'CPU 负责调度', 21, '#526a84')
text(185, 1745, '算子由引擎执行', 21, '#526a84')

text(65, 1893, '资源口径：内部 SRAM 共 235 KiB（122 个宏）；512 KiB 共享 SRAM 单独统计。推理模式，Dropout 关闭。', 21, '#526a84', 400, 'start')
text(65, 1925, '依据：docs/design/full-encoder.md、实际 RTL 与固定 KWT-1 flags.json；音频前处理、嵌入和分类头属于软件参考边界。', 18, '#718398', 400, 'start')
parts.append('</g></svg>')
svg = '\n'.join(parts)
(OUT / 'keyword-transformer-architecture.svg').write_text(svg, encoding='utf-8')
(OUT / 'keyword-transformer-architecture.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>KWT-1 结构框图</title><style>html,body{margin:0;background:white}svg{display:block;width:2000px;height:1940px}</style>' + svg + '</html>', encoding='utf-8')
print(OUT / 'keyword-transformer-architecture.svg')
