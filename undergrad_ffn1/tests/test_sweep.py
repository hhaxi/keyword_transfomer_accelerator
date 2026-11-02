"""Comparison contract: complete combinations, honest unknowns, no failed reuse."""
import importlib.util,json,sys,tempfile,unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
class SweepTest(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(parents=True,exist_ok=True)
        path=ROOT/'tools/sweep.py'
        self.assertTrue(path.exists(),'Missing exhaustive comparison runner')
        spec=importlib.util.spec_from_file_location('sweep',path)
        self.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.s)
    def test_all_combinations_and_unique_hardware(self):
        cases=self.s.cases()
        self.assertEqual(len(cases),16)
        self.assertEqual(len({c['name'] for c in cases}),16)
        self.assertEqual(len({c['hardware_key'] for c in cases}),4)
        self.assertEqual(sum(not any(c['options'].values()) for c in cases),1)
        self.assertEqual(sum(all(c['options'].values()) for c in cases),1)
    def test_unknown_is_not_zero(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            r=self.s.report_metrics(Path(p))
            self.assertIsNone(r['cell_area'])
            self.assertIsNone(r['setup_slack'])
            self.assertIsNone(r['dynamic_power_w'])
    def test_missing_build_falls_back_to_compilation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            self.assertFalse(self.s.reuse_build(Path(p)/'source',Path(p)/'target'))
    def test_missing_vectors_fail_before_simulation(self):
        from verify import vector_signature
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            with self.assertRaisesRegex(AssertionError,'Missing/unexpected test vectors'):
                vector_signature(Path(p))
    def test_failed_current_run_overrides_old_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            root=Path(p);out=root/'experiments/results';out.mkdir(parents=True)
            (out/'simulation_status.json').write_text(json.dumps([dict(case='i0_h0_x0_b0',passed=False)]))
            old=dict(passed=True,tasks=12,task_cycles=[123]*12,throughput_at_150MHz=1)
            with patch.object(self.s,'ROOT',root),patch.object(self.s,'valid_simulation',lambda c,l:old if c.name=='i0_h0_x0_b0' else None):
                self.s.collect()
            row=json.loads((out/'comparison.json').read_text())[0]
            self.assertFalse(row['reset_tasks_passed']);self.assertNotIn('reset_tasks_cycles',row)
    def test_stale_dc_is_not_reported_as_current(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            root=Path(p);out=root/'experiments/results';out.mkdir(parents=True)
            (out/'dc_status.json').write_text(json.dumps([dict(case='i0_h0_x0_b0',scope='soc',passed=True,cell_area=10,hardware_sha256='old')]))
            with patch.object(self.s,'ROOT',root),patch.object(self.s,'hardware_digest',lambda c,s:'new'):
                self.s.collect()
            row=json.loads((out/'comparison.json').read_text())[0]
            self.assertFalse(row['dc_soc_passed']);self.assertTrue(row['dc_soc_stale'])
            self.assertNotIn('dc_soc_cell_area',row)
    def test_materialized_case_closure(self):
        if not (ROOT/'experiments/matrix.json').exists() or not (ROOT/'experiments/cases').exists():self.skipTest('Run tools/sweep.py prepare to materialize generated cases')
        for item in self.s.cases():
            case=ROOT/'experiments/cases'/item['name']
            self.assertEqual(json.loads((case/'checkpoint.json').read_text())['options'],item['options'])
            self.assertEqual(len(list((case/'vectors').rglob('*.hex'))),72)
            for scope in ('soc','accelerator'):
                for line in (case/f'filelists/{scope}.f').read_text().splitlines():
                    self.assertTrue((case/line).is_file(),str(case/line))
    def test_parse_standard_reports(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as p:
            p=Path(p)
            (p/'area.rpt').write_text('Total cell area: 1234.5\n')
            (p/'timing_setup.rpt').write_text('slack (VIOLATED) -0.123\n')
            (p/'power_vectorless_NOT_OFFICIAL.rpt').write_text('Total Dynamic Power = 2.5 mW\nCell Leakage Power = 300 nW\n')
            r=self.s.report_metrics(p)
            self.assertEqual(r['cell_area'],1234.5)
            self.assertEqual(r['setup_slack'],-0.123)
            self.assertAlmostEqual(r['dynamic_power_w'],0.0025)
            self.assertAlmostEqual(r['leakage_power_w'],3e-7)
    def test_dc_reuse_with_legacy_clock_is_saved_for_every_case_and_scope(self):
        # Only test orchestration with a synthetic tool result; never claim PDK mapping.
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root=Path(folder)
            for item in self.s.cases():(root/'experiments/cases'/item['name']).mkdir(parents=True)
            calls=[]
            def fake_run(args,cwd,env,stdout,stderr):
                calls.append((cwd.name,env['KWT_SYNTHESIS_SCOPE']))
                run=cwd/'run'/env['KWT_SYNTHESIS_SCOPE'];report=run/'report';report.mkdir(parents=True)
                (report/'area.rpt').write_text('Total cell area: 100\n')
                (report/'timing_setup.rpt').write_text('slack (MET) 0.5\n')
                stdout.write(('KWT_DC_COMPLETED: '+str(run)+'\n').encode())
                return SimpleNamespace(returncode=0)
            # Python 3.6 has time.time(), but no time.time_ns().
            legacy_clock=SimpleNamespace(time=lambda:1700000000.0)
            with patch.object(self.s,'time',legacy_clock,create=True),patch.object(self.s,'ROOT',root),patch.object(self.s,'hardware_digest',lambda c,s:c.name[-5:]),patch.object(self.s.subprocess,'run',fake_run):
                self.s.dc_run(('soc','accelerator'),False)
            records=json.loads((root/'experiments/results/dc_status.json').read_text())
            self.assertEqual(len(calls),8)
            self.assertEqual(len(records),32)
            self.assertTrue(all(r['passed'] for r in records))
if __name__=='__main__':unittest.main()
