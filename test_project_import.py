from pathlib import Path
import tempfile
import unittest
import workbench as w
from project_layout import resolve_project_root

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def project(self,root):
        (root/'USER').mkdir(parents=True);(root/'HARDWARE').mkdir()
        (root/'USER'/'demo.uvprojx').write_text('<Project><Targets><Target><TargetName>demo</TargetName><Device>STM32F407VE</Device><File><FilePath>main.c</FilePath></File><File><FilePath>../HARDWARE/output.c</FilePath></File></Target></Targets></Project>')
        (root/'USER'/'main.c').write_text('void main(void) { output(); }')
        (root/'HARDWARE'/'output.c').write_text('void output(void) { TIM_SetCompare1(TIM1, 100); }')

    def test_user_keil_and_packaging_folder_include_siblings(self):
        inner=self.root/'archive';self.project(inner)
        scan=w.scan_project(self.root);self.assertEqual(scan['root'],str(inner));self.assertEqual(scan['platform'],'stm32');self.assertIn('HARDWARE/output.c',scan['files']);self.assertEqual(len(scan['inventory']['endpoints']),1)

    def test_multiple_projects_require_choice(self):
        self.project(self.root/'a');self.project(self.root/'b')
        with self.assertRaisesRegex(ValueError,'多个工程'):resolve_project_root(self.root)

    def test_never_search_parent_or_deep_descendants(self):
        self.project(self.root/'a');child=self.root/'a'/'HARDWARE'
        with self.assertRaises(ValueError):resolve_project_root(child)
        empty=self.root/'outer';empty.mkdir();self.project(empty/'deep'/'inner')
        with self.assertRaises(ValueError):resolve_project_root(empty)

    def test_gpio_macro_driver_and_vendor_header_noise(self):
        self.project(self.root/'p');root=self.root/'p'
        (root/'HARDWARE'/'pins.h').write_text('#define PBout(n) BIT_ADDR(GPIOB_ODR_Addr,n)\n#define PBin(n) BIT_ADDR(GPIOB_IDR_Addr,n)\n#define TRIGGER PBout(0)\n#define ECHO PBin(1)\n')
        (root/'HARDWARE'/'range.c').write_text('#include "pins.h"\nvoid range(void){TRIGGER=1;while(ECHO==0){wait();}}')
        scan=w.scan_project(root);macros=[e for e in scan['inventory']['endpoints'] if e['family']=='MACRO_IO'];self.assertEqual({e['handle'] for e in macros},{'TRIGGER','ECHO'})
        from project_layout import is_vendor_source
        self.assertTrue(is_vendor_source(Path('CORE/core_cm4.h')));self.assertTrue(is_vendor_source(Path('USER/stm32f4xx.h')));self.assertFalse(is_vendor_source(Path('USER/stm32f4xx_it.c')))

    def test_numeric_macro_tracks_use_after_renaming(self):
        self.project(self.root/'p');root=self.root/'p';header=root/'HARDWARE'/'settings.h';source=root/'HARDWARE'/'output.c'
        for name in ['TURN_SCALE','q7']:
            header.write_text('#define '+name+' 35\n');source.write_text('#include "settings.h"\nvoid output(void) { TIM_SetCompare1(TIM1, '+name+'); }')
            scan=w.scan_project(root);candidate=next(c for c in scan['usage']['candidates'] if c['symbol']==name)
            self.assertEqual(candidate['type'],'numeric_macro');self.assertEqual(candidate['literal'],'35');self.assertGreater(len(candidate['evidence_ids']),1)

    def test_cached_report_only_attaches_to_explicit_matching_scan(self):
        import json
        from unittest.mock import patch
        self.project(self.root/'p');scan=w.scan_project(self.root/'p')
        cache={'root':scan['root'],'project_hash':scan['project_hash'],'device_report':{'devices':[]}}
        (self.root/'project-session.json').write_text(json.dumps(cache))
        with patch.object(w,'STATE',self.root):
            w.restore_device_report(scan);self.assertTrue(scan['device_report']['restored_from_cache'])
            scan.pop('device_report');cache['project_hash']='different';(self.root/'project-session.json').write_text(json.dumps(cache));w.restore_device_report(scan);self.assertNotIn('device_report',scan)

    def test_explicit_macro_query_is_not_hidden_by_peripheral_scope(self):
        from usage_analysis import make_packet
        self.project(self.root/'p');root=self.root/'p'
        (root/'HARDWARE'/'output.c').write_text('#define STEP_AMOUNT 0.02f\nvoid output(void){float x=STEP_AMOUNT;custom_output(x);}')
        scan=w.scan_project(root);packet=make_packet(scan,'STEP_AMOUNT','stm32');self.assertIn('STEP_AMOUNT',[c['symbol'] for c in packet['candidates']])

if __name__=='__main__':unittest.main()
