import gzip
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'power_vcd.py'
spec = importlib.util.spec_from_file_location('power_vcd', str(MODULE))
power_vcd = importlib.util.module_from_spec(spec)
if MODULE.exists():
    spec.loader.exec_module(power_vcd)

HEADER = '''$date today $end
$comment
  retained metadata
$end
$timescale
  10 ps
$end
$scope module tb_soc $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 1 ! clk_alias $end
$var wire 4 " data [3:0] $end
$var wire 1 # uninitialized $end
$upscope $end
$upscope $end
$enddefinitions $end
'''
BODY = '''#0
$dumpvars
0!
b0010 "
$end
#2
1!
#3
$dumpoff
x!
bx "
x#
$end
#5
$dumpon
0!
b1010 "
$end
#6
1!
b11 "
#8
0!
#10
'''


class PowerVcdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(MODULE.parents[1]))
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.vcd'
        self.source.write_text(HEADER + BODY, encoding='ascii')

    def tearDown(self):
        self.temp.cleanup()

    def export(self, windows, source=None):
        self.assertTrue(hasattr(power_vcd, 'export_windows'), 'export_windows is not implemented')
        return power_vcd.export_windows(source or self.source, windows, self.root / 'out')

    def window(self, start, end, task=0):
        return dict(task=task, start_fs=start * 10000, end_fs=end * 10000)

    def read(self, row):
        return gzip.open(self.root / 'out' / row['file'], 'rt', encoding='ascii').read()

    def test_crop_aliases_unknown_and_exact_end(self):
        rows = self.export([self.window(1, 3)])
        row = rows[0]
        result = self.read(row)
        self.assertTrue(result.startswith(HEADER))
        self.assertIn('#0\n$dumpvars\n0!\nb0010 "\nx#\n$end\n', result)
        self.assertTrue(result.endswith('#1\n1!\n#2\n'))
        self.assertNotIn('x!', result)
        self.assertEqual(row['duration_fs'], 20000)
        self.assertEqual(row['source_timescale_fs'], 10000)
        data = (self.root / 'out' / row['file']).read_bytes()
        self.assertEqual(row['bytes'], len(data))
        self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())

    def test_dumpon_snapshot_seeds_next_window_without_gap_artifacts(self):
        rows = self.export([self.window(0, 3), self.window(5, 8, 1)])
        result = self.read(rows[1])
        self.assertIn('0!\nb1010 "\nx#\n$end', result)
        self.assertIn('#1\n1!\nb0011 "\n#3\n', result)
        self.assertNotIn('dumpoff', result)
        self.assertNotIn('x!', result)

    def test_includes_true_events_at_start_excludes_end(self):
        result = self.read(self.export([self.window(2, 3)])[0])
        self.assertIn('$end\n1!\n#1\n', result)
        self.assertNotIn('x!', result)

    def test_gzip_input_and_twelve_windows(self):
        source = self.root / 'source.vcd.gz'
        with gzip.open(str(source), 'wt', encoding='ascii') as handle:
            handle.write(HEADER + '#0\n0!\n#24\n')
        rows = self.export([self.window(i * 2, i * 2 + 1, i) for i in range(12)], source)
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[-1]['file'], 'task_11.vcd.gz')

    def test_rejects_invalid_windows(self):
        for windows in ([], [self.window(-1, 1)], [self.window(3, 3)],
                        [self.window(1, 3), self.window(2, 4)],
                        [dict(task=0, start_fs=1, end_fs=10000)],
                        [dict(task=0, start_fs=0)], [self.window(8, 11)]):
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                self.export(windows)

    def test_rejects_dump_disabled_inside_window(self):
        for start, end in ((2, 6), (4, 6), (3, 5)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                self.export([self.window(start, end)])

    def test_rejects_malformed_and_truncated_source_even_after_window(self):
        for tail in ('#2\nb10000 "\n#10\n', '#2\nb02 "\n#10\n',
                     '#2\nb101\n', '#2\n$dumpvars\n0!\n',
                     '#2\n1?\n#10\n', '#2\n#1\n#10\n'):
            self.source.write_text(HEADER + '#0\n0!\n' + tail, encoding='ascii')
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                self.export([self.window(0, 1)])

    def test_alias_width_conflict_and_no_timescale_rejected(self):
        for header in (HEADER.replace('1 ! clk_alias', '2 ! clk_alias'),
                       HEADER.replace('$timescale\n  10 ps\n$end\n', '')):
            self.source.write_text(header + BODY, encoding='ascii')
            with self.assertRaises(ValueError):
                self.export([self.window(0, 1)])

    def test_failure_removes_outputs_even_when_bad_data_follows_all_windows(self):
        self.source.write_text(HEADER + '#0\n0!\n#10\nb2 "\n', encoding='ascii')
        with self.assertRaises(ValueError):
            self.export([self.window(0, 1)])
        self.assertEqual(list((self.root / 'out').glob('*.gz')), [])

    def test_metadata_reads_full_gzip_duration_and_rejects_regression(self):
        rows = self.export([self.window(5, 8)])
        self.assertTrue(hasattr(power_vcd, 'read_vcd_metadata'), 'metadata helper missing')
        info = power_vcd.read_vcd_metadata(self.root / 'out' / rows[0]['file'])
        self.assertEqual(info['source_timescale_fs'], 10000)
        self.assertEqual(info['duration_fs'], 30000)
        self.assertEqual(info['start_tick'], 0)
        self.assertEqual(info['end_tick'], 3)
        self.source.write_text(HEADER + '#0\n#9\n#1\n', encoding='ascii')
        with self.assertRaises(ValueError):
            power_vcd.read_vcd_metadata(self.source)

    def test_dumpon_missing_value_becomes_unknown_not_stale(self):
        self.source.write_text(HEADER + '#0\nb1010 "\n#1\n$dumpoff\nbx "\n$end\n'
                               '#2\n$dumpon\n0!\n$end\n#4\n', encoding='ascii')
        result = self.read(self.export([self.window(2, 3)])[0])
        self.assertIn('bxxxx "\n', result)

    def test_rejects_window_before_first_source_marker(self):
        self.source.write_text(HEADER + '#5\n0!\n#10\n', encoding='ascii')
        with self.assertRaises(ValueError):
            self.export([self.window(0, 1)])

    def test_gzip_truncation_is_detected_after_completed_windows(self):
        source = self.root / 'truncated.gz'
        data = gzip.compress((HEADER + '#0\n0!\n#10\n').encode('ascii'))
        source.write_bytes(data[:-4])
        with self.assertRaises(ValueError):
            self.export([self.window(0, 1)], source)

    def test_rejects_nonwhitespace_control_bytes(self):
        self.source.write_bytes((HEADER + '#0\n0!\n\x00#10\n').encode('ascii'))
        with self.assertRaises(ValueError):
            self.export([self.window(0, 1)])

    def test_whitespace_body_and_comments_are_equivalent(self):
        self.source.write_text(HEADER + '#0 $dumpvars 0! b0010 " $end\n'
                               '#1\t$comment ignored #99 text $end 1!\v'
                               '#2\fbx "\r\n#4', encoding='ascii')
        result = self.read(self.export([self.window(0, 3)])[0])
        self.assertIn('#1\n1!\n#2\nbxxxx "\n#3\n', result)

    def test_lf_at_exact_read_boundary_does_not_join_adjacent_values(self):
        prefix = HEADER + '#0\n$comment '
        suffix = ' $end\n0!\n'
        padding = ' ' * (65536 - len(prefix) - len(suffix))
        self.source.write_bytes((prefix + padding + suffix + '1!\n#10\n').encode('ascii'))
        metadata = power_vcd.read_vcd_metadata(self.source)
        self.assertEqual(metadata['duration_fs'], 100000)
        rows = self.export([self.window(0, 1)])
        self.assertIn('0!\n1!\n#1\n', self.read(rows[0]))


class NativePowerVcdTests(PowerVcdTests):
    @classmethod
    def setUpClass(cls):
        compiler = MODULE.parents[3] / '.tools/w64devkit/bin/g++.exe'
        if not compiler.is_file():
            raise unittest.SkipTest('optional native compiler unavailable')
        cls.native_temp = tempfile.TemporaryDirectory(dir=str(MODULE.parents[1]))
        if not hasattr(power_vcd, 'build_native_exporter'):
            raise AssertionError('native backend is not implemented')
        cls.executable = power_vcd.build_native_exporter(compiler, Path(cls.native_temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.native_temp.cleanup()

    def export(self, windows, source=None):
        return power_vcd.export_windows(source or self.source, windows, self.root / 'out',
                                        native_executable=self.executable)

    def test_native_exact_decompressed_equivalence(self):
        windows = [self.window(0, 3), self.window(5, 8, 1)]
        rows = self.export(windows)
        reference_dir = self.root / 'reference'
        reference = power_vcd.export_windows(self.source, windows, reference_dir)
        for actual, expected in zip(rows, reference):
            with gzip.open(str(reference_dir / expected['file']), 'rb') as handle:
                with gzip.open(str(self.root / 'out' / actual['file']), 'rb') as native:
                    self.assertEqual(native.read(), handle.read())


if __name__ == '__main__':
    unittest.main()
