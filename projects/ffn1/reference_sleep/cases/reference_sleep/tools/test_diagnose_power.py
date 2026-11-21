"""Meaningful local safety/SAIF tests for the saved-run diagnostics helper."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).with_name("diagnose_power.py")


class DiagnosticsTests(unittest.TestCase):
    def module(self):
        self.assertTrue(TOOL.is_file(), "saved-run diagnostics helper is missing")
        spec = importlib.util.spec_from_file_location("diagnose_power", str(TOOL))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_help_is_usable_without_dc(self):
        result = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--replay", result.stdout)

    def test_tcl_paths_are_literal(self):
        import tkinter
        tool = self.module()
        interpreter = tkinter.Tcl()
        value = 'path with spaces/[exit 99]/$env(HOME)/"quoted"/a\\b'
        interpreter.eval("set diagnostic_path " + tool.tcl_string(value))
        self.assertEqual(interpreter.getvar("diagnostic_path"), value)

    def test_saif_reports_direct_clock_and_cen_activity(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "task.saif"
            source.write_text('''(SAIFILE (TIMESCALE 1 ns) (DURATION 100)
              (INSTANCE tb_soc (INSTANCE dut (NET (clk (T0 50) (T1 50) (TX 0) (TC 20)))
              (INSTANCE local_sram (NET (macro_clk (T0 90) (T1 10) (TX 0) (TC 4))
                (cen (T0 20) (T1 80) (TX 0) (TC 2)))
                (INSTANCE u_macro (PORT (CLK (T0 90) (T1 10) (TX 0) (TC 4))
                  (CEN (T0 20) (T1 80) (TX 0) (TC 2))))))))''')
            result = tool.inspect_saif(source)
            self.assertEqual(result["duration_ns"], 100)
            rows = {row["path"]: row for row in result["signals"]}
            clk = rows["tb_soc/dut/local_sram/u_macro/CLK"]
            self.assertAlmostEqual(clk["toggles_per_ns"], .04)
            self.assertEqual(clk["TC"], 4)
            self.assertEqual(rows["tb_soc/dut/local_sram/u_macro/CEN"]["T0"], 20)
            self.assertEqual(clk["evidence"], "present_in_raw_saif_not_proof_of_dc_mapping")

    def test_saif_truncation_fails(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.saif"
            source.write_text('(SAIFILE (DURATION 10) (INSTANCE dut (NET (clk (TC 2)))')
            with self.assertRaisesRegex(ValueError, "unbalanced"):
                tool.inspect_saif(source)

    def test_prepare_preserves_saved_evidence_and_allocates_unique_output(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "saved"
            for name in ("netlist", "report", "sdc"):
                (run / name).mkdir(parents=True)
            (run / "netlist/kwt_ffn1_soc.ddc").write_bytes(b"original ddc")
            (run / "sdc/kwt_ffn1_soc.sdc").write_bytes(b"original sdc")
            library = root / "original.db"
            library.write_bytes(b"original library")
            (run / "report/run_settings.txt").write_text("std_db = " + str(library) + "\ntop_design = kwt_ffn1_soc\n")
            (run / "report/sram_inventory.rpt").write_text("RAMSP128X16 count=0\n")
            original = {str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()}
            first = tool.main(["--run", str(run), "--output-root", str(root / "diagnostics")])
            second = tool.main(["--run", str(run), "--output-root", str(root / "diagnostics")])
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            self.assertEqual(len(list((root / "diagnostics").iterdir())), 2)
            self.assertEqual(original, {str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()})


    def test_mapped_leaf_loads_and_unavailable_reports_are_explicit(self):
        import tkinter
        interpreter = tkinter.Tcl()
        interpreter.eval(r'''
            proc foreach_in_collection {variable collection body} {
                foreach item $collection { uplevel 1 [list set $variable $item]; uplevel 1 $body }
            }
            proc get_nets {args} { return net_clk }
            proc get_object_name {object} { return $object }
            proc all_connected {args} { return {port_clk pin0 pin1} }
            proc get_attribute {object attribute} {
                if {$attribute eq "object_class"} { return [expr {$object eq "port_clk" ? "port" : "pin"}] }
                if {$attribute eq "direction"} { return in }
                if {$attribute eq "fanout"} { return 128 }
                if {$attribute eq "total_capacitance"} { return 3.5 }
                error "attribute unsupported: $attribute"
            }
            proc redirect {args} {
                set file [lindex $args 1]
                set out [open $file w]; puts $out "mock command report"; close $out
                uplevel 1 [lindex $args end]
            }
            proc report_net {args} { return 1 }
        ''')
        interpreter.eval('source ' + self.module().tcl_string(TOOL.parents[1] / 'script/power_diagnostics.tcl'))
        with tempfile.TemporaryDirectory(dir=str(TOOL.parent)) as folder:
            interpreter.call('kwt_diag::start', Path(folder).as_posix(), 'mock_mapped')
            interpreter.call('kwt_diag::net_loads')
            interpreter.eval('kwt_diag::report missing.rpt {command_not_installed}')
            interpreter.call('kwt_diag::finish')
            import csv
            with (Path(folder) / 'mapped_net_loads.tsv').open() as source:
                rows = list(csv.DictReader(source, delimiter='\t'))
            self.assertEqual(rows[0]['leaf_input_pin_loads'], '2')
            self.assertEqual(rows[0]['leaf_drivers'], '1')
            self.assertEqual(rows[0]['fanout_attribute'], '128')
            self.assertEqual(rows[0]['total_capacitance'], '3.5')
            self.assertTrue(rows[0]['capacitance'].startswith('UNAVAILABLE:'))
            self.assertIn('missing.rpt\tUNAVAILABLE', (Path(folder) / 'availability.tsv').read_text())

if __name__ == "__main__":
    unittest.main()