"""Four-state scoreboard for exact words/indices, stalls, clear and bad groups."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'tmp/formatter';out.mkdir(parents=True,exist_ok=True)
logs=ROOT/'reports/formatter';logs.mkdir(parents=True,exist_ok=True)
results=[]
for packed in (0,1):
    exe=out/('p%d.vvp'%packed)
    command=['iverilog','-g2012','-s','tb_formatter','-Ptb_formatter.PACKED40=%d'%packed,
             '-o',str(exe),str(ROOT/'rtl/kwt_output_formatter.sv'),str(ROOT/'tests/tb_formatter.sv')]
    subprocess.run(command,check=True,capture_output=True)
    run=subprocess.run(['vvp',str(exe)],capture_output=True,text=True,timeout=60)
    log=logs/('p%d.log'%packed);log.write_text(run.stdout+run.stderr)
    if run.returncode or 'FORMATTER_PASS packed=%d'%packed not in run.stdout:
        raise RuntimeError(log.read_text())
    print(run.stdout,flush=True)
    results.append(dict(passed=True,packed40=bool(packed),log=log.relative_to(ROOT).as_posix(),
                        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (ROOT/'rtl/kwt_output_formatter.sv',ROOT/'tests/tb_formatter.sv',Path(__file__))}
(logs/'results.json').write_text(json.dumps(dict(passed=True,inputs=inputs,tests=results),indent=2)+'\n')
