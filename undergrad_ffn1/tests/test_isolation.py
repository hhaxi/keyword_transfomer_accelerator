"""Reject accidental inclusion of optional accelerator hardware or parent paths."""
from pathlib import Path
import re,unittest
ROOT=Path(__file__).resolve().parents[1]

class IsolationTest(unittest.TestCase):
    def test_standalone_filelists(self):
        for scope in ('soc','accelerator'):
            lines=(ROOT/f'filelists/{scope}.f').read_text().splitlines()
            self.assertEqual(len(lines),len(set(lines)))
            for line in lines:
                self.assertNotIn('..',Path(line).parts)
                self.assertTrue((ROOT/line).is_file(),line)
                self.assertFalse(re.search(r'kwt_(?:encoder|gelu|exp_negative|isqrt|udiv|vecmem|result_fifo)',line),line)
    def test_core_has_only_first_layer_storage(self):
        text=(ROOT/'rtl/kwt_ffn1_core.sv').read_text()
        self.assertIn('kwt_mac40',text)
        self.assertNotRegex(text,r'\b(?:second_stage|w2write|gelu_busy|wd2|gd|nw2)\b')
        self.assertNotIn('kwt_ffn2',text)

if __name__=='__main__':unittest.main()
