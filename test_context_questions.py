import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import context_questions as q
import workbench as w

class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.source=self.root/'a.c';self.source.write_text('// hidden-secret\nvoid f(){char *key="hidden-secret"; HAL_ADC_GetValue(&hadc1);}\n')
        sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.scan={'root':str(self.root),'project_hash':'p'*64,'platform':'stm32','files':{'a.c':sha},'inventory':{'endpoints':[{'id':'adc','family':'ADC','handle':'hadc1','channel':'','path':'a.c','calls':[{'line':2,'sha256':sha,'api':'HAL_ADC_GetValue'}]}]},'pid':{'loops':[]}}
        self.data={'project_hash':self.scan['project_hash'],'target':'interface:adc','question':'采样值有什么用？','screen':{'text':'private-screen-text','size':'128x64','page':'data'}}

    def test_bounded_masked_context(self):
        packet=q.packet(self.scan,self.root,self.data,w.strip_comments);text=json.dumps(packet)
        self.assertNotIn('hidden-secret',text);self.assertNotIn('private-screen-text',text);self.assertIn('HAL_ADC_GetValue',text);self.assertEqual(packet['screen']['size'],'128x64')
        self.scan['fields']=[{'id':'native','label':'温度','module':'chip','evidence':[{'path':'a.c','line':2}]}]
        self.assertTrue(any(t['id']=='native-field:native' for t in q.targets(self.scan,self.root)))

    def test_reject_unknown_stale_and_changed_source(self):
        for data in [{**self.data,'target':'../../secret'},{**self.data,'project_hash':'old'},{**self.data,'question':''}]:
            with self.assertRaises(ValueError):q.packet(self.scan,self.root,data,w.strip_comments)
        self.source.write_text('changed')
        with self.assertRaises(ValueError):q.packet(self.scan,self.root,self.data,w.strip_comments)

    def test_local_and_preview_do_not_call_provider(self):
        with patch.object(w,'SCAN',self.scan),patch.object(w,'STATE',self.root),patch.object(w,'API',{}),patch.object(w.urllib.request,'urlopen') as http:
            answer=w.answer_context_question(self.data);self.assertEqual(answer['source'],'local');self.assertIn('未调用模型',answer['answer']);w.answer_context_question(self.data,True);http.assert_not_called()

    def test_model_uses_only_bound_context(self):
        response=io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'采样值需按配置解释。'}}]}).encode())
        settings={'enabled':True,'url':'https://provider.invalid','model':'test','key':'unit-test-only'}
        with patch.object(w,'SCAN',self.scan),patch.object(w,'STATE',self.root),patch.object(w,'API',settings),patch.object(w.urllib.request,'urlopen',return_value=response) as http:
            result=w.answer_context_question(self.data);self.assertEqual(result['source'],'model');body=json.loads(http.call_args.args[0].data);self.assertNotIn('hidden-secret',json.dumps(body));self.assertEqual(len(body['messages']),2)

    def test_screen_context_cannot_contain_arbitrary_strings(self):
        data={**self.data,'target':'screen:buttons','screen':{'size':'some-secret','page':'data','brightness':float('nan'),'selected':0}}
        packet=q.packet(self.scan,self.root,data,w.strip_comments);self.assertEqual(packet['screen'],{'page':'data','selected':0});self.assertFalse(packet['snippets'])

    def test_incomplete_model_result_is_error(self):
        response=io.BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':'partial'}}]}).encode())
        with patch.object(w,'SCAN',self.scan),patch.object(w,'STATE',self.root),patch.object(w,'API',{'enabled':True,'url':'https://provider.invalid','model':'test','key':''}),patch.object(w.urllib.request,'urlopen',return_value=response):
            with self.assertRaises(ValueError):w.answer_context_question(self.data)

if __name__=='__main__':unittest.main()
