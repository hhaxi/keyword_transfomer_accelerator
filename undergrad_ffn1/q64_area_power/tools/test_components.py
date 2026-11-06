"""Four-state scoreboards for the new fixed-group FIFO and exact-width MAC."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
out=ROOT/'tmp/component';out.mkdir(parents=True,exist_ok=True)
logs=ROOT/'reports/components';logs.mkdir(parents=True,exist_ok=True)
tests=[('mac38','tb_mac38',[],['rtl/kwt_tile_mac.sv','tests/tb_mac38.sv'],'MAC38_PASS')]
for depth in (1,2):
 tests.append(('queue%d'%depth,'tb_group_queue',['-Ptb_group_queue.DEPTH=%d'%depth],
   ['rtl/kwt_output_sequence.sv','rtl/kwt_group_queue.sv','tests/tb_group_queue.sv'],'GROUP_QUEUE_PASS'))
for packed in (0,1):
 tests.append(('formatter%d'%packed,'tb_formatter',['-Ptb_formatter.PACKED40=%d'%packed],
   ['rtl/kwt_output_formatter.sv','tests/tb_formatter.sv'],'FORMATTER_PASS'))
results=[]
for name,top,extra,sources,marker in tests:
 exe=out/(name+'.vvp');log=logs/(name+'.log')
 cmd=['iverilog','-g2012','-s',top]+extra+['-o',str(exe)]+[str(ROOT/p) for p in sources]
 compile_run=subprocess.run(cmd,capture_output=True,text=True)
 if compile_run.returncode:raise RuntimeError(compile_run.stderr)
 result=subprocess.run(['vvp',str(exe)],capture_output=True,text=True,timeout=60)
 log.write_bytes((compile_run.stderr+result.stdout+result.stderr).encode())
 if result.returncode or marker not in result.stdout:raise RuntimeError(log.read_text())
 results.append(dict(name=name,passed=True,source_sha256={p:sha(ROOT/p) for p in sources},
   log=log.relative_to(ROOT).as_posix(),log_sha256=sha(log)))
 print(result.stdout,flush=True)
(logs/'results.json').write_bytes((json.dumps(dict(passed=True,tests=results,driver_sha256=sha(__file__)),indent=2)+'\n').encode())
