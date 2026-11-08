"""Isolated visual QA using only our own parsing fixture and synthetic values."""
import json
from pathlib import Path
import workbench as w
import panel_templates as p

w.STATE=w.BASE/'state'/'template-preview';w.STATE.mkdir(exist_ok=True)
w.SCAN=w.scan_project(w.BASE/'sample_stm32_panel')
candidates=p.candidates(w.SCAN)
choices=[]
pwm=0
for c in candidates:
    if c['id'].startswith('interface:') and 'PWM' in c['name']:
        pwm+=1;choices.append({'id':c['id'],'name':'左电机' if pwm==1 else '右电机','template':'motor'})
    elif c['suggested'] in {'imu','encoder','pid'}:choices.append({'id':c['id'],'name':{'imu':'惯性传感器','encoder':'轮编码器','pid':'角度控制环'}[c['suggested']],'template':c['suggested']})
panel=p.build(w.STATE,w.SCAN,{'project_hash':w.SCAN['project_hash'],'selections':choices})
for i,item in enumerate(panel['items']):
    if item['template']=='motor':
        p.set_value(w.STATE,w.SCAN,{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':item['fields'][0]['id'],'value':25 if i==0 else -15})


class Preview(w.Handler):
    def do_GET(self):
        if self.path=='/app.js':
            extra="""\nsetTimeout(async()=>{workspaceNavigated=true;showWorkspace('panel');await refreshTemplatePanel(true);if(new URLSearchParams(location.search).get('builder'))$('tpl-builder').open=true;else $('tpl-builder').open=false;const params=new URLSearchParams(location.search);if(params.get('view')==='screen'){showWorkspace('screen');screenState.page='data';renderScreen();if(params.get('question')){await openQuestion('screen:buttons');$('question-text').value='这里的按键怎样调整屏幕？';await sendQuestion();}}},300);"""
            body=(w.BASE/'dist/app.js').read_bytes()+extra.encode();self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path.startswith('/?'):self.path='/'
        super().do_GET()


w.ThreadingHTTPServer(('127.0.0.1',8769),Preview).serve_forever()
