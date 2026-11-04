"""No DC license required: real fixture validation and Tcl command-order mocks."""
import gzip
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import power_server as power


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def vcd(self, content):
        path = self.root / 'task.vcd.gz'
        with gzip.open(str(path), 'wt') as out:
            out.write(content)
        return path

    def test_vcd_exact_duration_and_noninteger_cycles(self):
        path = self.vcd('$timescale\n1 fs\n$end\n#0\n0!\n#10000000\n1!\n')
        self.assertEqual(power.check_vcd(path, {'duration_fs': 10000000})['duration_fs'], 10000000)
        with self.assertRaises(ValueError):
            power.check_vcd(path, {'duration_fs': 9999999})
        with self.assertRaises(ValueError):
            power.check_vcd(path, {'duration_fs': 10000000, 'source_timescale_fs': 1000})

    def test_vcd_rejects_unrebased_or_backward_time(self):
        for content in ('$timescale 1 ns $end\n#1\n#2\n', '$timescale 1 ns $end\n#0\n#2\n#1\n'):
            with self.assertRaises(ValueError):
                power.check_vcd(self.vcd(content), {'duration_fs': 1000000})

    def test_saif_duration_and_scope(self):
        path = self.root / 'activity.saif'
        path.write_text('(SAIFILE (TIMESCALE 1 ps) (DURATION 100) (INSTANCE tb_soc (INSTANCE dut)))')
        power.check_saif(path, 100000)
        with self.assertRaises(ValueError):
            power.check_saif(path, 100001)
        path.write_text('(SAIFILE (TIMESCALE 1 ps) (DURATION 100) (INSTANCE wrong))')
        with self.assertRaises(ValueError):
            power.check_saif(path, 100000)

    def test_conversion_reuse_binds_converter_vcd_saif_and_duration(self):
        path = self.vcd('$timescale 1 fs $end\n#0\n0!\n#100\n1!\n')
        task = {'task': 0, '_path': str(path), 'sha256': power.sha(path), 'duration_fs': 100}
        calls = []
        def converter(command, log):
            calls.append(command)
            Path(command[-1]).write_text('(SAIFILE (TIMESCALE 1 fs) (DURATION 100) (INSTANCE tb_soc (INSTANCE dut)))')
        with mock.patch.object(power, 'run_logged', converter):
            target = power.convert(task, self.root / 'saif', sys.executable)
            power.convert(task, self.root / 'saif', sys.executable)
            self.assertEqual(len(calls), 1)
            target.write_text('tampered')
            power.convert(task, self.root / 'saif', sys.executable)
            self.assertEqual(len(calls), 2)
            task['duration_fs'] = 101
            with self.assertRaises(ValueError):
                power.convert(task, self.root / 'saif', sys.executable)

    def test_unknown_units_remain_unknown(self):
        parsed = power.parse_power('Total Dynamic Power = 7\nCell Leakage Power = 2\n')
        self.assertIsNone(parsed['total_power_w'])
        parsed = power.parse_power('Total Dynamic Power = 7 mW\nCell Leakage Power = 2 uW\n')
        self.assertAlmostEqual(parsed['total_power_w'], .007002)

    def test_weighted_average_and_mean_energy(self):
        tasks = [dict(task=i, duration_fs=(i+1)*10**15, tool_status='complete', dynamic_power_w=i+1,
                      leakage_power_w=1, total_power_w=i+2) for i in range(12)]
        result = power.aggregate(tasks)
        energy = sum((i+2)*(i+1) for i in range(12))
        self.assertAlmostEqual(result['weighted_total_power_w'], energy / 78)
        self.assertAlmostEqual(result['mean_task_energy_j'], energy / 12)
        self.assertEqual(result['coverage_review'], 'required')
        tasks[0]['leakage_power_w'] = None
        self.assertEqual(power.aggregate(tasks)['data_status'], 'incomplete')
        self.assertIsNone(power.aggregate(tasks)['mean_task_energy_j'])

    def test_aggregate_rejects_nonfinite_duplicate_and_negative_duration(self):
        tasks = [dict(task=i, duration_fs=1000, tool_status='complete', dynamic_power_w=1,
                      leakage_power_w=1, total_power_w=2) for i in range(12)]
        for field, value in [('duration_fs', -1), ('dynamic_power_w', float('inf')),
                             ('dynamic_power_w', float('nan')), ('task', 1)]:
            changed = [dict(t) for t in tasks]
            changed[0][field] = value
            summary = power.aggregate(changed)
            self.assertEqual(summary['data_status'], 'incomplete')
            self.assertIsNone(summary['mean_task_energy_j'])

    def test_manifest_paths_use_study_root_for_objects_and_names(self):
        study = self.root / 'power_study'
        expected = study / 'cases' / 'selected'
        for cases in ([{'name': 'selected', 'path': 'cases/selected'}], ['selected']):
            power.save(study / 'activity_manifest.json', {'cases': cases})
            with mock.patch.object(power, 'analyze_case', return_value=None) as analyze:
                self.assertEqual(power.main(['--study', str(study), '--convert']), 0)
                self.assertEqual(analyze.call_args[0][0], expected.resolve())

    def test_path_and_source_hash_fail_closed(self):
        with self.assertRaises(ValueError):
            power.confined(self.root, '../escape')
        case = self.root
        source = case / 'rtl.sv'
        source.write_text('original')
        receipt = {'source_signature': 'abc', 'config_signature': 'def', 'source_sha256': {'rtl.sv': power.sha(source)},
                   'config_sha256': {'rtl.sv': power.sha(source)}, 'tasks': [],
                   'passed': True, 'functional_passed': True, 'stage': 'complete', 'real_cpu': True,
                   'task_count': 12, 'clock_period_fs': 6666667}
        receipt['source_signature'] = power.signature(receipt['source_sha256'])
        receipt['config_signature'] = power.signature(receipt['config_sha256'])
        power.save(case / 'output/activity/capture.json', receipt)
        source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            power.validate_capture(case)

    def test_capture_requires_complete_qualified_export(self):
        case = self.root
        source = case / 'rtl.sv'
        source.write_text('fixture')
        vcd = self.vcd('$timescale 1 fs $end\n#0\n0!\n#1\n1!\n')
        receipt = dict(passed=True, functional_passed=True, stage='complete', source_signature='src',
                       config_signature='cfg', source_sha256={'rtl.sv': power.sha(source)},
                       real_cpu=True, task_count=12, clock_period_fs=6666667,
                       config_sha256={'rtl.sv': power.sha(source)}, tasks=[
                           dict(task=i, file='../../task.vcd.gz', sha256=power.sha(vcd), start_fs=0,
                                end_fs=1, duration_fs=1, source_timescale_fs=1) for i in range(12)])
        # Put the fixture inside the activity directory, as in the capture ABI.
        activity = case / 'output/activity'
        activity.mkdir(parents=True)
        import shutil
        shutil.copyfile(str(vcd), str(activity / 'task.vcd.gz'))
        vector = case / 'vectors/input.hex'
        vector.parent.mkdir()
        vector.write_text('12345678\n')
        firmware = case / 'output/firmware/kwt.hex'
        firmware.parent.mkdir()
        firmware.write_text('00000013\n')
        receipt['vector_sha256'] = {'vectors/input.hex': power.sha(vector)}
        receipt['firmware_sha256'] = power.sha(firmware)
        for task in receipt['tasks']:
            task['file'] = 'task.vcd.gz'
        target = activity / 'capture.json'
        receipt['source_signature'] = power.signature(receipt['source_sha256'])
        receipt['config_signature'] = power.signature(receipt['config_sha256'])
        power.save(target, receipt)
        self.assertEqual(len(power.validate_capture(case)[1]['tasks']), 12)
        for field, invalid in [('passed', False), ('passed', 1), ('functional_passed', False),
                               ('stage', 'awaiting_verified_export')]:
            bad = dict(receipt)
            bad[field] = invalid
            power.save(target, bad)
            with self.assertRaisesRegex(ValueError, 'complete verified export'):
                power.validate_capture(case)
        for field, invalid in [('real_cpu', False), ('task_count', 11), ('clock_period_fs', 6666666),
                               ('source_signature', 'wrong'), ('config_signature', 'wrong')]:
            bad = dict(receipt)
            bad[field] = invalid
            power.save(target, bad)
            with self.assertRaises(ValueError):
                power.validate_capture(case)
        for field, invalid in [('vector_sha256', {}), ('firmware_sha256', '')]:
            bad = dict(receipt)
            bad[field] = invalid
            power.save(target, bad)
            with self.assertRaises(ValueError):
                power.validate_capture(case)
        power.save(target, receipt)
        vector.write_text('changed vector\n')
        with self.assertRaisesRegex(ValueError, 'vector mismatch'):
            power.validate_capture(case)
        vector.write_text('12345678\n')
        firmware.write_text('changed firmware\n')
        with self.assertRaisesRegex(ValueError, 'firmware mismatch'):
            power.validate_capture(case)

    def test_comparison_csv_markdown_units_and_unknowns(self):
        result = dict(weighted_dynamic_power_w=.002, weighted_leakage_power_w=.001,
                      weighted_total_power_w=.003, mean_task_energy_j=4e-6,
                      strict_mean_cycles_per_task=12.5, strict_throughput_tasks_per_s=100,
                      timing=dict(added_area=10, cell_area=50, setup_wns_ns=-.1))
        power.write_comparison(self.root, {'case': result})
        with open(str(self.root / 'comparison.csv'), newline='') as handle:
            row = list(csv.DictReader(handle))[0]
        self.assertEqual(float(row['Dynamic (mW)']), 2)
        self.assertEqual(float(row['Energy (uJ/task)']), 4)
        self.assertEqual(row['Coverage'], 'required')
        self.assertEqual(row['Hold WNS SS only (ns)'], '')
        self.assertIn('unknown', (self.root / 'comparison.md').read_text())

    def test_library_and_report_binding(self):
        library = self.root / 'test.db'
        library.write_text('fixture')
        (self.root / 'library_signatures.tsv').write_text(power.sha(library) + '\t' + str(library) + '\n')
        power.verify_libraries(self.root)
        library.write_text('changed')
        with self.assertRaises(ValueError):
            power.verify_libraries(self.root)

    def test_explicit_annotation_failure(self):
        folder = self.root / 'report/activity/task_00'
        folder.mkdir(parents=True)
        (folder / 'annotation.rpt').write_text('Error: instance tb_soc/dut not found')
        with self.assertRaisesRegex(ValueError, 'mapping failed'):
            power.collect(self.root, {'tasks': [dict(task=0, duration_fs=100)]})


class TclFlow(unittest.TestCase):
    def mock(self, read_ok=1, available=True):
        try:
            import tkinter
            interp = tkinter.Tcl()
        except (ImportError, RuntimeError) as error:
            self.skipTest('embedded Tcl unavailable: %s' % error)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / 'fixture.db'
            library.write_text('fixture DB only')
            saif = root / 'task.saif'
            saif.write_text('fixture')
            for key, value in {'KWT_POWER_CASE_ROOT': root, 'KWT_POWER_RUN_DIR': root / 'run',
                               'KWT_POWER_TASKS': root / 'tasks.tcl', 'KWT_POWER_PYTHON': sys.executable}.items():
                interp.setvar('env(%s)' % key, str(value))
            interp.setvar('fixture_library', str(library))
            interp.setvar('fixture_saif', str(saif))
            interp.setvar('read_ok', read_ok)
            interp.eval('''
                set events {}
                rename source real_source
                proc fail {message} {error $message}
                proc require_file {path label} {return $path}
                proc resolve_and_validate {} {}
                proc exit {status} {error "MOCK_EXIT:$status"}
                proc redirect {option path script} {
                    set ch [open $path w]; puts $ch "mock report"; close $ch
                    uplevel 1 $script
                }
                proc saif_map {args} {lappend ::events "saif_map $args"; return 1}
                proc reset_switching_activity {} {lappend ::events reset}
                proc read_saif {args} {
                    if {[lsearch -exact $args -auto_map_names]<0 || [lsearch -exact $args tb_soc/dut]<0} {error "bad read_saif"}
                    lappend ::events read; return $::read_ok
                }
                proc report_saif {} {lappend ::events coverage}
                proc report_power {args} {lappend ::events power}
                proc source {path} {
                    switch -- [file tail $path] {
                        common.tcl {}
                        library_config.tcl {
                            set ::synthesis_scope soc; set ::clock_period_ns 6.666667
                            set ::std_db $::fixture_library; set ::required_sram_db_names {}
                        }
                        set_env.tcl {lappend ::events env}
                        read_file.tcl {lappend ::events analyze}
                        set_constraint.tcl {lappend ::events constraints}
                        compile.tcl {lappend ::events compile}
                        write_file.tcl {lappend ::events vectorless}
                        tasks.tcl {
                            set ::power_tasks {}
                            for {set i 0} {$i<12} {incr i} {lappend ::power_tasks [list $i $::fixture_saif]}
                        }
                        default {error "unexpected source $path"}
                    }
                }
            ''')
            if not available:
                interp.eval('rename read_saif {}')
            previous = os.getcwd()
            try:
                with self.assertRaises(tkinter.TclError) as caught:
                    interp.call('real_source', str(power.ROOT / 'script/power_run.tcl'))
            finally:
                os.chdir(previous)
            events = interp.eval('join $events |').split('|')
            return str(caught.exception), events, (root / 'run/dc_complete.ok').is_file()

    def test_success_order_and_all_twelve_tasks(self):
        status, events, marker = self.mock()
        self.assertEqual(status, 'MOCK_EXIT:0')
        self.assertTrue(marker)
        self.assertLess(events.index('saif_map -start'), events.index('analyze'))
        self.assertLess(events.index('compile'), events.index('read'))
        self.assertLess(events.index('vectorless'), events.index('read'))
        self.assertEqual(events.count('reset'), 12)
        self.assertEqual(events.count('read'), 12)
        self.assertEqual(events.count('coverage'), 12)
        for i, event in enumerate(events):
            if event == 'read':
                self.assertEqual(events[i-1], 'reset')

    def test_read_failure_never_reports_power(self):
        status, events, marker = self.mock(read_ok=0)
        self.assertEqual(status, 'MOCK_EXIT:1')
        self.assertFalse(marker)
        self.assertNotIn('power', events)

    def test_unsupported_tool_fails_before_compile(self):
        status, events, marker = self.mock(available=False)
        self.assertEqual(status, 'MOCK_EXIT:1')
        self.assertFalse(marker)
        self.assertNotIn('compile', events)


if __name__ == '__main__':
    unittest.main()
