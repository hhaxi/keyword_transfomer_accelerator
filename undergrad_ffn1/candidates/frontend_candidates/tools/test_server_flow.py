"""Run inherited server-driver tests with mocks; does not run VCS or DC."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
source=ROOT.parent/'finalists/tests'
tests=ROOT/'study/tests'
if source.is_dir():
    shutil.copytree(source,tests,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
temp=ROOT/'tmp/server_tests';temp.mkdir(parents=True,exist_ok=True)
env=os.environ.copy();env['TMPDIR']=env['TEMP']=env['TMP']=str(temp)
log=ROOT/'reports/server_tool_tests.log'
with log.open('wb') as f:
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(tests),'-v'],
                          env=env,stdout=f,stderr=subprocess.STDOUT,cwd=ROOT)
if result.returncode:raise RuntimeError(log.read_text(errors='replace')[-5000:])
inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('study/tests','study/tools') for p in (ROOT/folder).rglob('*')
        if p.is_file() and p.suffix in ('.py','.cpp')}
(ROOT/'reports/server_tool_tests.json').write_text(json.dumps(dict(passed=True,
    actual_commercial_tools_run=False,inputs=inputs,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()),indent=2)+'\n')
print(log.read_text(errors='replace')[-900:])
