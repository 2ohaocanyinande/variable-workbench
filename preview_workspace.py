"""Isolated local UI preview; no API credentials, serial port or source writes."""
import json
from pathlib import Path
import urllib.parse
import workbench as w
import telemetry
import tuning_advisor

w.STATE=w.BASE/'state'/'workspace-preview'
w.STATE.mkdir(exist_ok=True)
if not telemetry.listing(w.STATE/'records'):telemetry.demo(w.STATE/'records')
if not any(r.get('info',{}).get('tuning_scenario') for r in telemetry.listing(w.STATE/'records')):tuning_advisor.demos(w.STATE/'records')
w.SCAN=w.scan_project(Path('D:/Halpractice/qiansaitest'))
result=w.BASE/'state/pid-qiansaitest-check.json'
if result.is_file():
    suggestions=json.loads(result.read_text(encoding='utf-8')).get('suggestions',[])
    ids={l['id'] for l in w.SCAN['pid']['loops']}
    w.SCAN['pid']['suggestions']=[s for s in suggestions if s['id'] in ids]


class Preview(w.Handler):
    def do_GET(self):
        if self.path=='/app.js':
            extra="""
setTimeout(async()=>{const params=new URLSearchParams(location.search);const view=params.get('view')||'pid';if(view==='demo'){showWorkspace('demo');if(params.get('scene'))demoState.scenario=params.get('scene');await prepareShowcase();stopDemoReplay();setDemoStage(Number(params.get('stage')||0));demoState.time=Number(params.get('time')||0);drawDemoChart();if(params.get('present'))$('demo-present').onclick();}else if(view==='records'){await refreshRecords();showWorkspace(view);if(params.get('tuning')){const before=localRecords.find(r=>r.info.tuning_scenario==='oscillating'),after=localRecords.find(r=>r.info.tuning_scenario==='damped');$('record-list').value=before.id;selectRecord();$('tuning-confirmed').checked=true;$('tuning-feedback').checked=true;await $('tuning-diagnose').onclick();$('tuning-before').value=before.id;$('tuning-after').value=after.id;await $('tuning-compare').onclick();document.querySelector('.tuning-workspace').scrollIntoView();}else{if(params.get('channel')){$('record-channel').value=params.get('channel');configureRecordChannel();}await $('record-analyze').onclick();}}else{showWorkspace(view);if(view==='pid')document.querySelector('.pid-card')?.setAttribute('open','');}},300);"""
            extra=extra.replace("document.querySelector('.tuning-workspace').scrollIntoView();", "")
            body=(w.BASE/'dist/app.js').read_bytes()+extra.encode()
            self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path.startswith('/?'): self.path='/'
        super().do_GET()


w.ThreadingHTTPServer(('127.0.0.1',8768),Preview).serve_forever()
