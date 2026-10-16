"""Verify expanded numeric evidence and publish a compact, replayable report.

This stdlib-only command does not run inference or modify frozen configuration.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory):
    report = json.loads((directory/'report.json').read_text(encoding='utf-8'))
    for name, digest in report['evidence_sha256'].items():
        require(sha((directory/name).read_bytes()) == digest, 'Evidence hash mismatch: '+name)
    for group in ('frozen_files_sha256', 'evaluation_sources_sha256', 'checkpoint_files_sha256'):
        for name, digest in report[group].items():
            require(sha((ROOT/name).read_bytes()) == digest, 'Source/parameter mismatch: '+name)
    names = json.loads((directory/'samples.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in (directory/'samples.jsonl').read_text(encoding='utf-8').splitlines()]
    require(len(rows) == len(names) == report['classification']['samples'], 'Sample count mismatch')
    for i, row in enumerate(rows):
        require(row['index'] == i and row['file'] == names[i], 'Sample ordering mismatch')
        require(len(row['layer_errors']) == len(row['saturation']) == len(row['softmax_cutoff']) == 12, 'Layer count mismatch')
        for key in ('float', 'integer'):
            require(row[key+'_predicted'] == max(range(12), key=lambda j: row[key+'_logits'][j]), 'Prediction/logit mismatch')
    c = report['classification']
    for key in ('float', 'integer'):
        correct = sum(r[key+'_predicted'] == r['label'] for r in rows)
        require(correct == c[key+'_correct'], 'Classification count mismatch')
        require(math.isclose(correct/len(rows), c[key+'_accuracy']), 'Accuracy mismatch')
        matrix = [[0]*12 for _ in range(12)]
        for r in rows:
            matrix[r['label']][r[key+'_predicted']] += 1
        require(matrix == report[key+'_confusion_matrix'], 'Confusion matrix mismatch')
    differences = [r['index'] for r in rows if r['float_predicted'] != r['integer_predicted']]
    require(differences == [r['index'] for r in report['prediction_differences']], 'Difference list mismatch')
    require(len(differences) == c['prediction_differences'], 'Difference count mismatch')
    drop = 100*(c['float_correct']-c['integer_correct'])/len(rows)
    require(math.isclose(drop, c['accuracy_drop_percentage_points'], abs_tol=1e-12), 'Accuracy drop mismatch')
    require(report['passed'] == (drop <= 2), 'Precision gate mismatch')
    total_saturation = 0
    for li, layer in enumerate(report['layers']):
        values = [r['layer_errors'][li] for r in rows]
        expected = math.sqrt(sum(v['sse'] for v in values)/max(sum(v['reference_energy'] for v in values), 1e-16))
        require(math.isclose(expected, layer['aggregate_nrmse'], rel_tol=1e-12), 'Aggregate NRMSE mismatch')
        require(max(v['max_absolute_error'] for v in values) == layer['max_absolute_error'], 'Maximum error mismatch')
        worst = max(range(len(rows)), key=lambda i: values[i]['nrmse'])
        require(worst == layer['worst_sample']['index'], 'Worst-sample mismatch')
        for stage, entry in layer['saturation'].items():
            width = 256 if stage == 'gelu' else 99 if stage == 'score' else 64
            require(entry['elements'] == len(rows)*99*width, 'Observed element count mismatch')
            for key in ('elements', 'saturated'):
                require(sum(r['saturation'][li][stage][key] for r in rows) == entry[key], 'Saturation aggregation mismatch')
            total_saturation += entry['saturated']
        require(sum(r['softmax_cutoff'][li] for r in rows) == layer['softmax_cutoff_count'], 'Softmax cutoff mismatch')
    require(total_saturation == report['saturation_count'], 'Total saturation mismatch')
    return report, rows


def render(report, stem):
    c = report['classification']
    lines = ['# 冻结数值格式：扩展验证集评估', '',
             '本报告评估冻结整数编码器相对原浮点 KWT-1 的数值误差。输入嵌入和分类头继续使用相同的浮点软件实现；没有训练、调整尺度或修改 RTL。', '',
             '## 数据范围与结果', '',
             '- 划分：`validation`；完整上游索引覆盖：**%s**。' % ('是' if report['covers_upstream_index'] else '否'),
             '- 共 **%d 条记录**，其中 **%d 个不同音频文件**、**%d 个静音条目**；非静音重复条目 %d。' %
             (c['samples'], report['unique_audio_files'], report['silence_entries'], report['duplicate_non_silence_entries']),
             '- 浮点分类：**%d/%d（%.6f%%）**；整数分类：**%d/%d（%.6f%%）**。' %
             (c['float_correct'], c['samples'], 100*c['float_accuracy'], c['integer_correct'], c['samples'], 100*c['integer_accuracy']),
             '- 分类预测差异 **%d**；浮点正确而整数错误 **%d**；浮点错误而整数正确 **%d**；准确率下降 **%.6f 个百分点**。' %
             (c['prediction_differences'], c['regressions'], c['improvements'], c['accuracy_drop_percentage_points']),
             '- 最大逐层聚合 NRMSE：**%.6f%%**；运行时实际裁剪事件 **%d**。' %
             (100*report['max_layer_nrmse'], report['saturation_count']), '',
             '这里的完整划分指上游 12 类评估索引：10 个关键词的验证音频、按上游比例抽样的 unknown 及静音条目，不是把所有非关键词录音全部加入。静音条目使用相同的全零输入，保留上游索引权重，但不能视为独立音频。另列去静音与新增音频结果：', '',
             '| 范围 | 条数 | 浮点正确 | 整数正确 | 预测不同 |', '| --- | ---: | ---: | ---: | ---: |']
    for label, key in [('去除静音', 'non_silence'), ('不在原 120 条清单中的音频', 'newly_added_audio')]:
        a = report[key]
        lines.append('| %s | %d | %d | %d | %d |' % (label, a['samples'], a['float_correct'], a['integer_correct'], a['prediction_differences']))
    lines += ['', '## 逐层误差', '',
              '以每层 LN2 输出为比较点。整数输出先按 Q16 解码，与同一输入的完整浮点网络对应层比较；误差包含前面各层传播。聚合 NRMSE = sqrt(Σ误差² / Σ浮点输出²)，不是单样本 NRMSE 的平均值。', '',
              '| 层（从 0 起） | 聚合 NRMSE | 单样本 P95 NRMSE | 最差单样本 NRMSE | 最大绝对误差 |',
              '| --- | ---: | ---: | ---: | ---: |']
    for layer in report['layers']:
        lines.append('| %d | %.6f%% | %.6f%% | %.6f%% | %.8f |' %
                     (layer['layer'], 100*layer['aggregate_nrmse'], 100*layer['p95_sample_nrmse'],
                      100*layer['worst_sample']['nrmse'], layer['max_absolute_error']))
    lines += ['', '每层最差样本的路径、序号、SSE 和参考能量见 JSON 的 `layers[].worst_sample`；每条样本的全部 12 层误差见压缩 JSONL。', '',
              '## 分类与饱和', '', '| 类别 | 条数 | 浮点正确 | 整数正确 | 预测不同 |', '| --- | ---: | ---: | ---: | ---: |']
    for c in report['per_class']:
        lines.append('| %s | %d | %d | %d | %d |' % (c['label'], c['samples'], c['float_correct'], c['integer_correct'], c['prediction_differences']))
    if report['prediction_differences']:
        lines += ['', '| 序号 | 音频 | 真值 | 浮点 → 整数 | 浮点前两名分差 |', '| --- | --- | --- | --- | ---: |']
        for r in report['prediction_differences']:
            labels = report['labels']
            lines.append('| %d | `%s` | %s | %s → %s | %.8f |' %
                         (r['index'], r['file'], labels[r['label']], labels[r['float_predicted']], labels[r['integer_predicted']], r['float_margin']))
    totals = collections.Counter()
    for layer in report['layers']:
        for stage, v in layer['saturation'].items():
            totals[stage] += v['saturated']
    lines += ['', '| 裁剪位置 | 次数（12 层全部记录合计） |', '| --- | ---: |']
    lines += ['| `%s` | %d |' % (k, v) for k, v in totals.items()]
    lines += ['', '饱和按**裁剪前严格越界**计数，合法最大/最小值不算饱和。包含 Q/K/V、QK 分数、PV、输出投影、两次残差、两次 LN 中心化/仿射、FFN 输入 int16 和 GELU；LN 中心化每个元素计一次。Q16 输入/参数转换越界会直接报错；FFN 的 int40 累加在合法输入范围内不会溢出。', '',
              'FFN 权重/偏置离线量化裁剪事件：**%d**。Softmax 固定截断（分数差 ≥16）共 **%d** 个元素，这是冻结近似的定义，单独记录，不计入整数饱和。' %
              (sum(sum(v.values()) for v in report['parameter_saturation']), sum(v['softmax_cutoff_count'] for v in report['layers'])), '',
              '## 复现与证据', '',
              '```powershell',
              '.venv-model\\Scripts\\python.exe scripts/evaluate_encoder.py --sample-list docs/%s.samples.json --output output/encoder-validation-replay' % stem,
              'python scripts/report_encoder_evaluation.py --evaluation output/encoder-validation-replay --publish output/encoder-validation-replay-summary',
              '```', '',
              '使用未占用的输出目录。首次选择完整上游索引可省略 `--sample-list`；提交的清单固定音频及顺序，避免不同系统目录遍历顺序改变 unknown 抽样。', '',
              '- [聚合 JSON](%s.json)：逐层误差、最差样本、混淆矩阵、分类差异、格式/权重/脚本 SHA-256。' % stem,
              '- [样本清单](%s.samples.json)：可直接用于重新评估。' % stem,
              '- [逐样本明细（gzip JSONL）](%s.samples.jsonl.gz)：音频 SHA-256、全部层误差、饱和与 Softmax 截断、浮点/整数 logits、分类分差。' % stem, '',
              '冻结的三个格式 JSON 及三个原整数算术文件在运行前后 SHA-256 一致。统计器使用私有模型实例，首条样本全部 12 层中间结果与原整数模型逐位核对；发布前再次校验逐样本文件与汇总计数。', '',
              '这是扩大后的**软件数值验证**，不是扩大 RTL 仿真或官方 600 条测试集验收。既有硬件回归仍为 12 条 RTL 整机输入、1 条通用网表输入；本轮未改动 RTL。浮点环境延续 TensorFlow 2.4.0 本地开发环境，正式平台等价性待官方环境验证。', '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evaluation', type=Path, required=True)
    p.add_argument('--publish', type=Path, required=True, help='Destination filename prefix (without extension)')
    a = p.parse_args()
    report, rows = verify(a.evaluation)
    prefix = a.publish
    prefix.parent.mkdir(parents=True, exist_ok=True)
    raw = (a.evaluation/'samples.jsonl').read_bytes()
    compressed = gzip.compress(raw, mtime=0)
    # Git normalizes tracked JSON to LF. Hash and publish those exact bytes,
    # while preserving the original per-sample stream inside binary gzip.
    manifest = (a.evaluation/'samples.json').read_bytes().replace(b'\r\n', b'\n')
    report['published_samples_gzip_sha256'] = sha(compressed)
    report['published_samples_manifest_sha256'] = sha(manifest)
    Path(str(prefix)+'.samples.jsonl.gz').write_bytes(compressed)
    Path(str(prefix)+'.samples.json').write_bytes(manifest)
    Path(str(prefix)+'.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    Path(str(prefix)+'.md').write_text(render(report, prefix.name), encoding='utf-8')
    print('Verified and published %d records: %s' % (len(rows), prefix))


if __name__ == '__main__':
    main()
