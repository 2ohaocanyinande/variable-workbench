import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import urllib.request
import panel_templates as p
import workbench as w


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'project';self.root.mkdir();self.base=Path(self.tmp.name)/'state';self.base.mkdir()
        self.source=self.root/'main.c';self.source.write_text('void f(void) {}\n');self.sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        endpoint=lambda eid,family:dict(id=eid,family=family,handle='h'+eid,channel='',path='main.c',module_hints=[],calls=[{'line':1,'api':'test','sha256':self.sha}])
        self.scan={'root':str(self.root),'project_hash':'f'*64,'platform':'stm32','files':{'main.c':self.sha},'inventory':{'endpoints':[endpoint('a','PWM'),endpoint('b','ENCODER'),endpoint('c','ADC')]},
                   'pid':{'loops':[{'id':'pid-a','symbol':'ctrl_x','gains':{'kp':{'value':15},'ki':{'value':None},'kd':{'value':.75}},'evidence':[{'path':'main.c','line':1,'sha256':self.sha}]}]}}

    def build(self,selections=None):
        return p.build(self.base,self.scan,{'project_hash':self.scan['project_hash'],'selections':selections or [{'id':'interface:a','template':'motor','name':'左电机'},{'id':'interface:b','template':'encoder','name':'轮编码器'},{'id':'pid:pid-a','template':'pid','name':'角度环'}]})

    def test_pwm_not_assumed_servo_or_motor(self):
        rows=p.candidates(self.scan);self.assertEqual(rows[0]['suggested'],'generic');self.assertEqual(rows[1]['suggested'],'encoder');self.assertEqual(rows[2]['suggested'],'adc')

    def test_save_reload_trace_and_readonly_source(self):
        panel=self.build();self.assertEqual(len(panel['items']),3);self.assertEqual(p.load(self.base,self.scan)['id'],panel['id'])
        self.assertEqual(panel['items'][0]['evidence'][0]['path'],'main.c');self.assertEqual(panel['mode'],'simulation');self.assertFalse(panel['hardware_writable'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.sha)

    def test_set_persists_only_simulated_value(self):
        panel=self.build();field=panel['items'][0]['fields'][0];r=p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':field['id'],'value':37.5})
        self.assertFalse(r['hardware_written']);self.assertEqual(p.sample(p.load(self.base,self.scan),2)['values'][field['id']],37.5)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.sha)

    def test_invalid_values_and_read_only_fields(self):
        panel=self.build();field=panel['items'][0]['fields'][0]
        for value in [101,-101,True,None,float('nan'),'30']:
            with self.assertRaises(ValueError):p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':field['id'],'value':value})
        with self.assertRaises(ValueError):p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':panel['items'][1]['fields'][0]['id'],'value':3})

    def test_pid_source_defaults_not_device_readback(self):
        panel=self.build();fields=panel['items'][2]['fields'];self.assertEqual(fields[0]['initial'],15);self.assertEqual(fields[1]['initial'],0)
        self.assertIn('源码扫描',fields[0]['initial_source']);self.assertIn('未确定',fields[1]['initial_source'])

    def test_same_content_project_folders_do_not_share_panel(self):
        panel=self.build();other={**self.scan,'root':str(self.root/'clone')};self.assertNotEqual(p.path(self.base,self.scan),p.path(self.base,other));self.assertIsNone(p.load(self.base,other))

    def test_stale_source_and_panel_rejected(self):
        panel=self.build()
        with self.assertRaises(ValueError):p.set_value(self.base,self.scan,{'panel_id':'old','project_hash':panel['project_hash'],'field':panel['items'][0]['fields'][0]['id'],'value':3})
        self.source.write_text('changed')
        with self.assertRaises(ValueError):self.build()

    def test_multiple_motors_remain_separate(self):
        self.scan['device_report']={'devices':[{'id':'left','name':'左电机','instance':'LEFT','kind':'motor','interfaces':[],'evidence':[]},{'id':'right','name':'右电机','instance':'RIGHT','kind':'motor','interfaces':[],'evidence':[]}]}
        panel=self.build([{'id':'device:'+key,'template':'motor','name':key} for key in ['left','right']]);a,b=[item['fields'][0]['id'] for item in panel['items']]
        p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':a,'value':80});values=p.sample(p.load(self.base,self.scan),1)['values'];self.assertEqual(values[a],80);self.assertEqual(values[b],0)

    def test_all_templates_and_boolean_text_validation(self):
        for key in p.TEMPLATES:
            panel=self.build([{'id':'interface:a','template':key,'name':key}]);r=p.sample(panel,2.5);self.assertTrue(r['values']);self.assertEqual(r['mode'],'simulation')
        panel=self.build([{'id':'interface:a','template':'display','name':'OLED'}]);f=panel['items'][0]['fields'][0]
        result=p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':f['id'],'value':'测试显示 <text>'});self.assertEqual(result['value'],'测试显示 <text>')
        with self.assertRaises(ValueError):p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':f['id'],'value':'x'*81})
        panel=self.build();field=panel['items'][0]['fields'][1]
        with self.assertRaises(ValueError):p.set_value(self.base,self.scan,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':field['id'],'value':1})

    def test_unknown_duplicate_and_limits(self):
        for selections in [[],[{'id':'invented','template':'motor'}],[{'id':'interface:a','template':'bad'}],[{'id':'interface:a','template':'motor'}]*2]:
            with self.assertRaises(ValueError):p.build(self.base,self.scan,{'project_hash':self.scan['project_hash'],'selections':selections})
        for t in [float('nan'),float('inf'),-1,True,86401]:
            with self.assertRaises(ValueError):p.sample(self.build(),t)

    def test_http_endpoints_never_write_serial(self):
        port=Mock()
        with patch.object(w,'SCAN',self.scan),patch.object(w,'STATE',self.base),patch.object(w,'PORT',port):
            server=w.ThreadingHTTPServer(('127.0.0.1',0),w.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));url='http://127.0.0.1:'+str(server.server_port)
                def post(path,body):return json.load(opener.open(urllib.request.Request(url+'/api/'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})))
                listed=json.load(opener.open(url+'/api/template-panel'));self.assertEqual(listed['root'],str(self.root))
                panel=post('template-panel',{'project_hash':self.scan['project_hash'],'selections':[{'id':'interface:a','template':'servo','name':'舵机'}]})
                result=post('template-panel-set',{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':panel['items'][0]['fields'][0]['id'],'value':35})
                sample=json.load(opener.open(url+'/api/template-panel-data?panel_id='+panel['id']+'&project_hash='+panel['project_hash']+'&t=1'))
                self.assertEqual(list(sample['values'].values()),[35]);self.assertFalse(result['hardware_written']);port.write.assert_not_called()
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
