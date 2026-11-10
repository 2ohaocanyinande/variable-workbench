import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workbench as w

SOURCE='''typedef struct {float Kp;float Ki;float Kd;} abc_t;
abc_t first;
abc_t second;
float calc(float target, float feedback, abc_t *controller) {
 float error=target-feedback;
 return controller->Kp*error + controller->Kd*(error-last_error) + controller->Ki*sum;
}
void configure(void) {first.Kp=1.0f;first.Ki=0.2f;first.Kd=0.4f;second.Kp=3.0f;}
void update(void) {
 float outer=calc(reference,measurement,&first);
 float result=calc(outer,other_measurement,&second);
}
'''


class PidTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'a.c';self.source.write_text(SOURCE)
        (self.root/'CMakeLists.txt').write_text('idf_component_register(SRCS "a.c")')
        state=self.root/'state';state.mkdir()
        for name,value in [('STATE',state),('SCAN',None)]:
            p=patch.object(w,name,value);p.start();self.addCleanup(p.stop)
        w.SCAN=w.scan_project(self.root)

    def test_behavior_not_instance_name_and_local_dependency(self):
        index=w.SCAN['pid'];self.assertEqual(len(index['loops']),2)
        self.assertEqual(len(index['edges']),1)
        self.assertEqual(index['edges'][0]['kind'],'串级候选')
        self.assertFalse(index['loops'][0]['online_writable'])

    def test_unrelated_calls_or_overwritten_output_not_cascade(self):
        self.source.write_text(SOURCE.replace('float result=calc(outer,','outer=0;\n float result=calc(outer,'))
        self.assertEqual(w.scan_project(self.root)['pid']['edges'],[])

    def test_conditional_alternative_braces_do_not_hide_calls(self):
        source=SOURCE.replace('float outer=calc(reference,measurement,&first);',
            '#if MODE\nif(active) {\n#else\nif(other) {\n#endif\nfloat outer=calc(reference,measurement,&first);')
        # Both branches open the same lexical block; only one is compiled.
        source=source.replace('float result=calc(outer,other_measurement,&second);',
                              'float result=calc(outer,other_measurement,&second);\n}')
        self.source.write_text(source)
        index=w.scan_project(self.root)['pid']
        first=next(l for l in index['loops'] if l['symbol']=='first')
        self.assertTrue(first['calls'])
        self.assertTrue(first['calls'][0]['conditional_span'])
        self.assertEqual(index['edges'][0]['kind'],'条件编译下的依赖候选')

    def test_uncalled_instance_keeps_shared_evidence_without_false_binding(self):
        self.source.write_text(SOURCE.replace('float outer=calc(reference,measurement,&first);','float outer=0;'))
        index=w.scan_project(self.root)['pid']
        first=next(l for l in index['loops'] if l['symbol']=='first')
        self.assertEqual(first['calls'],[])
        self.assertTrue(first['kernels'])
        self.assertFalse(first.get('kernel_bound',False))

    def test_structure_without_multiplication_not_pid(self):
        self.source.write_text(SOURCE.replace('controller->Kp*error','1').replace('controller->Kd*(error-last_error)','2').replace('controller->Ki*sum','3'))
        self.assertEqual(w.scan_project(self.root)['pid']['loops'],[])

    def test_input_producer_evidence_is_preserved(self):
        self.source.write_text(SOURCE.replace('float outer=calc(reference,measurement,&first);',
            'float outer=calc(reference,feedback_value,&first);')+'''
float produce(void) { return GPIO_ReadPin(PORT, PIN_1)*8; }
void collect(void) { feedback_value=produce(); }
''')
        first=next(l for l in w.scan_project(self.root)['pid']['loops'] if l['symbol']=='first')
        self.assertIn('GPIO_ReadPin(PORT, PIN_1)*8',first['calls'][0]['context'])

    def config(self,value=2):
        loop=next(l for l in w.SCAN['pid']['loops'] if l['symbol']=='first')
        return {'project_hash':w.SCAN['project_hash'],'loops':[{'id':loop['id'],'name':'测试环','category':'待确认','gains':{'kp':{'value':value,'source_index':0}}}]}

    def test_export_patch_without_modifying_source_and_restore_draft(self):
        before=self.source.read_bytes();result=w.save_pid_config(self.config())
        self.assertIn('first.Kp=2.0f',result['patch'])
        self.assertEqual(before,self.source.read_bytes())
        self.assertEqual(w.scan_project(self.root)['pid']['draft']['loops'][0]['name'],'测试环')
        with self.assertRaises(ValueError): w.save_pid_config(self.config(float('nan')))
        with self.assertRaises(ValueError): w.save_pid_config(self.config(True))
        self.source.write_text(SOURCE+'\n')
        with self.assertRaises(ValueError): w.save_pid_config(self.config())

    def test_multiple_sources_are_not_final_runtime_value(self):
        self.source.write_text(SOURCE+'\nvoid mode(void){first.Kp=9.0f;}')
        index=w.scan_project(self.root)['pid']
        gain=next(l for l in index['loops'] if l['symbol']=='first')['gains']['kp']
        self.assertEqual(len(gain['sources']),2);self.assertIsNone(gain['value'])

    def test_apply_refreshes_offsets_and_rejects_a_stale_preview(self):
        original=b'\xef\xbb\xbf'+SOURCE.replace('\n','\r\n').encode('utf-8')
        self.source.write_bytes(original)
        w.SCAN=w.scan_project(self.root)
        with patch.object(w,'PID_WRITE_ROOT',self.root),patch.object(w,'MANIFEST',None):
            def preview(value):
                config=self.config(value)
                result=w.save_pid_config(config)
                self.assertEqual(result['write_block'],'')
                return dict(config,preview_id=result['preview_id'])

            first=preview(12.25)
            self.assertTrue(w.apply_pid_config(first)['refreshed'])
            self.assertEqual(self.source.read_bytes(),original.replace(b'first.Kp=1.0f',b'first.Kp=12.25f'))
            with self.assertRaises(ValueError):
                w.apply_pid_config(first)
            second=preview(3)
            self.assertTrue(w.apply_pid_config(second)['refreshed'])
            self.assertEqual(self.source.read_bytes(),original.replace(b'first.Kp=1.0f',b'first.Kp=3.0f'))

            stale=preview(4)
            external=self.source.read_bytes()+b'// external edit\r\n'
            self.source.write_bytes(external)
            with self.assertRaisesRegex(ValueError,'重新扫描'):
                w.apply_pid_config(stale)
            self.assertEqual(self.source.read_bytes(),external)

    def test_ai_cannot_add_unknown_loop_or_invent_quote(self):
        lid=w.SCAN['pid']['loops'][0]['id']
        answer={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'loops':[
            {'id':lid,'name':'速度候选','category':'速度环','reason':'测试','quote':'controller->Kp*error'},
            {'id':'invented','name':'坏项','category':'速度环','reason':'无依据','quote':'fabricated();'}]})}}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(answer).encode()
        with patch.object(w,'API',{'enabled':True,'url':'https://example.invalid','model':'test','key':'fake'}),patch.object(w.urllib.request,'urlopen',return_value=Response()):
            result=w.analyze_usage({'mode':'pid'})
        self.assertEqual(len(result['suggestions']),1)

if __name__=='__main__':unittest.main()
