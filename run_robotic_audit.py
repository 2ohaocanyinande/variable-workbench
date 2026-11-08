"""Read-only holdout check. Output belongs to this workbench, never the project."""
import json
import time
from pathlib import Path
import api_store
import workbench as w

out=w.STATE/'robotic-arm-audit';out.mkdir(exist_ok=True)
if (out/'actual-model-result.json').is_file():raise RuntimeError('这一次已授权模型测试已经完成，不自动再次调用')
start=time.monotonic();w.SCAN=w.scan_project(Path('D:/原理图等资料/robotic-arm-cart-master'))
settings=api_store.load(w.STATE/'model-settings.dpapi')
if not settings or not settings.get('enabled'):raise RuntimeError('没有可用的已启用模型设置')
w.API=settings
if settings.get('url','').rstrip('/')!='https://api.deepseek.com' or settings.get('model')!='deepseek-flash':raise RuntimeError('API 目的地或模型与用户确认不一致，未发送')
preview=w._analyze_usage({'mode':'devices','preview':True})
approved=json.loads((out/'request-preview.json').read_text(encoding='utf-8'))
if preview['packet']!=approved:raise RuntimeError('源码上下文与用户确认的预览不一致，未发送')
(out/'actual-request-preview.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
try:
    result=w.analyze_usage({'mode':'devices'})
    (out/'actual-model-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'seconds':round(time.monotonic()-start,2),'packet_bytes':preview['bytes'],'devices':[{'name':d['name'],'kind':d['kind'],'instance':d['instance'],'endpoints':d['endpoint_ids']} for d in result['devices']],'warnings':result.get('warnings'),'coverage':result.get('coverage')},ensure_ascii=True,indent=2))
except Exception as error:
    (out/'actual-model-error.json').write_text(json.dumps({'error':str(error),'seconds':round(time.monotonic()-start,2)},ensure_ascii=False),encoding='utf-8');raise
