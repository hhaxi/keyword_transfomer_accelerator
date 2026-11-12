"""Execute the Tcl control flow with mock EDA commands; not a synthesis test."""
from pathlib import Path
import tkinter, unittest
ROOT=Path(__file__).resolve().parents[1]

class DCFlow(unittest.TestCase):
 def test_tcl_configuration_and_source_contract(self):
  t=tkinter.Tcl();calls=[]
  def mock(name,*args):
   calls.append((name,args))
   if name=='analyze':
    files=t.splitlist(args[-1])
    self.assertTrue(all(Path(p).is_file() for p in files))
    self.assertIn((ROOT/'dc/kwt_sram16.sv').as_posix(),files)
    self.assertNotIn((ROOT/'sim/kwt_sram16.sv').as_posix(),files)
    self.assertEqual(len(files),13)
   if name=='redirect':t.eval(args[-1])
   return '1'
  commands='puts set_app_var define_design_lib set_svf analyze elaborate current_design link check_design redirect create_clock get_ports set_clock_uncertainty get_clocks set_clock_transition set_input_delay remove_from_collection all_inputs set_output_delay all_outputs set_load set_false_path set_clock_gating_style compile_ultra report_area report_timing report_constraint report_clock_gating report_reference report_clock read_saif report_saif report_power change_names write write_sdc write_sdf quit'
  for name in commands.split(): t.createcommand(name,lambda *args,n=name:mock(n,*args))
  t.eval('set search_path {}')
  t.call('unset','-nocomplain','env(KWT_DC_STDLIB)','env(KWT_DC_SRAM_DBS)')
  with self.assertRaises(tkinter.TclError):t.call('source',(ROOT/'dc/run.tcl').as_posix())
  tmp=ROOT/'output/tcl-test';tmp.mkdir(parents=True,exist_ok=True)
  library=Path(tmp)/'mock.db';library.write_text('mock; not a technology library')
  t.setvar('env(KWT_DC_STDLIB)',library.as_posix())
  t.setvar('env(KWT_DC_SRAM_DBS)',library.as_posix())
  t.call('source',(ROOT/'dc/run.tcl').as_posix())
  clocks=[args for name,args in calls if name=='create_clock']
  self.assertEqual(len(clocks),1);self.assertIn('6.666667',clocks[0])
  compiles=[args for name,args in calls if name=='compile_ultra']
  self.assertEqual(compiles,[('-no_autoungroup','-gate_clock')])
  self.assertFalse(any(name=='report_power' for name,args in calls))

if __name__=='__main__':unittest.main()
