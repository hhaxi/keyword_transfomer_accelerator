"""Four-state gated-clock and component checks; no foundry power claim."""
import subprocess
from pathlib import Path
from prepare import ROOT,sha,save
def main():
 out=ROOT/'tmp/components';out.mkdir(parents=True,exist_ok=True)
 tests=[('clock_gate','tb_clock_gate',[],['rtl/kwt_clock_gate.sv','tests/tb_clock_gate.sv'],'CLOCK_GATE_PASS'),
  ('mac','tb_mac_gated',[],['rtl/kwt_clock_gate.sv','study/cases/fmt1_ref/rtl/kwt_tile_mac.sv','tests/tb_mac_gated.sv'],'MAC_GATED_PASS')]
 for depth in (1,2):
  tests.append(('queue%d'%depth,'tb_group_queue',['-Ptb_group_queue.DEPTH=%d'%depth],
   ['rtl/kwt_clock_gate.sv','study/cases/fmt1_cg_result/rtl/kwt_output_sequence.sv',
    'study/cases/fmt1_cg_result/rtl/kwt_group_queue.sv','tests/tb_group_queue.sv'],'GROUP_QUEUE_PASS'))
 for packed in (0,1):
  tests.append(('formatter%d'%packed,'tb_formatter',['-Ptb_formatter.PACKED40=%d'%packed],
   ['rtl/kwt_clock_gate.sv','study/cases/fmt1_cg_formatter/rtl/kwt_output_formatter.sv','tests/tb_formatter.sv'],'FORMATTER_PASS'))
 results=[]
 for name,top,extra,sources,marker in tests:
  exe=out/(name+'.vvp');log=ROOT/'reports/components'/(name+'.log');log.parent.mkdir(parents=True,exist_ok=True)
  compile_run=subprocess.run(['iverilog','-g2012','-s',top]+extra+['-o',str(exe)]+[str(ROOT/p) for p in sources],capture_output=True,text=True)
  if compile_run.returncode:raise RuntimeError(compile_run.stderr)
  result=subprocess.run(['vvp',str(exe)],capture_output=True,text=True,timeout=90)
  log.write_bytes((compile_run.stderr+result.stdout+result.stderr).encode())
  if result.returncode or marker not in result.stdout:raise RuntimeError(log.read_text())
  results.append(dict(name=name,passed=True,source_sha256={p:sha(ROOT/p) for p in sources},log=log.relative_to(ROOT).as_posix(),log_sha256=sha(log)))
  print(result.stdout,flush=True)
 save(ROOT/'reports/components/results.json',dict(passed=True,tests=results,driver_sha256=sha(__file__)))
if __name__=='__main__':main()
