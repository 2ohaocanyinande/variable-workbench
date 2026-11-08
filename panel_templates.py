"""Project-grounded UI templates. Every value here is explicitly simulation."""
import hashlib
import json
import math
from pathlib import Path
import uuid


def number(key,label,unit='',low=-100,high=100,initial=0,access='rw',profile='constant'):
    return dict(key=key,label=label,unit=unit,min=low,max=high,initial=initial,type='number',access=access,profile=profile)


TEMPLATES={
 'generic':{'label':'通用数值（用途待确认）','fields':[number('value','数值','',-100,100,0,'ro','wave')]},
 'motor':{'label':'电机演示','fields':[number('output','输出设定','%',-100,100),{'key':'enabled','label':'电机开关','type':'bool','initial':False,'access':'rw','profile':'constant'}]},
 'servo':{'label':'舵机演示','fields':[number('angle','角度设定','°',-90,90)]},
 'imu':{'label':'惯性／姿态数据演示','fields':[number('pitch','俯仰角','°',-180,180,0,'ro','wave'),number('roll','横滚角','°',-180,180,0,'ro','wave'),number('gyro_z','Z 轴角速度','°/s',-500,500,0,'ro','wave')]},
 'encoder':{'label':'编码器演示','fields':[number('count','模拟累计计数','count',0,1000000,0,'ro','counter'),number('speed','模拟转速','rpm',-300,300,0,'ro','wave')]},
 'distance':{'label':'测距数据演示','fields':[number('distance','模拟距离','mm',0,2000,500,'ro','distance')]},
 'adc':{'label':'ADC 数值演示','fields':[number('adc','模拟采样值','',0,4095,0,'ro','adc')]},
 'display':{'label':'显示器演示','fields':[{'key':'text','label':'显示文本','type':'text','initial':'Hello STM32','access':'rw','profile':'constant'}]},
 'pid':{'label':'PID 参数演示','fields':[number('kp','Kp','',-1000000,1000000),number('ki','Ki','',-1000000,1000000),number('kd','Kd','',-1000000,1000000)]},
}
NOTICE='所有数值来自本机模拟。范围、单位和信号含义由模板示例提供，不等同于设备量程或已验证的固件字段。应用仅修改本机模拟值。'


def candidates(scan):
    result=[];inventory=scan.get('inventory',{});devices=(scan.get('device_report') or {}).get('devices') or []
    if devices:
        for d in devices:
            kind=d.get('kind','unknown');category=d.get('category','');families={e.get('family') for e in d.get('interfaces',[])}
            template=kind if kind in {'motor','servo','display'} else 'encoder' if 'ENCODER' in families else 'imu' if 'IMU' in category or '惯性' in category else 'distance' if '测距' in category else 'generic'
            result.append(dict(id='device:'+d['id'],source_id=d['id'],name=d['name'],instance=d.get('instance',''),origin='设备候选（类型仍需确认）',suggested=template,evidence=d.get('evidence',[])))
    else:
        for e in inventory.get('endpoints',[])[:128]:
            hints=e.get('module_hints') or [];category=hints[0].get('category','') if len(hints)==1 else ''
            template='encoder' if e['family']=='ENCODER' else 'adc' if e['family']=='ADC' else 'imu' if 'IMU' in category or '惯性' in category else 'distance' if '测距' in category else 'generic'
            result.append(dict(id='interface:'+e['id'],source_id=e['id'],name=(category or e['family']+' 接口')+' · '+e['handle']+((' / '+e['channel']) if e.get('channel') else ''),instance=e['handle']+((' / '+e['channel']) if e.get('channel') else ''),origin='本地接口线索（物理设备未确认）',suggested=template,evidence=[dict(path=e['path'],line=c['line'],sha256=c.get('sha256'),role=c.get('api','接口调用')) for c in e.get('calls',[])[:3]]))
    for loop in scan.get('pid',{}).get('loops',[]):
        result.append(dict(id='pid:'+loop['id'],source_id=loop['id'],name=loop.get('name',loop['symbol']),instance=loop['symbol'],origin='PID 控制器候选',suggested='pid',loop_id=loop['id'],evidence=loop.get('evidence',[]),gains=loop['gains']))
    return result[:256]


def path(base,scan):return Path(base)/('template-panel-'+hashlib.sha256(scan['root'].encode()).hexdigest()[:12]+'-'+scan['project_hash'][:20]+'.json')


def load(base,scan):
    target=path(base,scan)
    if not target.is_file():return None
    panel=json.loads(target.read_text(encoding='utf-8'))
    return panel if panel.get('project_hash')==scan['project_hash'] and panel.get('root')==scan['root'] else None


def save(base,scan,panel):
    target=path(base,scan);temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(panel,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temporary.replace(target)


def build(base,scan,data):
    if data.get('project_hash')!=scan['project_hash']:raise ValueError('工程已切换，请刷新设备清单')
    for relative,expected in scan['files'].items():
        source=Path(scan['root'])/relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('源码已变化，请重新扫描后生成面板')
    selections=data.get('selections');known={c['id']:c for c in candidates(scan)}
    if not isinstance(selections,list) or not 1<=len(selections)<=64:raise ValueError('请选择 1–64 个设备或控制环')
    items=[];seen=set()
    import copy
    for choice in selections:
        if not isinstance(choice,dict) or choice.get('id') not in known or choice['id'] in seen:raise ValueError('设备选择已过期或重复')
        seen.add(choice['id']);candidate=known[choice['id']];template=choice.get('template');name=choice.get('name',candidate['name'])
        if template not in TEMPLATES:raise ValueError('未知面板模板')
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('显示名称应为 1–100 个字符')
        item={**candidate,'name':name.strip(),'template':template,'template_label':TEMPLATES[template]['label'],'fields':copy.deepcopy(TEMPLATES[template]['fields'])}
        for field in item['fields']:
            field['id']=candidate['id']+'::'+field['key'];field['hardware_writable']=False;field['data_source']='本机模拟'
            if template=='pid':
                value=candidate.get('gains',{}).get(field['key'],{}).get('value')
                if type(value) in (int,float) and math.isfinite(value):
                    field['initial']=value;field['min']=min(field['min'],value);field['max']=max(field['max'],value);field['initial_source']='源码扫描值（不是设备回读）'
                else:field['initial_source']='未确定源码值；模拟初值为 0'
        items.append(item)
    panel={'id':uuid.uuid4().hex,'project_hash':scan['project_hash'],'root':scan['root'],'platform':scan.get('platform'),
           'mode':'simulation','hardware_writable':False,'items':items,'values':{},'notice':NOTICE}
    save(base,scan,panel);return panel


def set_value(base,scan,data):
    panel=load(base,scan)
    if not panel or data.get('panel_id')!=panel['id'] or data.get('project_hash')!=panel['project_hash']:raise ValueError('面板已切换，请重新打开')
    field=next((f for item in panel['items'] for f in item['fields'] if f['id']==data.get('field')),None)
    if not field or field['access']!='rw':raise ValueError('这个模拟字段不能编辑')
    value=data.get('value')
    if field['type']=='bool':valid=type(value) is bool
    elif field['type']=='text':valid=isinstance(value,str) and len(value)<=80
    else:valid=type(value) in (int,float) and math.isfinite(value) and field['min']<=value<=field['max']
    if not valid:raise ValueError('数值格式或模拟范围无效')
    panel['values'][field['id']]=value;save(base,scan,panel)
    return {'value':value,'mode':'simulation','hardware_written':False,'notice':'已更新本机模拟值，未发送设备指令'}


def sample(panel,t):
    if type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=86400:raise ValueError('模拟时间无效')
    values={}
    for item in panel['items']:
        for i,field in enumerate(item['fields']):
            value=panel['values'].get(field['id'],field['initial']);profile=field['profile']
            if profile=='wave':value=min(10,field['max'])*math.sin(t*1.4+i*.9)
            elif profile=='counter':value=int(t*120)
            elif profile=='distance':value=500+100*math.sin(t)
            elif profile=='adc':value=round(2048+1000*math.sin(t))
            if field['type']=='number':value=max(field['min'],min(field['max'],value))
            values[field['id']]=value
    return {'panel_id':panel['id'],'project_hash':panel['project_hash'],'mode':'simulation','time':t,'values':values}
