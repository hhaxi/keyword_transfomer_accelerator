"""Run inherited native VCD tests with the available Linux C++ compiler."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
temp=ROOT/'study/tmp/native_tests';temp.mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(temp)
sys.path.insert(0,str(ROOT/'study/tests'))
import test_power_vcd as tests

def native_setup(cls):
    compiler=shutil.which('g++')
    if not compiler:raise RuntimeError('g++ is required for this explicit native test')
    cls.native_temp=tempfile.TemporaryDirectory(dir=str(temp))
    cls.executable=tests.power_vcd.build_native_exporter(compiler,Path(cls.native_temp.name))

tests.NativePowerVcdTests.setUpClass=classmethod(native_setup)
log=ROOT/'reports/native_exporter_tests.log'
with log.open('w') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(tests.NativePowerVcdTests))
if not result.wasSuccessful() or result.skipped:raise RuntimeError(log.read_text())
(ROOT/'reports/native_exporter_tests.json').write_text(json.dumps(dict(passed=True,tests=result.testsRun,
    log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
    native_source_sha256=hashlib.sha256((ROOT/'study/tools/power_vcd_fast.cpp').read_bytes()).hexdigest()),indent=2)+'\n')
print(log.read_text()[-700:])
