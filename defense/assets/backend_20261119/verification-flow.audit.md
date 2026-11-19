# verification-flow visual inventory

Source: Design report §5.1 and Table 5.1, PDF p45

Canvas: 1200 × 270, white. Microsoft YaHei; navy headings, blue/teal structure, restrained amber for unresolved timing.

Native text and geometry keep each label and connection editable. This is an explicitly requested presentation adaptation; report data are preserved, while geometry/typography are enlarged for projection. No illustrated icons or synthetic evidence.

| id | Visible content | Medium | Status |
|---|---|---|---|
| input | 同源输入与十二组参数 | native | accepted |
| float | 浮点参考模型 | native | accepted |
| integer | 整数软件模型 | native | accepted |
| rtl | 真实 E203 + RTL | native | accepted |
| nrmse | NRMSE<br>解码 Y16 对比浮点 | native | accepted |
| bitwise | 逐位一致<br>ACC40 与 SRAM 中 Y16 | native | accepted |
| a | input to float | native | accepted |
| b | input to integer | native | accepted |
| c | input to rtl | native | accepted |
| f | float to nrmse | native | accepted |
| i | integer to bitwise | native | accepted |
| r | rtl to bitwise | native | accepted |

## Export and visual audit

Draw.io Desktop CLI32.7.4 PNG and SVG exports inspected at full size. All listed labels, bars and connectors are visible. Data preserve the cited report values; page typography is a presentation adaptation. Diagram checker passed. Verification flow routing was repaired to avoid node crossings. No unresolved diagram defects remain.
