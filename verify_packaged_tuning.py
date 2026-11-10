"""Smoke check the packaged localhost service; never sends device commands."""
import json
from pathlib import Path
import urllib.request

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));url='http://127.0.0.1:8765'
def get(path):return json.load(opener.open(url+path,timeout=20))
def post(endpoint,data):
    request=urllib.request.Request(url+'/api/'+endpoint,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    return json.load(opener.open(request,timeout=20))

check=json.loads(Path('state/tuning-check.json').read_text(encoding='utf-8'));ids=check['records']
meta=json.loads((Path('state/records')/ids['oscillating']/'meta.json').read_text(encoding='utf-8'))
config={**meta['info']['snapshot'],'mapping':{'angle':'angle_deg','target':'target_deg','gyro':'gyro_dps','output':'control_out','integral':'i_out','derivative':'d_out'},'tolerance':.3,'parameters_confirmed':True,'feedback_verified':True}
r=post('tuning-diagnose',{'id':ids['oscillating'],'config':config})
c=post('tuning-compare',{'before':ids['oscillating'],'after':ids['damped'],'config':config})
assert r['proposal']['after']==14.25 and c['rms_reduction_percent']>99
for name in ['tuning.js','tuning.css']:assert opener.open(url+'/'+name).read()==Path('dist',name).read_bytes()
assert b'tuning-demo' not in opener.open(url+'/').read()
# This is the user's previously opened, authorized read-only test project.
session=Path('state/project-session.json')
if session.is_file():Path('state/project-session-before-tuning-check.json').write_bytes(session.read_bytes())
scan=post('scan',{'path':'D:/Halpractice/qianrushidasaitest_1'})
hints=[h for e in scan['inventory']['endpoints'] for h in e.get('module_hints',[]) if h.get('module_model')]
assert hints and len(hints[0]['components'])==3
s=get('/api/state')
result={'packaged_app':True,'assets_match':True,'key_settings_remembered':s['api_remembered'],'api_enabled':s['api_enabled'],
        'record_count':len(get('/api/records')['records']),'frequency_hz':r['metrics']['frequency_hz'],
        'proposal':r['proposal'],'rms_reduction_percent':c['rms_reduction_percent'],'nine_axis_components':hints[0]['components'],
        'diagnosis_path':r['report_path'],'comparison_path':c['report_path']}
Path('state/tuning-packaged-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['proposal','nine_axis_components']},indent=2))
