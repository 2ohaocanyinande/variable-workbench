"""Packaged runtime smoke check with our own read-only STM32 parsing fixture."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

base=Path(__file__).parent;url='http://127.0.0.1:8765';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):return json.load(opener.open(url+'/api/'+path,timeout=20))
def post(path,data):return json.load(opener.open(urllib.request.Request(url+'/api/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=20))

for attempt in range(100):
    try:state=get('state');break
    except OSError:time.sleep(.1)
else:raise RuntimeError('local app not ready')
assert not state['connected'] and not state['active_record']
for name in ['app.js','template-panel.js','template-panel.css']:assert opener.open(url+'/'+name).read()==(base/'dist'/name).read_bytes()
scan=post('scan',{'path':str(base/'sample_stm32_panel')});root=Path(scan['root']);before=dict(scan['files'])
listed=get('template-panel');choices=[]
for c in listed['candidates']:
    if c['id'].startswith('interface:') and 'PWM' in c['name']:choices.append({'id':c['id'],'template':'motor','name':'左电机' if not choices else '右电机'})
    elif c['suggested'] in {'encoder','imu','pid'}:choices.append({'id':c['id'],'template':c['suggested'],'name':{'encoder':'轮编码器','imu':'惯性传感器','pid':'角度控制环'}[c['suggested']]})
panel=post('template-panel',{'project_hash':scan['project_hash'],'selections':choices});motors=[item for item in panel['items'] if item['template']=='motor'];assert len(motors)==2
for item,value in zip(motors,[42,-18]):
    f=item['fields'][0];reply=post('template-panel-set',{'panel_id':panel['id'],'project_hash':panel['project_hash'],'field':f['id'],'value':value});assert reply['value']==value and not reply['hardware_written']
data=get('template-panel-data?panel_id='+panel['id']+'&project_hash='+panel['project_hash']+'&t=2');assert [data['values'][m['fields'][0]['id']] for m in motors]==[42,-18]
restored=get('template-panel')['panel'];assert restored['id']==panel['id'] and len(restored['values'])==2
assert all(hashlib.sha256((root/relative).read_bytes()).hexdigest()==sha for relative,sha in before.items())
result={'packaged_assets_match':True,'mode':panel['mode'],'items':len(panel['items']),'fields':sum(len(i['fields']) for i in panel['items']),
        'motor_values':[data['values'][m['fields'][0]['id']] for m in motors],'persisted':True,'source_files_unchanged':len(before),
        'key_settings_remembered':get('state')['api_remembered'],'hardware_written':False,'project':str(root)}
(base/'state/template-panel-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
