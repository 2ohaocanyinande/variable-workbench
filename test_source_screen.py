import hashlib
from pathlib import Path
import tempfile
import unittest
import source_screen as s
import workbench as w
import context_questions as q

DRIVER='void OLED_ShowChar(int Line,int Column,char c){OLED_SetCursor((Line-1)*2,(Column-1)*8);}\n'
APP='''void draw(void){
if(key==1){page=1;}
OLED_Clear();
if(page==0){OLED_ShowString(1,1,"Speed:");OLED_ShowSignedNum(1,8,speed,3);}
if(page==1){OLED_ShowString(1,1,"Angle,deg");OLED_ShowNum(2,1,angle+2,3);}
}'''

class SourceScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.make(DRIVER,APP)
    def make(self,driver,app):
        (self.root/'driver.c').write_text(driver,encoding='utf-8');(self.root/'main.c').write_text(app,encoding='utf-8')
        self.scan={'root':str(self.root),'project_hash':'a'*64,'files':{n:hashlib.sha256((self.root/n).read_bytes()).hexdigest() for n in ['main.c','driver.c']},'inventory':{'endpoints':[]},'pid':{'loops':[]}}
        self.report=s.extract(self.scan);self.group=self.report['groups'][0] if self.report['groups'] else None
    def render(self,values):return s.render(self.report,{'group':self.group['id'],'values':values,'calls':[c['id'] for c in self.group['calls']]})
    def test_literals_variables_coordinates_and_numeric_format(self):
        self.assertEqual(self.group['name'],'draw');self.assertIn('speed',self.group['variables']);r=self.render({'page':0,'speed':-7});self.assertTrue(r['rows'][0].startswith('Speed: -007'))
        r=self.render({'page':1,'angle':10});self.assertTrue(r['rows'][0].startswith('Angle,deg'));self.assertTrue(r['rows'][1].startswith('012'))
    def test_missing_values_not_fake_live_data(self):
        r=self.render({'page':0});self.assertIn('{speed}',r['rows'][0]);r=self.render({});self.assertTrue(r['warnings'])
    def test_formatted_buffer_uses_each_nearest_assignment(self):
        self.make(DRIVER,'void draw(void){sprintf(buf,"A:%d",speed_A_real);OLED_ShowString(1,1,buf);sprintf(buf,"%04d",int_AGZ);OLED_ShowString(2,1,buf);}')
        self.assertIn('speed_A_real',self.group['variables']);r=self.render({'speed_A_real':12,'int_AGZ':-3});self.assertTrue(r['rows'][0].startswith('A:12'));self.assertTrue(r['rows'][1].startswith('-003'))
    def test_source_button_assignments_and_copyable_identifiers(self):
        self.assertEqual(self.group['buttons'][0]['input'],'key');self.assertEqual(self.group['buttons'][0]['variable'],'page');self.assertEqual(self.group['buttons'][0]['value'],1)
    def test_unverified_driver_does_not_guess_layout(self):
        self.make('',APP);self.assertFalse(self.group['grid_verified']);self.assertEqual(self.render({'page':0})['rows'],[])
    def test_serial_menu_is_not_a_screen(self):
        self.make('', 'void Send_Menu(void){USART3_SendString("menu");}');self.assertFalse(self.report['groups'])
    def test_hash_changes_and_unsafe_expressions_rejected(self):
        (self.root/'main.c').write_text('changed')
        with self.assertRaises(ValueError):s.extract(self.scan)
        for expr in ['__import__("os")','a.b','2**1000000','x[0]'] :self.assertIsNone(s.evaluate(expr,{}))
        self.assertEqual(s.evaluate('10U+2',{}),12)
    def test_global_question_targets_include_files_variables_and_screen_sources(self):
        self.scan['usage']={'candidates':[{'id':'v','symbol':'speed','path':'main.c','line':4,'evidence_ids':['x']}],'snippets':{'x':{'path':'main.c','line':4}}};self.scan['screen_index']=self.report
        targets=q.targets(self.scan,self.root);ids={t['id'] for t in targets};self.assertIn('file:main.c',ids);self.assertIn('usage:v',ids);self.assertIn('screen-group:'+self.group['id'],ids)
    def test_original_source_unchanged(self):
        self.render({'page':1,'angle':8});self.assertTrue(all(hashlib.sha256((self.root/n).read_bytes()).hexdigest()==sha for n,sha in self.scan['files'].items()))

if __name__=='__main__':unittest.main()
