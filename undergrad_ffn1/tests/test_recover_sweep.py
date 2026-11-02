"""Saved-report recovery contracts; fixture values are not PDK measurements."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))

def reports(folder,scope='soc'):
    folder.mkdir(parents=True,exist_ok=True)
    data={
        'area.rpt':'Number of cells: 123\nCombinational area: 20\nNoncombinational area: 30\nMacro/Black Box area: 100\nTotal cell area: 150\n',
        'units.rpt':'Time Unit : 1ns\nArea Unit : 1um^2\n',
        'timing_setup.rpt':'Startpoint: in\nEndpoint: reg\nslack (MET) 0.5\nStartpoint: reg\nEndpoint: out\nslack (VIOLATED) -0.2\n',
        'timing_hold_ss_only.rpt':'slack (MET) 0.03\n',
        'qor.rpt':"Timing Path Group 'clk'\nTotal Negative Slack: -1.25\nNo. of Violating Paths: 3\nTiming Path Group 'io'\nTotal Negative Slack: -0.75\nNo. of Violating Paths: 2\n",
        'power_vectorless_NOT_OFFICIAL.rpt':'Cell Internal Power = 1.5 mW\nNet Switching Power = 1 mW\nTotal Dynamic Power = 2.5 mW\nCell Leakage Power = 300 nW\n',
        'constraints.rpt':'max_transition violated (VIOLATED)\n',
        'area_scope.rpt':'status=COMPLETE\nadded leaves=2 area=30 known_area=30 unknown_leaves=0 constant_pseudo_leaves=1\ncpu leaves=2 area=20 known_area=20 unknown_leaves=0 constant_pseudo_leaves=0\nshared leaves=1 area=100 known_area=100 unknown_leaves=0 constant_pseudo_leaves=1\nArea sources: instance=3 library=0 constant_pseudo=2 unavailable=0\n',
        'recovery_metadata.rpt':'scope='+scope+'\nclock=clk\tperiod=6.666667\n',
    }
    for name,value in data.items():(folder/name).write_text(value)

HIERARCHY_POWER='''Design : kwt_ffn1_soc
Dynamic Power Units = 1mW (derived from V,C,T units)
Leakage Power Units = 1uW
                         Switch   Int      Leak      Total
Hierarchy                Power    Power    Power     Power      %
-----------------------------------------------------------------
kwt_ffn1_soc              3.765    6.766     4.16e+03  14.695    100.0
  cpu (e203_cpu_top)      3.051    0.577     758.884   4.386     29.8
    storage (kwt_sram)
                         1.37e-03 4.34e-02 368.620   0.413      2.8
'''

class RecoverSweepTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'tools/recover_sweep.py').exists(),'Missing saved-DDC recovery driver')
        import recover_sweep,ppa_metrics
        self.r=recover_sweep;self.p=ppa_metrics
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def case_run(self,name='i0_h0_x0_b0',scope='soc',stamp='20261102_100000_100'):
        case=self.root/'experiments/cases'/name
        for path in ('script/area_scope.tcl','script/common.tcl','config/library_config.tcl','config/optimization_config.tcl'):
            p=case/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/path).read_bytes())
        run=case/'run'/(stamp+'_'+scope);(run/'netlist').mkdir(parents=True)
        top='kwt_ffn1_soc' if scope=='soc' else 'kwt_ffn1_top'
        (run/'netlist'/(top+'_compiled.ddc')).write_bytes(b'fixture compiled design')
        (run/'netlist'/(top+'.ddc')).write_bytes(b'fixture final design')
        (run/'report').mkdir();(run/'report/run_settings.txt').write_text('synthesis_scope = '+scope+'\n')
        return case,run

    def test_parse_units_worst_slack_and_scope_area(self):
        reports(self.root)
        p=self.p.parse_reports(self.root,'soc')
        self.assertEqual(p['cell_area'],150)
        self.assertEqual(p['added_area'],30)
        self.assertEqual(p['constant_pseudo_count'],2)
        self.assertAlmostEqual(p['setup_wns_ns'],-0.2)
        self.assertEqual(p['setup_tns'],-2)
        self.assertEqual(p['setup_violating_paths'],5)
        self.assertAlmostEqual(p['hold_wns_ss_only_ns'],0.03)
        self.assertAlmostEqual(p['dynamic_power_w'],0.0025)
        self.assertAlmostEqual(p['total_power_w'],0.0025003)
        self.assertFalse(p['setup_meets_target'])
        self.assertEqual(p['constraint_violation_lines'],1)
        self.assertTrue(p['key_metrics_complete'])

    def test_dc_hierarchy_power_top_row_mixed_units_and_rounding(self):
        reports(self.root)
        (self.root/'power_vectorless_NOT_OFFICIAL.rpt').write_text(HIERARCHY_POWER)
        p=self.p.parse_reports(self.root,'soc')
        self.assertAlmostEqual(p['switching_power_w'],0.003765)
        self.assertAlmostEqual(p['internal_power_w'],0.006766)
        self.assertAlmostEqual(p['dynamic_power_w'],0.010531)
        self.assertAlmostEqual(p['leakage_power_w'],0.004160)
        self.assertAlmostEqual(p['total_power_w'],0.014695)
        self.assertAlmostEqual(p['calculated_total_power_w'],0.014691)
        self.assertTrue(p['key_metrics_complete'])

    def test_hierarchy_power_never_sums_children_or_guesses_missing_units(self):
        reports(self.root)
        path=self.root/'power_vectorless_NOT_OFFICIAL.rpt'
        path.write_text(HIERARCHY_POWER.replace('Leakage Power Units = 1uW',''))
        p=self.p.parse_reports(self.root,'soc')
        self.assertAlmostEqual(p['dynamic_power_w'],0.010531)
        self.assertIsNone(p['leakage_power_w'])
        path.write_text(HIERARCHY_POWER.replace('Design : kwt_ffn1_soc','Design : missing_top'))
        self.assertIsNone(self.p.parse_reports(self.root,'soc')['dynamic_power_w'])

    def test_unitless_power_uses_explicit_unit_declaration(self):
        reports(self.root)
        (self.root/'power_vectorless_NOT_OFFICIAL.rpt').write_text('Dynamic Power Units = 1mW\nLeakage Power Units = 1nW\nTotal Dynamic Power = 2.5\nCell Leakage Power = 300\n')
        p=self.p.parse_reports(self.root,'soc')
        self.assertAlmostEqual(p['dynamic_power_w'],0.0025)
        self.assertAlmostEqual(p['leakage_power_w'],3e-7)
        (self.root/'power_vectorless_NOT_OFFICIAL.rpt').write_text('Total Dynamic Power = 2.5\n')
        self.assertIsNone(self.p.parse_reports(self.root,'soc')['dynamic_power_w'])

    def test_missing_metrics_and_unknown_area_are_not_zero(self):
        p=self.p.parse_reports(self.root,'soc')
        self.assertIsNone(p['cell_area']);self.assertIsNone(p['setup_meets_target'])
        reports(self.root)
        (self.root/'area_scope.rpt').write_text('status=INCOMPLETE\nadded leaves=2 area=UNKNOWN known_area=10 unknown_leaves=1\n')
        p=self.p.parse_reports(self.root,'soc')
        self.assertIsNone(p['added_area']);self.assertFalse(p['area_scope_complete'])

    def test_dc_unit_spellings_and_pico_second_conversion(self):
        reports(self.root)
        (self.root/'units.rpt').write_text('Time_unit : 1.0ps\nArea_unit : 1um^2\n')
        p=self.p.parse_reports(self.root,'soc')
        self.assertAlmostEqual(p['setup_wns_ns'],-0.0002)
        (self.root/'units.rpt').write_text('Time Units = 1ns\n')
        self.assertAlmostEqual(self.p.parse_reports(self.root,'soc')['setup_wns_ns'],-0.2)

    def test_rounded_negative_zero_still_fails_timing(self):
        reports(self.root)
        (self.root/'timing_setup.rpt').write_text('slack (VIOLATED) -0.00\n')
        self.assertFalse(self.p.parse_reports(self.root,'soc')['setup_meets_target'])

    def test_hold_qor_is_not_added_to_setup_totals(self):
        reports(self.root)
        with (self.root/'qor.rpt').open('a') as output:
            output.write('Hold Timing\nTotal Negative Slack: -99\nNo. of Violating Paths: 200\n')
        p=self.p.parse_reports(self.root,'soc')
        self.assertEqual(p['setup_tns'],-2)
        self.assertEqual(p['setup_violating_paths'],5)

    def test_latest_failed_directory_does_not_fall_back_to_older_ddc(self):
        case,old=self.case_run()
        newer=case/'run/20261102_110000_200_soc';newer.mkdir()
        with self.assertRaisesRegex(ValueError,'DDC'):
            self.r.select_source(self.root,'i0_h0_x0_b0','soc',[])

    def test_failed_launch_before_run_creation_never_selects_old_design(self):
        self.case_run()
        status=[dict(case='i0_h0_x0_b0',scope='soc',passed=False)]
        with self.assertRaisesRegex(ValueError,'recorded run'):
            self.r.select_source(self.root,'i0_h0_x0_b0','soc',status)

    def test_recorded_run_and_reused_source_take_precedence(self):
        case,old=self.case_run()
        self.case_run(stamp='20261102_110000_200')
        relative=(old/'report').relative_to(self.root).as_posix()
        status=[dict(case='i1_h1_x0_b0',scope='soc',reused=True,report_relative=relative)]
        s=self.r.select_source(self.root,'i1_h1_x0_b0','soc',status)
        self.assertEqual(s['source_case'],'i0_h0_x0_b0')
        self.assertEqual(s['run_dir'],old)
        self.assertEqual(s['ddc'].name,'kwt_ffn1_soc.ddc')
        status[0]['case']='i1_h1_x1_b0'
        with self.assertRaisesRegex(ValueError,'hardware'):
            self.r.select_source(self.root,'i1_h1_x1_b0','soc',status)

    def test_launch_failure_selects_exact_run(self):
        case,old=self.case_run();self.case_run(stamp='20261102_110000_200')
        log=self.root/'experiments/results/launch.log';log.parent.mkdir()
        log.write_text('Writing file /old/server/experiments/cases/i0_h0_x0_b0/run/'+old.name+'/netlist/kwt_ffn1_soc.ddc\nKWT: area scope incomplete\n')
        s=self.r.select_source(self.root,'i0_h0_x0_b0','soc',[dict(case='i0_h0_x0_b0',scope='soc',passed=False,launch_log='experiments/results/launch.log')])
        self.assertEqual(s['run_dir'],old)

    def test_record_paths_cannot_escape_workspace(self):
        bad=[dict(case='i0_h0_x0_b0',scope='soc',report_relative='../outside/report')]
        with self.assertRaises(ValueError):self.r.select_source(self.root,'i0_h0_x0_b0','soc',bad)

    def install_scripts(self):
        for path in ('script/area_scope.tcl','script/recover_reports.tcl'):
            p=self.root/path;p.parent.mkdir(exist_ok=True);p.write_bytes((ROOT/path).read_bytes())

    def test_failed_case_isolated_original_status_preserved_and_no_compile(self):
        self.install_scripts()
        for name in ('i0_h0_x0_b0','i0_h0_x1_b0'):self.case_run(name)
        out=self.root/'experiments/results';out.mkdir(parents=True)
        report='experiments/cases/i0_h0_x0_b0/run/20261102_100000_100_soc/report'
        original=json.dumps([dict(case='i0_h0_x0_b0',scope='soc',passed=False,report_relative=report)])+'\n'
        (out/'dc_status.json').write_text(original)
        calls=[]
        def tool(args,cwd,env,stdout,stderr):
            calls.append(env['KWT_RECOVER_DDC'])
            self.assertEqual(args[0],'dc_shell')
            self.assertTrue(args[-1].endswith('recover_reports.tcl'))
            folder=Path(env['KWT_RECOVER_REPORT_DIR']);reports(folder)
            if 'i0_h0_x1_b0' in str(cwd):return SimpleNamespace(returncode=1)
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        items=[i for i in self.r.matrix_cases() if i['name'] in ('i0_h0_x0_b0','i0_h0_x1_b0')]
        result=self.r.recover_all(self.root,('soc',),runner=tool,items=items)
        self.assertEqual(len(calls),2)
        self.assertTrue(result[0]['recovery_passed']);self.assertFalse(result[1]['recovery_passed'])
        self.assertEqual((out/'dc_status.json').read_text(),original)
        rows=json.loads((out/'ppa_comparison.json').read_text())
        self.assertEqual(len(rows),16)
        self.assertIn('soc_cell_area',rows[0])

    def test_resume_checks_ddc_and_report_hashes(self):
        self.install_scripts();case,run=self.case_run();calls=[]
        def tool(args,cwd,env,stdout,stderr):
            calls.append(1);folder=Path(env['KWT_RECOVER_REPORT_DIR']);reports(folder)
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        items=[self.r.matrix_cases()[0]]
        self.r.recover_all(self.root,('soc',),runner=tool,items=items)
        self.r.recover_all(self.root,('soc',),runner=tool,items=items)
        self.assertEqual(len(calls),1)
        (run/'netlist/kwt_ffn1_soc.ddc').write_bytes(b'changed design fixture')
        self.r.recover_all(self.root,('soc',),runner=tool,items=items)
        self.assertEqual(len(calls),2)

    def test_both_scopes_32_rows_follow_original_reused_ddcs(self):
        self.install_scripts();status=[]
        for item in self.r.matrix_cases():
            name=item['name'];case,run=self.case_run(name)
            status.append(dict(case=name,scope='soc',passed=False,report_relative=(run/'report').relative_to(self.root).as_posix()))
            reference='i0_h0_'+name[-5:]
            if name==reference:base,acc=self.case_run(name,'accelerator')
            else:acc=self.root/'experiments/cases'/reference/'run/20261102_100000_100_accelerator'
            status.append(dict(case=name,scope='accelerator',passed=True,reused=name!=reference,
                               report_relative=(acc/'report').relative_to(self.root).as_posix()))
        out=self.root/'experiments/results';out.mkdir(parents=True);(out/'dc_status.json').write_text(json.dumps(status))
        calls=[]
        def tool(args,cwd,env,stdout,stderr):
            calls.append(env['KWT_RECOVER_DDC']);folder=Path(env['KWT_RECOVER_REPORT_DIR'])
            reports(folder,env['KWT_SYNTHESIS_SCOPE'])
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        result=self.r.recover_all(self.root,('soc','accelerator'),runner=tool)
        self.assertEqual(len(calls),20)
        self.assertEqual(len(result),32)
        self.assertTrue(all(r['recovery_passed'] for r in result))
        self.assertEqual(sum(r['recovery_status']=='reused' for r in result),12)
        rows=json.loads((out/'ppa_comparison.json').read_text())
        self.assertEqual(len(rows),16)
        self.assertTrue(all('soc_cell_area' in r and 'accelerator_cell_area' in r for r in rows))
        self.r.recover_all(self.root,('soc',),runner=tool)
        self.assertEqual(len(calls),20)
        self.assertEqual(len(json.loads((out/'recovery_status.json').read_text())),32)

    def test_soc_only_recovers_16_cases_and_omits_accelerator_scope(self):
        self.install_scripts()
        for item in self.r.matrix_cases():self.case_run(item['name'])
        out=self.root/'experiments/results';out.mkdir(parents=True)
        # Accelerator synthesis was stopped. These records must be ignored.
        (out/'dc_status.json').write_text(json.dumps([
            dict(case=i['name'],scope='accelerator',passed=False,launch_log='absent.log')
            for i in self.r.matrix_cases()]))
        calls=[]
        def tool(args,cwd,env,stdout,stderr):
            self.assertEqual(env['KWT_SYNTHESIS_SCOPE'],'soc')
            calls.append(env['KWT_RECOVER_DDC'])
            folder=Path(env['KWT_RECOVER_REPORT_DIR']);reports(folder,'soc')
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        result=self.r.recover_all(self.root,('soc',),runner=tool)
        self.assertEqual(len(calls),16)
        self.assertTrue(all(r['recovery_passed'] for r in result))
        rows=json.loads((out/'ppa_comparison.json').read_text())
        self.assertEqual(len(rows),16)
        self.assertTrue(all('soc_cell_area' in r and 'accelerator_cell_area' not in r and 'accelerator_recovery_status' not in r for r in rows))
        self.assertNotIn('| accelerator |',(out/'ppa_summary.md').read_text())
        detail=json.loads((out/'ppa_recovery_long.json').read_text())
        self.assertEqual(len(detail),16)
        self.assertTrue(all(r['scope']=='soc' for r in detail))

    def test_cli_defaults_to_soc(self):
        from unittest.mock import patch
        with patch.object(sys,'argv',['recover_sweep.py']),patch.object(self.r,'recover_all',return_value=[{'recovery_passed':True}]) as recovery:
            self.r.main()
        self.assertEqual(recovery.call_args[0][1],('soc',))

    def test_resume_reparses_metrics_and_rejects_changed_reports(self):
        self.install_scripts();case,run=self.case_run();calls=[]
        def tool(args,cwd,env,stdout,stderr):
            calls.append(1);folder=Path(env['KWT_RECOVER_REPORT_DIR']);reports(folder)
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        item=[self.r.matrix_cases()[0]]
        result=self.r.recover_all(self.root,('soc',),runner=tool,items=item)
        from unittest.mock import patch
        old_parser=self.r.parse_reports
        def stricter(folder,scope):
            data=old_parser(folder,scope);data['key_metrics_complete']=False;return data
        with patch.object(self.r,'parse_reports',stricter):
            result=self.r.recover_all(self.root,('soc',),runner=tool,items=item)
        self.assertFalse(result[0]['recovery_passed'])
        result=self.r.recover_all(self.root,('soc',),runner=tool,items=item)
        self.assertEqual(len(calls),1)
        report=self.root/result[0]['report_relative']/'timing_setup.rpt'
        report.write_text('changed\n')
        self.r.recover_all(self.root,('soc',),runner=tool,items=item)
        self.assertEqual(len(calls),2)

    def test_collect_only_repairs_parser_failure_without_invoking_dc(self):
        self.install_scripts();self.case_run();item=[self.r.matrix_cases()[0]]
        def tool(args,cwd,env,stdout,stderr):
            folder=Path(env['KWT_RECOVER_REPORT_DIR']);reports(folder)
            (folder/'power_vectorless_NOT_OFFICIAL.rpt').write_text(HIERARCHY_POWER)
            stdout.write(('KWT_REPORTS_RECOVERED: reports='+str(folder)+'\n').encode())
            return SimpleNamespace(returncode=0)
        self.r.recover_all(self.root,('soc',),runner=tool,items=item)
        path=self.root/'experiments/results/recovery_status.json'
        old=json.loads(path.read_text());old[0].update(recovery_passed=False,recovery_status='failed',error='Old parser did not recognize hierarchy table',dynamic_power_w=None,leakage_power_w=None)
        path.write_text(json.dumps(old))
        def forbidden(*args,**kwargs):self.fail('collect-only must not invoke dc_shell')
        result=self.r.recover_all(self.root,('soc',),runner=forbidden,items=item,collect_only=True)
        self.assertTrue(result[0]['recovery_passed'])
        self.assertAlmostEqual(result[0]['dynamic_power_w'],0.010531)
        self.assertNotIn('error',result[0])
        old=json.loads(path.read_text());old[0].update(tool_returncode=1,recovery_passed=False)
        path.write_text(json.dumps(old))
        rejected=self.r.recover_all(self.root,('soc',),runner=forbidden,items=item,collect_only=True)
        self.assertFalse(rejected[0]['recovery_passed'])

if __name__=='__main__':unittest.main()
