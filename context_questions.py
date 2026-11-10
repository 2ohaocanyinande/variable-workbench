"""Bounded, project-grounded questions. Never executes model output."""
import hashlib
import json
import re
from pathlib import Path
import panel_templates

REGIONS={'screen':'源码屏幕预览','screen:content':'屏幕输出调用与变量','screen:buttons':'屏幕相关条件与按键','screen:settings':'屏幕驱动坐标与格式'}
MODULES={'serial':('串口连接','普通串口按固件波特率收发；打开串口不等于已获得变量读写协议。'),
         'records':('记录与分析','记录逐行数值与原始字节；支持曲线、导出和本地统计，t 的单位为秒。'),
         'analysis':('代码分析','本地提取变量和数值宏，按需发送有限上下文给模型解释用途；引用存在不等于数据流已证明。'),
         'rtos':('FreeRTOS','从配置和源码整理任务创建、同步对象及调度器入口，运行状态需结合实际固件核对。'),
         'panel':('控制面板','已适配的 ESP32 固件可通过桥接协议读写已确认字段。'),
         'pid':('控制环与调参','索引 PID 候选、源赋值与局部依赖，保存本机方案和补丁预览；不等于在线下发。'),
         'devices':('设备清单','本地接口线索加模型设备候选，可回溯源码。类型、参数归属与在线状态仍需核对。'),
         'screen':('源码屏幕预览','提取支持的绘图调用、字串及变量，填写假定值做静态预览，不运行完整固件。')}

def targets(scan,base):
    result=[{'id':'project','name':'当前工程 / 页面','evidence':[]}]
    result += [{'id':key,'name':label,'evidence':[]} for key,label in REGIONS.items()]
    result += [{'id':'module:'+key,'name':'软件模块：'+name,'help':help,'origin':'工作台功能说明，不是用户工程的硬件证据','evidence':[]} for key,(name,help) in MODULES.items()]
    for group in scan.get('screen_index',{}).get('groups',[]):
        evidence=[{'path':c['path'],'line':c['line'],'sha256':c['sha256']} for c in group['calls'][:6]]
        result.append({'id':'screen-group:'+group['id'],'name':'屏幕调用：'+group['name']+' · '+group['path'],'origin':'从源码提取的显示调用，未执行完整固件','evidence':evidence})
        for target in result[:5]:
            if target['id'] in REGIONS:target['evidence']=(target['evidence']+evidence)[:6]
    result += panel_templates.candidates(scan)
    snippets=scan.get('usage',{}).get('snippets',{})
    for candidate in scan.get('usage',{}).get('candidates',[]):
        result.append({'id':'usage:'+candidate['id'],'name':'变量／函数：'+candidate['symbol']+' · '+candidate['path']+':'+str(candidate['line']),
                       'origin':'本地代码索引（用途与执行条件待核对）','evidence':[snippets[sid] for sid in candidate.get('evidence_ids',[]) if sid in snippets]})
    for path,sha in scan['files'].items():
        if path.endswith(('.c','.cpp','.h')):
            anchors=[{'path':path,'line':1,'sha256':sha}]+[{'path':path,'line':c['line'],'sha256':sha} for c in scan.get('usage',{}).get('candidates',[]) if c['path']==path][:5]
            result.append({'id':'file:'+path,'name':'源码模块：'+path,'origin':'选定文件的有限代码片段，不是完整文件执行分析','evidence':anchors})
    for f in scan.get('fields',[])[:128]:
        result.append({'id':'native-field:'+f['id'],'name':f.get('module','')+' / '+f['label'],'evidence':f.get('evidence',[]),
                       'field':{k:f.get(k) for k in ('label','type','unit','access','data_source','symbol')},'origin':'工程已适配字段，实时状态仍需设备确认'})
    panel=panel_templates.load(base,scan)
    if panel:
        for item in panel['items']:
            for f in item['fields']:
                result.append({'id':'field:'+f['id'],'name':item['name']+' / '+f['label'],'evidence':item['evidence'],'template':item['template'],'field':f})
    return result

def packet(scan,base,data,mask):
    if data.get('project_hash')!=scan['project_hash']:raise ValueError('工程已切换，请重新选择提问对象')
    question=data.get('question','')
    if not isinstance(question,str) or not 1<=len(question.strip())<=2000:raise ValueError('问题应为 1–2000 个字符')
    target=next((t for t in targets(scan,base) if t['id']==data.get('target')),None)
    if not target:raise ValueError('提问对象不存在，请重新选择')
    if target['id'].startswith('file:'):
        name=target['id'][5:];raw=(Path(scan['root'])/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=scan['files'][name]:raise ValueError('源码已变化，请重新扫描后提问')
        code=mask(raw.decode('utf-8-sig',errors='replace'))
        definitions=[{'name':m[1],'line':code.count('\n',0,m.start())+1} for m in re.finditer(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t*]+)+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{',code)]
        requested=[f for f in definitions if re.search(r'(?<!\w)'+re.escape(f['name'])+r'(?!\w)',question)]
        anchors=requested[:6] or definitions[::max(1,len(definitions)//5)][:5]
        if anchors:target['evidence']=[{'path':name,'line':f['line'],'sha256':scan['files'][name]} for f in anchors]
        target['functions']=definitions[:80]
    snippets=[];seen=set();size=0
    for e in target.get('evidence',[])[:6]:
        name=e.get('path');line=e.get('line',1)
        if name not in scan['files'] or type(line) is not int:continue
        path=(Path(scan['root'])/name).resolve()
        if not path.is_relative_to(Path(scan['root']).resolve()):continue
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=scan['files'][name]:raise ValueError('源码已变化，请重新扫描后提问')
        lines=mask(raw.decode('utf-8-sig',errors='replace')).splitlines();start=max(0,line-7);key=(name,start)
        if key in seen:continue
        seen.add(key);code='\n'.join(lines[start:start+18])[:2400]
        if size+len(code.encode())>12000:break
        size+=len(code.encode());snippets.append({'path':name,'line':start+1,'sha256':scan['files'][name],'code':code})
    screen=data.get('screen',{})
    if not isinstance(screen,dict):screen={}
    # Do not send free-form display text, API credentials or arbitrary source paths.
    screen={k:v for k,v in screen.items() if (k=='size' and v in ['128x64','240x240','320x240']) or (k=='page' and v in ['menu','data','text','settings']) or (k=='theme' and v in ['green','white','amber']) or (k=='brightness' and type(v) is int and 20<=v<=100) or (k=='selected' and type(v) is int and 0<=v<3)}
    return {'project_hash':scan['project_hash'],'platform':scan.get('platform'),'target':{'id':target['id'],'name':target['name'],'origin':target.get('origin'),'template':target.get('template'),'field':target.get('field'),'help':target.get('help'),'functions':target.get('functions')},
            'question':question.strip(),'screen':screen,'snippets':snippets,
            'notice':'仅提供所选对象的有限源码上下文，不代表所有执行路径。屏幕预览来自支持的绘图调用；变量输入为假定值，不是实时读数。源码注释与字符串已隐藏。'}

def local_answer(p):
    tips={'screen':'请读取当前工程的绘图调用。若未检测到支持的调用，不生成虚构菜单。',
          'screen:buttons':'仅展示可提取的条件与赋值；复杂按键状态机和循环执行顺序尚未仿真。',
          'screen:content':'文字由支持的源码调用提取，变量可复制并填写预览值。填写预览值不会修改源码。',
          'screen:settings':'驱动坐标未经当前工程的实现核实时只列调用，不猜测画面。'}
    tip=p['target'].get('help') or tips.get(p['target']['id'],'这是当前工程中的候选或模板字段；模拟面板的可编辑状态不代表具备真实硬件写入能力。')
    return '【本地说明，未调用模型】\n当前对象：'+p['target']['name']+'。\n'+tip+'\n'+p['notice']+'\n'+('本次已定位 '+str(len(p['snippets']))+' 段相关代码，可展开查看。' if p['snippets'] else '当前对象没有可用源码片段，不能据此推断实际固件行为。')+'\n启用左下角 AI 助手后，再点击提问，才能获得针对问题的模型回答。'
