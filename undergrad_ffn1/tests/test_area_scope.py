"""Exercise the area reporter in plain Tcl; no DC/PDK result is fabricated."""
import tempfile,tkinter,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class AreaScopeTest(unittest.TestCase):
    def setUp(self):
        self.t=tkinter.Tcl()
        self.t.eval('''
            set attributes {}; set references {}; set leaves {}
            proc sizeof_collection {c} {llength $c}
            proc get_attribute {args} {
                global attributes
                set obj [lindex $args end-1];set attr [lindex $args end]
                if {[dict exists $attributes $obj $attr]} {return [dict get $attributes $obj $attr]}
                return {}
            }
            proc get_lib_cells {args} {
                global references
                set obj [lindex $args end]
                if {[dict exists $references $obj]} {return [dict get $references $obj]}
                return {}
            }
            proc get_object_name {obj} {return $obj}
            proc get_cells {args} {global leaves;return $leaves}
            proc foreach_in_collection {name collection body} {
                uplevel 1 [list foreach $name $collection $body]
            }
        ''')
        self.t.call('source',str(ROOT/'script/area_scope.tcl'))
        self.cells=[]
        self.add('bus/accelerator/U1','AND2',10)
        self.add('cpu/U1','DFF',20)
        self.add('bus/shared/U1','RAMSP4096X16',100)

    def add(self,name,ref,area=None):
        self.cells.append(name)
        self.t.call('dict','set','attributes',name,'ref_name',ref)
        if area is not None:self.t.call('dict','set','attributes',name,'area',area)
        self.t.call('set','leaves',tuple(self.cells))

    def report(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            p=Path(folder)/'area.rpt'
            valid=int(self.t.call('kwt_write_scope_area_report',str(p)))
            return valid,p.read_text()

    def test_constant_pseudo_cells_do_not_make_real_areas_unknown(self):
        self.add('bus/accelerator/U0','**logic_0**')
        self.add('cpu/U0','**logic_1**')
        self.add('bus/accelerator/tie','TIELO',0.4)
        valid,text=self.report()
        self.assertEqual(valid,1,text)
        self.assertIn('area=10.4',text)
        self.assertIn('constant_pseudo=2',text)
        self.assertNotIn('UNKNOWN_AREA cell',text)

    def test_unknown_real_macros_and_similar_names_still_fail(self):
        for reference in ('RAMSP128X16','TIELO','custom_logic_0','**logic_x**'):
            with self.subTest(reference=reference):
                self.t.call('dict','set','attributes','bus/shared/U1','area','')
                self.t.call('dict','set','attributes','bus/shared/U1','ref_name',reference)
                valid,text=self.report()
                self.assertEqual(valid,0)
                self.assertIn('UNKNOWN_AREA cell bus/shared/U1',text)

    def test_actual_linked_library_area_remains_available(self):
        self.add('bus/accelerator/from_lib','RAMSP128X16')
        self.t.call('dict','set','references','bus/accelerator/from_lib','lib/RAMSP128X16')
        self.t.call('dict','set','attributes','lib/RAMSP128X16','area',200)
        valid,text=self.report()
        self.assertEqual(valid,1,text)
        self.assertIn('area=210.0',text)
        self.assertIn('library=1',text)

    def test_empty_categories_and_invalid_physical_area_still_fail(self):
        self.t.call('set','leaves',('bus/accelerator/U1',))
        valid,text=self.report()
        self.assertEqual(valid,0)
        self.assertIn('EMPTY_CATEGORY cpu',text)
        for value in ('NaN','Inf','-1',''):
            self.assertEqual(int(self.t.call('kwt_valid_area',value)),0)

if __name__=='__main__':unittest.main()
