import argparse,inspect,re,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import vcs_power as vcs
import power_server as power
import test_vcs_power as fixtures

def one_log():
 return '\n'.join(line for line in fixtures.simulation_log().splitlines() if 'task=' not in line or re.search(r'task=0\b',line)).replace('SOC_PASS tasks=12','SOC_PASS tasks=1')

class QuickScreenTests(unittest.TestCase):
 def test_runtime_and_log_use_one_explicit_task(self):
  self.assertIn('task_count',inspect.signature(vcs.simulation_command).parameters)
  self.assertIn('+tasks=1',vcs.simulation_command('simv','trace.vcd',task_count=1))
  windows,profiles=vcs.validate_simulation(one_log(),dict(engine='flat',packed40=False),task_count=1)
  self.assertEqual(len(windows),1);self.assertEqual(set(profiles),{0})
  with self.assertRaises(ValueError):vcs.validate_simulation(one_log(),dict(engine='flat',packed40=False))
 def test_energy_uses_one_and_default_still_requires_twelve(self):
  self.assertIn('expected_count',inspect.signature(power.aggregate).parameters)
  task=dict(task=0,duration_fs=2000000000,tool_status='complete',dynamic_power_w=.006,leakage_power_w=.002,total_power_w=.008)
  self.assertEqual(power.aggregate([task])['data_status'],'incomplete')
  result=power.aggregate([task],expected_count=1)
  self.assertEqual(result['data_status'],'complete');self.assertTrue(result['quick_screen'])
  self.assertAlmostEqual(result['mean_task_energy_j'],.008*2e-6)
  self.assertEqual(power.aggregate([task,task],expected_count=1)['data_status'],'incomplete')
 def test_quick_receipt_validates_and_cannot_resume_as_twelve(self):
  self.assertIn('task_count',inspect.signature(vcs.simulation_command).parameters)
  fixture=fixtures.VCSFlow('test_full_flow_receipt_and_verified_resume');fixture.setUp();self.addCleanup(fixture.tearDown)
  fixture.args.tasks=1
  def execute(command,log,case):
   text=fixture.fake_execute(command,log,case)
   if '-full64' not in command:text=one_log();Path(log).write_text(text)
   return text
  with mock.patch.object(vcs,'execute',side_effect=execute) as run,mock.patch.object(vcs.power_vcd,'build_native_exporter',return_value=Path(sys.executable)),mock.patch.object(vcs.power_vcd,'export_windows',side_effect=fixture.fake_export):
   r=vcs.simulate_case(fixture.case,fixture.args)
   self.assertEqual(r['task_count'],1);self.assertTrue(r['quick_screen']);power.validate_capture(fixture.case)
   fixture.args.resume=True;vcs.simulate_case(fixture.case,fixture.args);self.assertEqual(run.call_count,2)
   fixture.args.tasks=12
   with self.assertRaises(ValueError):vcs.simulate_case(fixture.case,fixture.args)
 def test_clone_excludes_all_old_activity_and_builds(self):
  import importlib.util
  spec=importlib.util.find_spec('quick_screen');self.assertIsNotNone(spec,'quick-screen launcher missing')
  import quick_screen
  fixture=fixtures.VCSFlow('test_full_flow_receipt_and_verified_resume');fixture.setUp();self.addCleanup(fixture.tearDown)
  vcs.prepare_case(fixture.case)
  for n in ('output/activity/old.vcd','tmp/old/simv'):
   p=fixture.case/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('do not copy')
  target=fixture.case.parent/'quick'
  quick_screen.clone_case(fixture.case,target)
  vcs.verify_seed(target)
  self.assertFalse((target/'output/activity').exists());self.assertFalse((target/'tmp').exists())
 def test_collection_and_comparison_label_the_single_sample(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'report/activity/task_00';folder.mkdir(parents=True)
   for n in ('annotation.rpt','coverage.rpt','annotated.ok'):(folder/n).write_text('one task annotated\n')
   (folder/'power.rpt').write_text('Total Dynamic Power = 6 mW\nCell Leakage Power = 2 mW\n')
   r=power.collect(root,dict(task_count=1,clock_period_fs=6666667,tasks=[dict(task=0,duration_fs=2000000000)]))
   self.assertEqual(r['data_status'],'complete');self.assertEqual(r['sample'],'task_00_only')
   self.assertAlmostEqual(r['mean_task_energy_j'],16e-9)
   power.write_comparison(root,{'one':r});self.assertIn('task_00_only',(root/'comparison.md').read_text())

if __name__=='__main__':unittest.main()
