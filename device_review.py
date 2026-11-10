"""Read-only, source-grounded second pass for one device or interface."""
from collections import defaultdict, deque
from functools import lru_cache
import hashlib
from pathlib import Path
import re

from common_modules import signatures
from device_inventory import split_arguments
from screen_drivers import functions
from usage_analysis import balanced, masked


READ = re.compile(r'HAL_(?:I2C_(?:Mem_Read|Master_Receive)|SPI_(?:Receive|TransmitReceive)|UART_Receive)\w*')
WRITE = re.compile(r'HAL_(?:I2C_(?:Mem_Write|Master_Transmit)|SPI_Transmit|UART_Transmit)\w*')
CALL = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
NUMERIC_HINT = re.compile(r'[0-9°%]')
PHYSICAL_QUANTITY = re.compile(
    r'(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)?'
    r'(?:\s*(?:~|～|至|–)\s*[+-]?\d+(?:\.\d+)?)*\s*'
    r'(?:转/分钟|转每分钟|米/秒|毫米|厘米|米|摄氏度|度|牛[·⋅]?米|伏|安|%'
    r'|°(?:C)?|(?:m/s(?:²|\^2)?|mm|cm|km|m|rpm|r/min|N[·⋅]?m|mV|V|mA|A)(?![A-Za-z0-9_/]))',
    re.I,
)
MEASUREMENT = re.compile(r'距离|位移|转速|速度|角度|角速度|力矩|扭矩|温度|占空比|电压|电流')
INTERFACE_LABEL = re.compile(r'(?<![A-Za-z0-9_])(?:TIM_?\d+(?:_CH[1-4])?|TIM_CHANNEL_[1-4]|(?:USART|UART)_?\d+|(?:GPIO_PIN_|GPIO_Pin_|Pin_)\d+)(?![A-Za-z0-9_])')
BAUD_CLAIM = re.compile(r'(?:配置\s*)?波特率\s*(?:为|[：:=])?\s*(\d+)\s*(?:bps|baud)?', re.I)
DUTY_CLAIM = re.compile(r'(?:设定|设置)?\s*占空比\s*(?:/\s*(?:力矩|扭矩))?\s*[（(]?\s*(?:范围|量程)?\s*([+-]?\d{1,9})\s*[~～至]\s*([+-]?\d{1,9})\s*[）)]?')
PWM_CLAIM = re.compile(r'(?:设定|设置)?\s*(?:PWM\s*)?脉宽\s*[（(]?\s*(\d{1,9})\s*[~～至–]\s*(\d{1,9})\s*(us|μs|µs|微秒|计数)?\s*[）)]?',re.I)
DUTY_ASSIGN = re.compile(r'\b(\w+)\s*\[\s*(\w+)\s*\]\s*\.\s*duty\s*=\s*(\w+)\s*\(\s*(\w+)\s*\)\s*;')
LIMIT_BRANCH = re.compile(r'if\s*\(\s*(\w+)\s*([<>])\s*([+-]?\d{1,9}|\w+)\s*\)\s*\{\s*return\s+\3\s*;\s*\}')
MAX_BYTES = 12_000_000
MAX_FILES = 400


def review(scan, data):
    if not scan or data.get('project_hash') != scan['project_hash'] or data.get('root') != scan['root']:
        raise ValueError('工程已切换，请重新选择设备')
    endpoints = {e['id']:e for e in scan['inventory']['endpoints']}
    identifier = data.get('id')
    if not isinstance(identifier, str):
        raise ValueError('设备标识无效')
    device = None
    if data.get('scope') == 'device':
        device = next((d for d in (scan.get('device_report') or {}).get('devices', []) if d['id'] == identifier), None)
        ids = device['endpoint_ids'] if device else []
    elif data.get('scope') == 'interface':
        ids = [identifier]
    else:
        ids = []
    if not ids or any(eid not in endpoints for eid in ids):
        raise ValueError('当前清单中找不到该设备或接口')
    selected = [endpoints[eid] for eid in ids]
    anchors = {e['path'] for e in selected}
    hints = [h for e in selected for h in e.get('module_hints', [])]
    models = sorted({h['model'] for h in hints if h.get('strength') == 'driver_signature'})
    sources, partial = load_sources(scan, anchors)
    return inspect(scan, sources, selected, models, device, partial)


def load_sources(scan, anchors):
    root = Path(scan['root']).resolve()
    sources = {}
    total = 0
    paths = sorted((p for p in scan['files'] if Path(p).suffix.lower() in {'.c','.cpp','.h'}),
                   key=lambda p: (p not in anchors, Path(p).name.lower() != 'main.c', p))
    for name in paths:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            continue
        if len(sources) >= MAX_FILES or total + path.stat().st_size > MAX_BYTES:
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != scan['files'][name]:
            raise ValueError('源码已变化，请重新扫描工程后细检测')
        total += len(raw)
        try:
            sources[name] = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            sources[name] = raw.decode('gb18030', errors='replace')
    if anchors - sources.keys():
        raise ValueError('设备对应的源文件不在可核验范围内')
    return sources, len(sources) != len(paths)


def baud_evidence(selected, defs, evidence):
    readings = {}
    for ep in selected:
        handle = ep['handle']
        if ep['family'] != 'UART' or not re.fullmatch(r'[A-Za-z_]\w*',handle):
            continue
        for entries in defs.values():
            for fn in entries:
                init = re.search(r'\bHAL_UART_Init\s*\(\s*&'+re.escape(handle)+r'\s*\)',fn['body'])
                assignment = list(re.finditer(r'\b'+re.escape(handle)+r'\s*\.\s*Init\s*\.\s*BaudRate\s*=(?!=)\s*([^;]+);',fn['body']))
                if not init or not assignment:
                    continue
                for item in assignment:
                    value = item[1].strip()
                    line = fn['body_line']+fn['body'].count('\n',0,item.start())
                    proof = evidence(fn['path'],line,handle+' 波特率配置')
                    readings.setdefault(int(value) if re.fullmatch(r'[0-9]{1,9}',value) else None,proof)
        init, configure = defs.get('uart_init',[]), defs.get('uart_baud_config',[])
        if len(init)==len(configure)==1 and re.search(r'\buart_baud_config\s*\(\s*\w+\s*,\s*baud\s*\)',init[0]['body']) and '->BRR' in configure[0]['body'] and re.search(r'/\s*[^;\n]*\bbaud\b',configure[0]['body']):
            for call in ep['calls']:
                args = call['arguments']
                if call['api']=='uart_init' and len(args)>=2 and args[0].strip()==handle:
                    value = args[1].strip()
                    readings.setdefault(int(value) if re.fullmatch(r'[0-9]{1,9}',value) else None,
                                        evidence(ep['path'],call['line'],handle+' 波特率配置'))
    return readings


def requires_numeric_review(device):
    return any(priority_numeric_claim(PHYSICAL_QUANTITY.sub(' ',feature)) for feature in device.get('features',[]))


def priority_numeric_claim(text):
    text=text.strip(' \t,，;；。')
    return bool(BAUD_CLAIM.fullmatch(text.strip('()（）')) or
                DUTY_CLAIM.fullmatch(text) or PWM_CLAIM.fullmatch(text))


def literal_bound(token, sources, related, evidence):
    if re.fullmatch(r'[+-]?\d{1,9}',token): return int(token), []
    matches = [(path,i,m[1].strip()) for path in sorted(related)
               for i,line in enumerate(masked(sources[path]).splitlines(),1)
               if (m:=re.fullmatch(r'\s*#\s*define\s+'+re.escape(token)+r'\b(.*)',line))]
    if len(matches)==1 and re.fullmatch(r'[+-]?\d{1,9}',matches[0][2]):
        path,line,value=matches[0]
        return int(value),[evidence(path,line,'限幅常量 '+token)]
    return None,[]


def pwm_range_evidence(device, selected, sources, related, nodes, evidence):
    instance=device.get('instance','')
    if not re.fullmatch(r'[A-Za-z_]\w*',instance): return {}
    ranges={}
    for ep in selected:
        channel=re.fullmatch(r'TIM_CHANNEL_([1-4])',ep['channel'])
        if ep['family']!='PWM' or not channel: continue
        start=next((c for c in ep['calls'] if c['api']=='HAL_TIM_PWM_Start'),None)
        if not start: continue
        handle=re.escape(ep['handle'])
        bindings=[(timer,fn) for fn in nodes.values()
                  if re.search(r'\bHAL_TIM_PWM_Init\s*\(\s*&'+handle+r'\s*\)',fn['body'])
                  for timer in re.findall(r'\b'+handle+r'\s*\.\s*Instance\s*=\s*(TIM\d+)\s*;',fn['body'])]
        if len(bindings)!=1: continue
        timer,init=bindings[0]
        for fn in nodes.values():
            if fn['path']!=ep['path']: continue
            params=re.findall(r'\b(\w+)\s*(?:,|$)',fn['params'])
            if len(params)!=2: continue
            selector,value=map(re.escape,params)
            branch=r'if\s*\(\s*'+value+r'\s*([<>])\s*([+-]?\d{1,9}|\w+)\s*\)\s*'+value+r'\s*=\s*\2\s*;\s*'
            limits=re.match(r'\s*(?:'+branch+r')(?:'+branch.replace(r'\2',r'\4')+r')switch\s*\(\s*'+selector+r'\s*\)\s*\{',fn['body'])
            if not limits or {limits[1],limits[3]}!={'<','>'}: continue
            case=re.search(r'\bcase\s+'+re.escape(instance)+r'\s*:\s*'+timer+r'\s*->\s*CCR'+channel[1]+r'\s*=\s*'+value+r'\s*;\s*break\s*;',fn['body'][limits.end():])
            if not case: continue
            bounds={limits[1]:limits[2],limits[3]:limits[4]}
            lower,lo=literal_bound(bounds['<'],sources,related,evidence)
            upper,hi=literal_bound(bounds['>'],sources,related,evidence)
            if lower is None or upper is None or not 0<=lower<upper: continue
            line=fn['body_line']+fn['body'].count('\n',0,limits.end()+case.start())
            ranges[(lower,upper)]=[evidence(fn['path'],fn['line'],'PWM 原始值限幅'),
                                   *lo,*hi,evidence(fn['path'],line,'舵机编号写入比较寄存器'),
                                   evidence(init['path'],init['line'],'定时器实例配置'),
                                   evidence(ep['path'],start['line'],'PWM 通道启动')]
    return ranges


def duty_range_evidence(device, selected, sources, related, nodes, calls, evidence):
    instance = device.get('instance','')
    if not re.fullmatch(r'[A-Za-z_]\w*',instance): return {}
    selected_tx = {(ep['path'],c['line'],ep['handle']) for ep in selected if ep['family']=='UART'
                   for c in ep['calls'] if WRITE.fullmatch(c['api'])}
    tx = {key:(split_arguments(args)[1],evidence(key[0],line,'串口发送'))
          for key,entries in calls.items() for api,args,line,_ in entries
          if WRITE.fullmatch(api) and ',' in args and (key[0],line,args.split(',')[0].strip().lstrip('&')) in selected_tx}
    if not tx: return {}

    def payload_proof(target, args, field):
        frame, send=tx[target]
        arguments=split_arguments(args)
        slot=next((i for i,arg in enumerate(arguments) if field.fullmatch(arg)),None)
        sender=nodes[target]
        params=re.findall(r'\b(\w+)\s*(?:,|$)',sender['params'])
        if slot is None or slot>=len(params) or not re.fullmatch(r'\w+',frame): return None
        parameter=re.escape(params[slot])
        raw=re.search(r'\buint16_t\s+(\w+)\s*=\s*\(uint16_t\)\s*'+parameter+r'\s*;',sender['body'])
        if not raw: return None
        frame_slot=r'\b'+re.escape(frame)+r'\s*\[\s*(\d+)\s*\]\s*=\s*\(uint8_t\)\s*'
        variable=re.escape(raw[1])
        high=re.search(frame_slot+r'\(\(\s*'+variable+r'\s*>>\s*8\s*\)\s*&\s*0xFF\s*\)\s*;',sender['body'])
        low=re.search(frame_slot+r'\(\s*'+variable+r'\s*&\s*0xFF\s*\)\s*;',sender['body'])
        if not high or not low or int(high[1])+1!=int(low[1]): return None
        if sender['body_line']+sender['body'].count('\n',0,max(high.start(),low.start()))>=send['line']: return None
        return send

    ranges = {}
    driver_paths={path for path,_,_ in selected_tx}
    for key,fn in nodes.items():
        if key[0] not in driver_paths: continue
        for assign in DUTY_ASSIGN.finditer(fn['body']):
            store,index,clamp,value=assign.groups()
            params=re.findall(r'\b(\w+)\s*(?:,|$)',fn['params'])
            if params!=[index,value]: continue
            caller=next((evidence(origin[0],line,'调用绑定电机 '+instance)
                         for origin,entries in calls.items() for _,args,line,target in entries
                         if target==key and args.split(',')[0].strip()==instance),None)
            if not caller: continue
            output=re.compile(re.escape(store)+r'\s*\[\s*'+re.escape(instance)+r'\s*\]\s*\.\s*duty')
            encoded=next(((evidence(delegate[0],line,'电机字段进入发送帧'),send)
                          for _,_,_,delegate in calls[key] if delegate
                          for _,args,line,target in calls[delegate]
                          if target in tx and (send:=payload_proof(target,args,output))),None)
            clamp_key=next((target for api,_,_,target in calls[key] if api==clamp and target),None)
            if not encoded or not clamp_key: continue
            body=nodes[clamp_key]['body']
            branches=list(LIMIT_BRANCH.finditer(body))
            if len(branches)!=2: continue
            first,second=branches
            parameter=first[1]
            if second[1]!=parameter or {first[2],second[2]}!={'<','>'}: continue
            if not re.fullmatch(r'\s*'+re.escape(first[0])+r'\s*'+re.escape(second[0])+r'\s*return\s+'+re.escape(parameter)+r'\s*;\s*',body): continue
            if not re.fullmatch(r'\w+\s+'+re.escape(parameter),nodes[clamp_key]['params'].strip()): continue
            limits={branch[2]:literal_bound(branch[3],sources,related,evidence) for branch in branches}
            lower,low_proof=limits['<']
            upper,high_proof=limits['>']
            if lower is None or upper is None or lower>=upper: continue
            ranges[(lower,upper)]=[caller,evidence(key[0],fn['body_line']+fn['body'].count('\n',0,assign.start()),'写入限幅后的电机指令'),
                                   evidence(*clamp_key,'指令限幅函数'),*low_proof,*high_proof,*encoded]
    return ranges


def review_numeric_claims(device, selected, defs, evidence, duty_ranges, pwm_ranges):
    features = (device or {}).get('features',[])
    labels = {label:evidence(ep['path'],ep['calls'][0]['line'],'已绑定接口 '+label)
              for ep in selected if ep['calls'] for label in (ep['handle'],ep['channel'])
              if INTERFACE_LABEL.fullmatch(label)}
    baud = None
    result = []
    for feature in features:
        raw_claim = PHYSICAL_QUANTITY.sub(' ',feature)
        if not NUMERIC_HINT.search(raw_claim): continue
        proofs = [labels[label] for label in INTERFACE_LABEL.findall(raw_claim) if label in labels]
        remaining = INTERFACE_LABEL.sub(lambda m:' ' if m[0] in labels else m[0],raw_claim)
        status, reason = 'pending', '还缺少能核对原始数值、字段格式或接口归属的源码依据。'
        normalized=remaining.strip(' \t,，;；。')
        claim = BAUD_CLAIM.fullmatch(normalized.strip('()（）'))
        duty_claim = DUTY_CLAIM.fullmatch(normalized)
        pwm_claim = PWM_CLAIM.fullmatch(normalized)
        if not NUMERIC_HINT.search(remaining) and proofs:
            status, reason = 'verified', '已核对该功能中的接口编号。'
        elif claim:
            if baud is None: baud=baud_evidence(selected,defs,evidence)
            value=int(claim[1])
            if baud.keys()=={value}:
                proofs.append(baud[value])
                status, reason = 'verified', '该设备接口的源码波特率配置与识别结果一致。'
            elif baud and None not in baud and value not in baud:
                proofs.extend(baud.values())
                status, reason = 'conflict', '对应接口的源码波特率为 '+ '、'.join(map(str,sorted(baud)))+'，与识别结果不同。'
            elif baud:
                proofs.extend(baud.values())
                reason='接口存在多处配置或使用了表达式，需要确认实际生效的赋值。'
        elif duty_claim:
            ranges=duty_ranges()
            if len(ranges)==1:
                limits,anchors=next(iter(ranges.items()))
                proofs.extend(anchors)
                if limits==tuple(map(int,duty_claim.groups())):
                    status,reason='verified','已核对对应电机的源码指令限幅，限幅后的值进入串口发送帧。'
                else:
                    status,reason='conflict',f'对应电机的源码指令限幅为 {limits[0]}～{limits[1]}，与识别结果不同。'
            else:
                reason='未能唯一定位该电机的指令限幅与发送路径。'
        elif pwm_claim:
            ranges=pwm_ranges()
            if len(ranges)==1:
                limits,anchors=next(iter(ranges.items()))
                proofs.extend(anchors)
                if limits==tuple(map(int,pwm_claim.groups()[:2])):
                    status,reason='verified',f'已核对该通道的 PWM 比较值限幅 {limits[0]}～{limits[1]} 计数。'
                elif not pwm_claim[3] or pwm_claim[3]=='计数':
                    status,reason='conflict',f'该通道实际限幅为 {limits[0]}～{limits[1]} 计数。'
                else:
                    reason=f'该通道限幅为 {limits[0]}～{limits[1]} 计数，需确认定时器时钟换算后再比较。'
        result.append({'feature':feature,'status':status,'reason':reason,'evidence':proofs,
                       'priority':priority_numeric_claim(normalized) or status=='conflict'})
    return result


def optional_unit_claims(device):
    result = []
    for feature in (device or {}).get('features',[]):
        quantities = [m[0] for m in PHYSICAL_QUANTITY.finditer(feature)]
        pulse=PWM_CLAIM.fullmatch(feature.strip())
        if pulse and pulse[3] and pulse[3]!='计数':
            result.append({'feature':feature,'reason':'默认仅核对比较寄存器计数。微秒换算需另外核对定时器输入时钟和预分频。'})
            continue
        if quantities:
            reason = '若要确认 '+ '、'.join(quantities)+'，可另外查看换算公式、标定数据或设备协议。'
        elif MEASUREMENT.search(feature):
            reason = '可以先按原始量查看。若需要物理单位，可另外核对换算比例或设备协议。'
        else:
            continue
        result.append({'feature':feature,'reason':reason})
    return result


def inspect(scan, sources, selected, models, device, partial):
    defs = functions(sources)
    nodes = {(f['path'], f['line']): f for entries in defs.values() for f in entries}
    calls = {}
    edges = defaultdict(list)
    def evidence(path, line, role):
        return dict(path=path, line=line, role=role, sha256=scan['files'][path])

    for key, fn in nodes.items():
        entries = []
        body = fn['body']
        line_base = sources[fn['path']].count('\n', 0, fn['opening']+1)+1
        fn['body_line'] = line_base
        for match in CALL.finditer(body):
            api = match[1]
            if api not in defs and not READ.fullmatch(api) and not WRITE.fullmatch(api):
                continue
            line = line_base + body.count('\n', 0, match.start())
            prefix = body[body.rfind('\n', 0, match.start())+1:match.start()]
            if re.match(r'\s*(?:#|extern\b)', prefix):
                continue
            close = balanced(body, match.end()-1)
            if close is None:
                continue
            definitions = defs.get(api, [])
            local = [f for f in definitions if f['path'] == fn['path']]
            targets = local or [f for f in definitions if not sources[f['path']][f['start']:f['opening']].lstrip().startswith('static ')]
            target = (targets[0]['path'],targets[0]['line']) if len(targets) == 1 else None
            entries.append((api, body[match.end():close], line, target))
            if target:
                edges[key].append((target,line))
        calls[key] = entries

    @lru_cache(maxsize=2048)
    def trace(start, first_api, depth=5):
        pending = deque([(start,0)])
        seen = set()
        while pending:
            node, level = pending.popleft()
            if node in seen or level > depth:
                continue
            seen.add(node)
            for api, args, line, target in calls[node]:
                if first_api.fullmatch(api):
                    return evidence(node[0],line,api)
                if target:
                    pending.append((target,level+1))
        return None

    paths = {}
    if len(defs.get('main', [])) == 1:
        main = defs['main'][0]
        start = (main['path'],main['line'])
        paths[start] = []
        pending = deque([start])
        while pending:
            node = pending.popleft()
            if len(paths[node]) >= 10:
                continue
            for target,line in edges[node]:
                if target not in paths:
                    paths[target] = paths[node]+[evidence(node[0],line,nodes[node]['name']+' → '+nodes[target]['name'])]
                    pending.append(target)

    driver_files = {e['path'] for e in selected}
    related = set(driver_files)
    for path in driver_files:
        for include in re.findall(r'^\s*#\s*include\s*"([^"\n]+)"', sources[path], re.M):
            candidates = [name for name in sources if Path(name).name == Path(include).name]
            if len(candidates) == 1:
                related.add(candidates[0])
    driver_text = '\n'.join(masked(sources[path]) for path in sorted(related))
    selected_calls = ' '.join(c['api']+' '+' '.join(c['arguments']) for e in selected for c in e['calls'])
    models = sorted(set(models) | {s[0] for s in signatures(selected_calls)})
    imu963 = (bool({'LSM6DSR','QMC5883L'} & set(models)) or 'IMU963RA_' in selected_calls) and any(
        f['path'] in driver_files and f['name'].startswith('IMU963RA_') for f in nodes.values())
    if re.search(r'\bQMC5883L_\w+', selected_calls) or imu963 and re.search(r'\bQMC5883L_\w+', driver_text):
        models = sorted(set(models) | {'QMC5883L'})

    components = []
    for model in models:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',model):
            continue
        tag = re.compile(r'(?<![A-Za-z0-9])'+re.escape(model)+r'(?=_|\b)',re.I)
        specs = [('加速度','GetAccel'),('陀螺仪','GetGyro')] if model == 'LSM6DSR' and imu963 else [(None,'GetMag' if model == 'QMC5883L' and imu963 else '')]
        for signal, entry in specs:
            component = {'name':model+(' · '+signal if signal else ''), 'definitions':[], 'initialization':[], 'sampling':[]}
            for path in sorted(related):
                for i,line in enumerate(masked(sources[path]).splitlines(),1):
                    if re.match(r'\s*#\s*define\b',line) and tag.search(line):
                        component['definitions'].append(evidence(path,i,'型号相关宏'))
                        if len(component['definitions']) >= 3:
                            break
                if len(component['definitions']) >= 3:
                    break
            for key,fn in nodes.items():
                if key[0] not in driver_files:
                    continue
                name = fn['name']
                entry_match = bool(entry and name.casefold() == ('IMU963RA_'+entry).casefold())
                chip_function = bool(tag.search(name))
                linked = [call for call in calls[key] if tag.search(call[0]+' '+call[1])]
                for kind, matcher in (('initialization',WRITE),('sampling',READ)):
                    named = chip_function and bool(re.search(r'init|config' if kind=='initialization' else r'read|get|sample',name,re.I))
                    if kind=='initialization' and imu963 and name.casefold()=='imu963ra_init' and linked:
                        named = True
                    if kind=='sampling' and signal and not entry_match:
                        continue
                    match = next((evidence(key[0],line,api) if matcher.fullmatch(api) else trace(target,matcher)
                                  for api,args,line,target in linked
                                  if matcher.fullmatch(api) or target and trace(target,matcher)), None)
                    if not (named or kind=='sampling' and entry_match or match):
                        continue
                    if not match and (named or kind=='sampling' and entry_match) and not (model=='QMC5883L' and entry_match):
                        match = trace(key,matcher)
                    # A shared IMU entry or a status/identity read alone cannot establish a magnetometer sample.
                    if kind=='sampling' and model=='QMC5883L' and not any(
                        re.search(r'\bQMC5883L_(?:\w*_)?(?:OUT\w*|DATA_[XYZ]\w*|[XYZ]_(?:OUT|LSB|MSB)\w*)\b', args, re.I)
                        for api,args,line,target in linked if READ.fullmatch(api) or target
                    ):
                        match = None
                    component[kind].append({'entry':evidence(*key,name), 'operation':match,
                                            'chain':paths.get(key,[]), 'from_main':key in paths})
            for kind in ('initialization','sampling'):
                component[kind] = sorted(component[kind], key=lambda item:(not bool(item['operation']),not bool(item['chain'])))[:3]
            components.append(component)
    conflicts = []
    if device and device.get('kind') in {'servo','motor'} and models and all(e['family']=='MODULE' for e in selected):
        conflicts.append('初检归为电机或舵机，但所选模块接口出现传感器驱动标识，请核对类别。')
    return {'name':device['name'] if device else selected[0]['handle'], 'components':components,
            'interfaces':[evidence(e['path'],c['line'],c['api']) for e in selected for c in e['calls'][:2]][:8],
            'conflicts':conflicts, 'numeric_claims':review_numeric_claims(device,selected,defs,evidence,
                lru_cache(maxsize=1)(lambda: duty_range_evidence(device,selected,sources,related,nodes,calls,evidence)),
                lru_cache(maxsize=1)(lambda: pwm_range_evidence(device,selected,sources,related,nodes,evidence))),
            'unit_claims':optional_unit_claims(device),
            'files_checked':len(sources), 'partial':partial,
            'scope':'静态源码复核。调用链可能受条件编译、调度及运行条件影响，硬件状态需实测。'}
