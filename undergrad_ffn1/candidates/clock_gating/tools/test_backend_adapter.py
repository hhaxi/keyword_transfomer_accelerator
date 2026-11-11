"""Exercise real Tcl adapter with mocked library API and compile generated wiring."""
import subprocess,tkinter
from prepare import ROOT,save,sha
def main():
 work=ROOT/'tmp/adapter_test';work.mkdir(parents=True,exist_ok=True)
 for folder in ('config','generated','report'):(work/folder).mkdir(exist_ok=True)
 t=tkinter.Tcl()
 for name,value in [('backend_root',work),('run_dir',work),('rpt_path',work/'report')]:t.setvar(name,value.as_posix())
 t.call('source',(ROOT/'tests/icg_adapter_mock.tcl').as_posix())
 t.call('source',(ROOT/'backend/clock_gating.tcl').as_posix())
 tests=[]
 def ok(name,script):t.eval(script);tests.append(dict(name=name,passed=True))
 def fails(name,script,expected):
  try:t.eval(script)
  except tkinter.TclError as e:
   if expected not in str(e):raise
   tests.append(dict(name=name,passed=True));return
  raise AssertionError('Expected failure: '+name)
 ok('reference_needs_no_icg','mock_expected 0;kwt_cg_prepare;kwt_cg_validate reference')
 fails('missing_library_fails','mock_expected 4;kwt_cg_prepare','No compatible')
 ok('minimum_area_compatible_selection','''
 mock_cell std/ICG_BIG latch_posedge_precontrol 12
 mock_cell std/ICG_SMALL latch_posedge_precontrol 8
 mock_cell std/WRONG_EDGE latch_negedge 1
 mock_cell std/DISABLED latch_posedge_precontrol 2
 set attrs(std/DISABLED,dont_use) true
 kwt_cg_prepare
 if {[dict get $kwt_cg_selected cell] ne "std/ICG_SMALL"} {error "wrong cell"}
 ''')
 header=work/'generated/kwt_icg_instance.vh'
 if header.read_text().strip()!='ICG_SMALL u_icg(.CK(clk), .E(en), .Q(gclk), .TE(test_en));':
  raise AssertionError(header.read_text())
 ok('explicit_cell_override','set env(KWT_ICG_LIB_CELL) ICG_BIG;kwt_cg_prepare;if {[dict get $kwt_cg_selected cell] ne "std/ICG_BIG"} {error wrong}')
 fails('invalid_override_fails','set env(KWT_ICG_LIB_CELL) UNKNOWN;kwt_cg_prepare','No compatible')
 ok('unknown_extra_pin_rejected','''
 unset env(KWT_ICG_LIB_CELL)
 set attrs(std/ICG_SMALL/UNSUPPORTED,direction) input
 kwt_cg_prepare
 if {[dict get $kwt_cg_selected cell] ne "std/ICG_BIG"} {error "unsupported pin accepted"}
 unset attrs(std/ICG_SMALL/UNSUPPORTED,direction)
 kwt_cg_prepare
 ''')
 fails('wrapper_count_fails','kwt_cg_validate before','wrapper count mismatch')
 ok('four_mapped_wrappers','''
 set wrapper_names {g0 g1 g2 g3}
 foreach name $wrapper_names {set attrs($name/u_icg,ref_name) ICG_SMALL}
 kwt_cg_validate after
 if {[llength $disabled_names]!=4} {error "gate partitions not preserved"}
 kwt_cg_report
 ''')
 fails('wrong_mapped_cell_fails','set attrs(g2/u_icg,ref_name) FAKE;kwt_cg_validate wrong','Expected mapped ICG missing')
 t.eval('set attrs(g2/u_icg,ref_name) ICG_SMALL')
 # Validate generated HDL port wiring independently of the behavioral branch.
 exe=work/'mapped_gate.vvp'
 compile_result=subprocess.run(['iverilog','-g2012','-DKWT_USE_LIBRARY_ICG','-I'+str(work/'generated'),
  '-s','tb_clock_gate','-o',str(exe),str(ROOT/'rtl/kwt_clock_gate.sv'),str(ROOT/'tests/mock_icg.sv'),str(ROOT/'tests/tb_clock_gate.sv')],capture_output=True,text=True)
 if compile_result.returncode:raise RuntimeError(compile_result.stderr)
 result=subprocess.run(['vvp',str(exe)],capture_output=True,text=True,timeout=30)
 if result.returncode or 'CLOCK_GATE_PASS' not in result.stdout:raise RuntimeError(result.stdout+result.stderr)
 tests.append(dict(name='generated_mapping_hdl_simulation',passed=True))
 log=ROOT/'reports/backend_adapter.log';log.write_bytes((result.stdout+result.stderr).encode())
 inputs=['tools/test_backend_adapter.py','backend/clock_gating.tcl','tests/icg_adapter_mock.tcl','tests/mock_icg.sv','rtl/kwt_clock_gate.sv','tests/tb_clock_gate.sv']
 save(ROOT/'reports/backend_adapter.json',dict(passed=True,tests=tests,inputs={p:sha(ROOT/p) for p in inputs},
  log=log.relative_to(ROOT).as_posix(),log_sha256=sha(log),dc_executed=False,
  note='Tcl and generated HDL tested against mock library API/cell, not foundry .db. Real mapping and PPA remain server work.'))
 print('BACKEND_ADAPTER_TEST_PASS',len(tests),'checks; actual DC/library not executed')
if __name__=='__main__':main()
