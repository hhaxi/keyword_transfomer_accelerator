import json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import vcs_power as vcs

class PreflightTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.study=Path(self.temp.name)
  (self.study/'activity_manifest.json').write_text(json.dumps(dict(cases=[dict(name='test',path='cases/test')])) )
 def tearDown(self):self.temp.cleanup()
 def test_missing_dc_is_rejected_before_any_simulation(self):
  def tool(value,label):
   if label=='DC':raise ValueError('DC unavailable')
   return str(value)
  with mock.patch.object(vcs,'tool_path',side_effect=tool),mock.patch.object(vcs,'verify_seed'),mock.patch.object(vcs.power_server,'main',return_value=0),mock.patch.object(vcs,'simulate_case') as simulate:
   with self.assertRaisesRegex(ValueError,'DC unavailable'):vcs.main(['--study',str(self.study)])
   simulate.assert_not_called()
 def test_check_only_does_not_start_simulation_or_dc(self):
  self.assertTrue(hasattr(vcs,'check_dc_inputs'),'VCS preflight feature missing')
  with mock.patch.object(vcs,'tool_path',side_effect=lambda value,label:str(value)),mock.patch.object(vcs,'verify_seed'),mock.patch.object(vcs,'check_dc_inputs'),mock.patch.object(vcs,'simulate_case') as simulate,mock.patch.object(vcs.power_server,'main') as dc:
   self.assertEqual(vcs.main(['--study',str(self.study),'--check']),0)
   simulate.assert_not_called();dc.assert_not_called()
 def test_custom_dc_converter_paths_reach_dc_driver(self):
  self.assertTrue(hasattr(vcs,'check_environment'),'VCS preflight feature missing')
  with mock.patch.object(vcs,'check_environment'),mock.patch.object(vcs,'simulate_case'),mock.patch.object(vcs.power_server,'main',return_value=0) as dc:
   self.assertEqual(vcs.main(['--study',str(self.study),'--dc-shell','/eda/dc','--vcd2saif','/eda/convert']),0)
   command=dc.call_args[0][0]
   self.assertIn('/eda/dc',command);self.assertIn('/eda/convert',command)

if __name__=='__main__':unittest.main()
