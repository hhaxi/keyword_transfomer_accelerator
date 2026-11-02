"""Run the real recovery Tcl with explicit DC API stubs, not a PDK design."""
import tempfile,tkinter,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class RecoveryTclTest(unittest.TestCase):
    def test_saved_design_is_reported_without_compile_or_new_constraints(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            temp=Path(folder);ddc=temp/'netlist/fixture.ddc';ddc.parent.mkdir();ddc.write_bytes(b'not a real DDC')
            lib=temp/'library.db';lib.touch()
            override=temp/'override.tcl'
            override.write_text(''.join('set '+name+' {'+lib.as_posix()+'}\n' for name in ('std_db','sram_db_128','sram_db_1024','sram_db_4096')))
            t=tkinter.Tcl()
            for name,value in {'KWT_RECOVER_BACKEND_ROOT':ROOT,'KWT_RECOVER_DDC':ddc,
                               'KWT_RECOVER_REPORT_DIR':temp/'reports','KWT_GLOBAL_LOCAL_CONFIG':override,
                               'KWT_SYNTHESIS_SCOPE':'soc'}.items():t.call('set','env('+name+')',str(value))
            t.eval('''
                set operations {}
                proc set_app_var {args} {}
                proc read_ddc {path} {lappend ::operations read_ddc;return 1}
                proc current_design {args} {return kwt_ffn1_soc}
                proc link {} {lappend ::operations link;return 1}
                proc sizeof_collection {objects} {llength $objects}
                proc get_object_name {object} {return $object}
                proc get_clocks {args} {return clk}
                proc get_attribute {args} {
                    set field [lindex $args end]
                    if {$field eq "period"} {return 6.666667}
                    if {$field eq "ref_name"} {return TEST_REAL_CELL}
                    if {$field eq "area"} {return 10.0}
                    error "Unexpected attribute $field"
                }
                proc get_cells {args} {
                    set filter [lindex $args end]
                    if {[regexp {ref_name == (RAMSP[0-9]+X16)} $filter ignored macro]} {
                        foreach spec $::expected_macros {
                            lassign $spec name count
                            if {$name eq $macro} {
                                set result {}
                                for {set i 0} {$i<$count} {incr i} {lappend result ${macro}_${i}}
                                return $result
                            }
                        }
                        return {}
                    }
                    return {bus/accelerator/U1 cpu/U1 bus/shared/U1}
                }
                proc foreach_in_collection {name collection body} {
                    uplevel 1 [list foreach $name $collection $body]
                }
                proc redirect {args} {
                    set path [lindex $args 1];set body [lindex $args end]
                    set text [uplevel 1 $body]
                    set output [open $path w];puts $output $text;close $output
                }
                proc report_timing {args} {lappend ::operations report_timing;return "slack (MET) 0.1"}
                proc report_clock {args} {return "clk 6.666667"}
                proc report_constraint {args} {return "No violations"}
                proc check_timing {args} {return "Test timing report"}
                proc report_area {args} {return "Total cell area: 30"}
                proc report_qor {args} {return "Total Negative Slack: 0"}
                proc report_units {args} {return "Time_unit : 1ns"}
                proc report_reference {args} {return "Test references"}
                proc check_design {args} {return 1}
                proc report_power {args} {return "Total Dynamic Power = 1 mW\nCell Leakage Power = 1 uW"}
                proc compile {args} {error "Forbidden compile"}
                proc compile_ultra {args} {error "Forbidden compile_ultra"}
                proc analyze {args} {error "Forbidden analyze"}
                proc elaborate {args} {error "Forbidden elaborate"}
                proc create_clock {args} {error "Forbidden replacement constraints"}
                proc exit {code} {set ::exit_code $code;error "TEST_EXIT_$code"}
            ''')
            with self.assertRaisesRegex(tkinter.TclError,'TEST_EXIT_0'):
                t.call('source',str(ROOT/'script/recover_reports.tcl'))
            self.assertEqual(int(t.eval('set exit_code')),0)
            self.assertEqual(t.eval('set operations'),'read_ddc link report_timing report_timing')
            self.assertIn('status=COMPLETE',(temp/'reports/area_scope.rpt').read_text())
            self.assertIn('inventory_valid=1',(temp/'reports/recovery_metadata.rpt').read_text())
            self.assertIn('period=6.666667',(temp/'reports/recovery_metadata.rpt').read_text())
            for name in ('qor.rpt','units.rpt','library_sources.rpt','sram_inventory.rpt'):
                self.assertTrue((temp/'reports'/name).is_file())

if __name__=='__main__':unittest.main()
