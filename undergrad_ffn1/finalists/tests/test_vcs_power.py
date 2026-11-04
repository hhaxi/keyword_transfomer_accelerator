import argparse
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import power_server as server
import vcs_power as vcs


TB = '''`timescale 1ns/1fs
module tb_soc;
reg clk=0;always begin #3.333333 clk=1; #3.333334 clk=0; end
initial begin
 if($test$plusargs("vcd")) begin
  if($test$plusargs("fst")) $dumpfile("output/soc.fst");
  else $dumpfile("output/soc.vcd");
  $dumpvars(0,tb_soc.dut);$dumpoff;
 end
 $display("POWER_BEGIN task=%0d time_fs=%0.0f cycle=%0d",0,0,0);
 $display("POWER_END task=%0d time_fs=%0.0f cycle=%0d",0,0,0);
 if(lo!==expected[0]) $fatal(1,"mismatch");
end
endmodule
'''


def simulation_log(engine='flat', packed=False):
    mac = 101376 if engine == 'flat' else 51200
    lines = []
    for task in range(12):
        lines += ['POWER_BEGIN task=%d time_fs=%d cycle=0' % (task, task*100+10),
                  'POWER_END task=%d time_fs=%d cycle=1' % (task, task*100+90)]
        for index in range(15):
            value = {4: mac, 9: 11616, 10: 31680 if packed else 50688}.get(index, 0)
            lines.append('SOC_PROFILE task=%d index=%d value=%d' % (task, index, value))
        lines.append('SOC_TASK_PASS task=%d cycles=1 outputs=25344' % task)
    lines.append('SOC_PASS tasks=12 total_cycles=12 nominal_tasks_per_second=1')
    return '\n'.join(lines)


class VCSFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.case = Path(self.temp.name) / 'case'
        self.case.mkdir()
        files = {'rtl/dut.sv': 'module dut; endmodule\n', 'tests/tb_soc_power.sv': TB,
                 'tests/macro_fixtures.sv': '// fixture\n', 'tests/sram_config.vh': '// config\n',
                 'filelists/soc.f': 'rtl/dut.sv\n', 'config/optional.json': '{}',
                 'case.json': '{}', 'output/firmware/kwt.hex': '12345678\n00000013\n'}
        for name, content in files.items():
            path = self.case / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        vectors = {}
        for task in range(12):
            for name in ('x', 'w', 'b', 'expected', 'x_packed', 'w_packed'):
                relative = 'vectors/task_%02d/%s.hex' % (task, name)
                path = self.case / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('00000000\n')
                vectors[relative] = server.sha(path)
        source = {name: server.sha(self.case/name) for name in files if not name.startswith('output/')}
        server.save(self.case/'vcs_seed.json', dict(schema_version=1, source_sha256=source,
                    vector_sha256=vectors, firmware_sha256=server.sha(self.case/'output/firmware/kwt.hex')))
        self.args = argparse.Namespace(vcs=sys.executable, cxx=sys.executable, resume=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_overlay_changes_only_dump_destination_and_preserves_four_state_checks(self):
        overlay = vcs.make_overlay(TB)
        self.assertIn('vcd_path=%s', overlay)
        self.assertIn('!==expected', overlay)
        self.assertIn('`timescale 1ns/1fs', overlay)
        self.assertIn('$dumpvars(0,tb_soc.dut)', overlay)
        self.assertNotIn('initreg', overlay)
        with self.assertRaises(ValueError):
            vcs.make_overlay(TB.replace('1ns/1fs', '1ns/1ps'))

    def test_firmware_words_are_verified_flat_8_hex_lines(self):
        vcs.prepare_case(self.case)
        self.assertEqual((self.case/'output/firmware/size.vh').read_text(), '`define FW_WORDS 2\n')
        original = (self.case/'output/firmware/kwt.hex').read_text()
        (self.case/'output/firmware/kwt.hex').write_text(original+'@00\n')
        seed = server.load(self.case/'vcs_seed.json')
        seed['firmware_sha256'] = server.sha(self.case/'output/firmware/kwt.hex')
        server.save(self.case/'vcs_seed.json', seed)
        with self.assertRaises(ValueError):
            vcs.prepare_case(self.case)

    def test_exact_vcs_compile_and_runtime_flags(self):
        build = self.case/'tmp/build'
        simv = build/'simv'
        command = vcs.compile_command(self.case, build, simv, 'vcs')
        for flag in ('-full64', '-sverilog', '-debug_access+all', '-timescale=1ns/1fs', '+define+DISABLE_SV_ASSERTION',
                     'tests/tb_soc_vcs_power.sv', '-top', 'tb_soc'):
            self.assertIn(flag, command)
        self.assertNotIn('+vcs+dumpvars+all', command)
        runtime = vcs.simulation_command(simv, self.case/'output/activity/run/raw.vcd')
        for flag in ('+tasks=12', '+profile', '+fast_checks', '+host_continuous', '+vcd'):
            self.assertIn(flag, runtime)
        self.assertNotIn('+continuous', runtime)

    def test_all_twelve_outputs_profiles_and_boundaries_required(self):
        windows, profiles = vcs.validate_simulation(simulation_log(), {'engine':'flat', 'packed40':False})
        self.assertEqual(len(windows), 12)
        self.assertEqual(len(profiles), 12)
        for bad in (simulation_log().replace('SOC_PASS tasks=12', 'SOC_PASS tasks=11'),
                    simulation_log().replace('task=0 cycles=1 outputs=25344', 'task=0 cycles=1 outputs=0'),
                    simulation_log().replace('index=9 value=11616', 'index=9 value=0'),
                    simulation_log()+'\nSOC_TASK_PASS task=0 cycles=1 outputs=25344'):
            with self.assertRaises(ValueError):
                vcs.validate_simulation(bad, {'engine':'flat', 'packed40':False})

    def fake_execute(self, command, log, case):
        if '-full64' in command:
            simv = Path(command[command.index('-o')+1])
            simv.write_text('fake VCS simv fixture')
            libraries = Path(str(simv)+'.daidir')
            libraries.mkdir()
            (libraries/'runtime.so').write_text('fake runtime fixture')
            text = 'VCS compile fixture\n'
        else:
            raw = Path(next(v.split('=',1)[1] for v in command if v.startswith('+vcd_path=')))
            raw.write_text('test-only raw VCD fixture')
            text = simulation_log()
        Path(log).write_text(text)
        return text

    def fake_export(self, raw, windows, output, native_executable=None):
        rows = []
        for window in windows:
            path = Path(output)/('task_%02d.vcd.gz'%window['task'])
            with gzip.open(str(path),'wt') as handle:
                handle.write('$timescale 1 fs $end\n#0\n0!\n#80\n1!\n')
            rows.append(dict(task=window['task'], file=path.name, sha256=server.sha(path),
                             bytes=path.stat().st_size, duration_fs=80, source_timescale_fs=1))
        return rows

    def patches(self):
        return (mock.patch.object(vcs,'execute',side_effect=self.fake_execute),
                mock.patch.object(vcs.power_vcd,'build_native_exporter',return_value=Path(sys.executable)),
                mock.patch.object(vcs.power_vcd,'export_windows',side_effect=self.fake_export))

    def test_full_flow_receipt_and_verified_resume(self):
        a,b,c = self.patches()
        with a as execute,b,c:
            result = vcs.simulate_case(self.case,self.args)
            self.assertTrue(result['passed'])
            self.assertEqual(result['simulator'],'VCS')
            self.assertTrue(result['functional_passed'])
            self.assertEqual(execute.call_count,2)
            server.validate_capture(self.case)
            self.args.resume=True
            vcs.simulate_case(self.case,self.args)
            self.assertEqual(execute.call_count,2)
            (self.case/'vectors/task_00/x.hex').write_text('changed')
            with self.assertRaises(ValueError):
                vcs.simulate_case(self.case,self.args)

    def test_no_verilator_receipt_can_resume(self):
        a,b,c = self.patches()
        with a,b,c:
            result=vcs.simulate_case(self.case,self.args)
        result['simulator']='Verilator'
        server.save(self.case/'output/activity/capture.json',result)
        self.args.resume=True
        with self.assertRaises(ValueError):
            vcs.simulate_case(self.case,self.args)

    def test_resume_checks_runtime_libraries_and_timing_evidence(self):
        a,b,c = self.patches()
        with a,b,c:
            result=vcs.simulate_case(self.case,self.args)
        self.args.resume=True
        receipt = self.case/'output/activity/capture.json'
        bad = server.load(receipt)
        bad['tasks'][0]['legacy_cycles'] += 1
        server.save(receipt,bad)
        with self.assertRaisesRegex(ValueError,'timing differs'):
            vcs.simulate_case(self.case,self.args)
        server.save(receipt,result)
        library = Path(str(self.case/result['simv'])+'.daidir')/'runtime.so'
        library.write_text('changed runtime')
        with self.assertRaises(ValueError):
            vcs.simulate_case(self.case,self.args)

    def test_input_changes_during_build_simulation_or_export_fail_closed(self):
        vector=self.case/'vectors/task_00/x.hex'
        original=vector.read_text()
        for phase in ('build','simulation','export'):
            vector.write_text(original)
            def execute(command, log, case):
                text=self.fake_execute(command,log,case)
                if (phase=='build' and '-full64' in command) or (phase=='simulation' and '-full64' not in command):
                    vector.write_text('changed during '+phase)
                return text
            def export(raw,windows,output,native_executable=None):
                rows=self.fake_export(raw,windows,output,native_executable)
                if phase=='export':vector.write_text('changed during export')
                return rows
            with mock.patch.object(vcs,'execute',side_effect=execute), \
                 mock.patch.object(vcs.power_vcd,'build_native_exporter',return_value=Path(sys.executable)), \
                 mock.patch.object(vcs.power_vcd,'export_windows',side_effect=export):
                with self.assertRaises(ValueError):
                    vcs.simulate_case(self.case,self.args)
            self.assertFalse(server.load(self.case/'output/activity/capture.json')['passed'])

    def test_cli_defaults_to_vcs_then_selected_dc_and_sim_can_run_alone(self):
        study=Path(self.temp.name)/'study'
        server.save(study/'activity_manifest.json',dict(cases=[dict(name='one',path='cases/one'),dict(name='two',path='cases/two')]))
        with mock.patch.object(vcs,'simulate_case') as simulate, mock.patch.object(vcs.power_server,'main',return_value=0) as dc:
            self.assertEqual(vcs.main(['--study',str(study),'--case','two']),0)
            self.assertEqual(simulate.call_args[0][0],study/'cases/two')
            self.assertEqual(dc.call_args[0][0],['--study',str(study),'--dc','--collect','--case','two'])
            dc.reset_mock()
            self.assertEqual(vcs.main(['--study',str(study),'--case','one','--sim']),0)
            dc.assert_not_called()

    def test_failed_vcs_invalidates_current_receipt_and_never_exports(self):
        a,b,c = self.patches()
        with a,b,c:
            vcs.simulate_case(self.case,self.args)
        with mock.patch.object(vcs,'execute',side_effect=RuntimeError('VCS failed')):
            with self.assertRaises(RuntimeError):
                vcs.simulate_case(self.case,self.args)
        self.assertFalse(server.load(self.case/'output/activity/capture.json')['passed'])


if __name__=='__main__':
    unittest.main()
