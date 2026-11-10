"""Group code endpoints; physical device identities require evidence-backed AI review."""
import hashlib
import json
from pathlib import Path
import re

from usage_analysis import balanced, masked, safe_excerpt
from common_modules import signatures, hints, enrich
from code_evidence import quote_exists, tokens


# Bind register access to a declared peripheral type before interpreting it.
# Many unrelated STM32 peripherals have fields named CR1 or DR.
REGISTER_INTERFACES = {
    'TIM': ('PWM', r'TIM_?\d+', r'(?:TIM\d+_CH|TIM_CHANNEL_)[1-4]', r'CCR[1-4]\s*=(?!=)'),
    'GPIO': ('GPIO', r'GPIO_?[A-K]', r'(?:Pin_|GPIO_Pin_|GPIO_PIN_)(?:[0-9]|1[0-5])', r'(?:CR[HL]|MODER|IDR|ODR|BSRR|BRR)\b'),
    'USART': ('UART', r'(?:USART|UART)_?\d+', None, r'(?:BRR|CR1|DR|TDR|RDR)\b'),
    'ADC': ('ADC', r'ADC_?\d+', r'(?:ADC_Channel_|ADC_CHANNEL_)\d+', r'(?:SQR[1-5]|CHSELR|DR)\b'),
}
REGISTER_ACCESS = re.compile(r'\b(\w+)\s*(?:\[\s*(\w+)\s*\])?\s*->\s*(\w+)')
SOFTWARE_INTERFACES = {
    'I2C_Init': ('I2C', '软件 I2C', r'\b(\w+)\s*\([^;]*SCL[^;]*;[\s\S]*\b\1\s*\([^;]*SDA'),
    'OLED_Init': ('DISPLAY', 'OLED', r'\bOLED_(?:I2C_Init|WriteCommand)\s*\([\s\S]*\bOLED_Clear\s*\('),
}


def split_arguments(text):
    result, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char in '([{': depth += 1
        elif char in ')]}': depth -= 1
        elif char == ',' and depth == 0:
            result.append(text[start:i].strip()); start = i+1
    result.append(text[start:].strip())
    return result


def register_binding(body, parameters, tables):
    typed_pointers = {}
    parameter_indices = {}
    for index, parameter in enumerate(split_arguments(parameters)):
        name = re.search(r'\b(\w+)$', parameter)
        if not name: continue
        parameter_indices[name[1]] = index
        pointer = re.search(r'\b(\w+)_TypeDef\s*\*', parameter)
        if pointer: typed_pointers[name[1]] = pointer[1]
    operations = {}
    for access in REGISTER_ACCESS.finditer(body):
        base, selector, register = access.groups()
        peripheral = tables.get(base) if selector else typed_pointers.get(base)
        argument = parameter_indices.get(selector or base)
        if peripheral in REGISTER_INTERFACES and argument is not None:
            family, handle_pattern, channel_pattern, operation = REGISTER_INTERFACES[peripheral]
            if re.match(operation, body[access.start(3):]):
                operations.setdefault((family, argument, handle_pattern, channel_pattern), []).append(access)
        elif base == 'EXTI' and not selector and register == 'IMR':
            statement = body[access.end():].split(';', 1)[0]
            pin = re.match(r'\s*\|=\s*1[uU]?\s*<<\s*\(?\s*(\w+)\b', statement)
            if pin and pin[1] in parameter_indices:
                operations.setdefault(('EXTI', parameter_indices[pin[1]], r'EXTI_P[A-K](?:[0-9]|1[0-5])', None), []).append(access)
    if len(operations) != 1: return None
    (family, argument, handle_pattern, channel_pattern), accesses = next(iter(operations.items()))
    channel_positions = {}
    if family == 'PWM':
        for access in accesses:
            channel_positions.setdefault(access[3][-1], access.start())
    fixed_channel = 'CH'+next(iter(channel_positions)) if len(channel_positions) == 1 else ''
    referenced = {index for name, index in parameter_indices.items()
                  if index != argument and re.search(r'\b'+re.escape(name)+r'\b', body)}
    return (family, argument, handle_pattern, channel_pattern, fixed_channel, referenced,
            accesses[0].start(), channel_positions)


def inventory(root, texts, hashes):
    endpoints, modules = {}, {}
    wrapper_drivers = {}
    wrapper_implementations = {}
    definitions_pattern = re.compile(r'(?m)^[ \t]*(?:\w+[ \t*]+)+(\w+)\s*\(([^;{}]*)\)\s*\{')
    sources = {p: masked(t) for p, t in texts.items() if p.suffix in {'.c', '.cpp'}}
    table_types = {}
    for code in sources.values():
        for kind, table in re.findall(r'\b(\w+)_TypeDef\s*\*\s*(\w+)\s*\[\s*\d*\s*\]', code):
            table_types.setdefault(table, set()).add(kind)
    tables = {table: next(iter(types)) for table, types in table_types.items() if len(types) == 1}
    definitions = {}
    wrapper_definition_sites = set()
    for source, code in sources.items():
        for match in definitions_pattern.finditer(code):
            name = match[1]
            definitions.setdefault(name, []).append(source)
            start = match.end()-1
            end = balanced(code, start, '{', '}')
            if end is None: continue
            body = code[start+1:end]
            binding = register_binding(body, match[2], tables)
            if not binding and name in SOFTWARE_INTERFACES:
                family, label, pattern = SOFTWARE_INTERFACES[name]
                proof = re.search(pattern, body)
                if proof: binding = family, None, None, None, label, set(), proof.start(), {}
            if binding:
                wrapper_definition_sites.add((source, match.start(1)))
                offset, channel_offsets = binding[-2:]
                line = code.count('\n', 0, start+1+offset)+1
                channel_lines = {channel: code.count('\n', 0, start+1+pos)+1
                                 for channel, pos in channel_offsets.items()}
                wrapper_implementations[name] = source, binding[:-2], line, channel_lines
    wrappers = {name: item for name, item in wrapper_implementations.items()
                if definitions[name] == [item[0]]}
    driver_sources = {item[0] for item in wrappers.values()}
    apis = r'HAL_TIM_PWM_Start|__HAL_TIM_SET_COMPARE|HAL_TIM_Encoder_(?:Init|Start(?:_IT|_DMA)?)|__HAL_TIM_(?:GET|SET)_COUNTER|TIM_GetCounter|TIM_SetCompare[1-4]|HAL_UART_(?:Transmit|Receive)(?:_DMA|_IT)?|HAL_ADC_(?:GetValue|Start_DMA)|HAL_GPIO_(?:Read|Write)Pin|GPIO_(?:SetBits|ResetBits|WriteBit)|ADC_GetConversionValue|USART_(?:SendData|ReceiveData)|HAL_I2C_(?:Master_(?:Transmit|Receive)|Mem_Read)(?:_DMA|_IT)?|HAL_SPI_(?:Transmit|Receive|TransmitReceive)(?:_DMA|_IT)?'
    if wrappers: apis += '|' + '|'.join(wrappers)
    calls = re.compile(r'\b('+apis+r')\s*\(')
    for path, text in texts.items():
        if path not in sources: continue
        code = sources[path]
        relative = path.relative_to(root).as_posix()
        pin_switches = []
        if path in driver_sources:
            for selector in re.finditer(r'\bswitch\s*\(\s*\w+\s*\)\s*\{', code):
                end = balanced(code, selector.end()-1, '{', '}')
                if end is not None: pin_switches.append((selector.end(), end))
        for match in calls.finditer(code):
            end = balanced(code, match.end()-1)
            if end is None: continue
            args = split_arguments(code[match.end():end])
            if not args: continue
            api = match[1]
            handle = re.sub(r'\s+', '', args[0]).lstrip('&')
            channel = ''
            status = '接口线索 · 设备类型待识别'
            if api in wrappers:
                if (path, match.start(1)) in wrapper_definition_sites: continue
                driver, binding, register_line, channel_lines = wrappers[api]
                family, argument, handle_pattern, channel_pattern, fixed_channel, referenced = binding
                # Pin alternatives inside a low-level driver's setup switch
                # are not project-selected pins. Index the upper-level call.
                if family == 'GPIO' and any(start <= match.start() < end for start, end in pin_switches):
                    continue
                if argument is not None:
                    if argument >= len(args): continue
                    handle = re.sub(r'\s+', '', args[argument]).lstrip('&')
                    if not re.fullmatch(handle_pattern, handle): continue
                    candidates = [value for i, value in enumerate(args)
                                  if i in referenced and channel_pattern and re.fullmatch(channel_pattern, value)]
                    if len(candidates) > 1: continue
                    channel = candidates[0] if candidates else fixed_channel
                    if channel_pattern and not channel: continue
                    if family == 'PWM':
                        if channel[-1] not in channel_lines: continue
                        register_line = channel_lines[channel[-1]]
                elif args != ['']:
                    continue
                else:
                    handle = fixed_channel
                    args = []
                status = 'OLED 显示屏 · 初始化调用' if family == 'DISPLAY' else '自定义驱动接口 · 调用已定位'
            elif not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?', handle):
                continue
            elif api.startswith('HAL_TIM_Encoder_'):
                family = 'ENCODER'
            elif api in {'__HAL_TIM_GET_COUNTER','__HAL_TIM_SET_COUNTER','TIM_GetCounter'}:
                family = 'COUNTER'
            elif api in {'HAL_TIM_PWM_Start', '__HAL_TIM_SET_COMPARE'}:
                if len(args) < 2: continue
                channel = args[1]
                family = 'PWM'
            elif api.startswith('TIM_SetCompare'):
                channel = 'CH'+api[-1]; family = 'PWM'
            elif api.startswith(('HAL_UART_', 'USART_')): family = 'UART'
            elif api.startswith(('HAL_ADC_', 'ADC_')): family = 'ADC'
            elif api.startswith(('HAL_GPIO_', 'GPIO_')):
                family = 'GPIO'
                if len(args) >= 2: channel = args[1]
            elif api.startswith('HAL_I2C_'):
                family = 'I2C'
                if len(args) >= 2: channel = args[1]  # address expression; no assumed physical model
            else: family = 'SPI'
            if len(channel) > 100: continue
            # Same interface across files is retained as separate module contexts;
            # physical merging is deferred to the model instead of guessed.
            key = f'{relative}::{family}::{handle}::{channel}'
            item = endpoints.setdefault(key, {'id': key, 'family': family, 'handle': handle,
                                              'channel': channel, 'path': relative, 'calls': [],
                                              'status': status})
            line = text.count('\n', 0, match.start())+1
            item['calls'].append({'api': api, 'line': line, 'arguments': args,
                                  'sha256': hashes[relative]})
            if api=='HAL_GPIO_ReadPin':
                prefix=code[max(0,code.rfind('\n',0,match.start())+1):match.start()]
                sampled=re.search(r'\b(\w+)\s*\.\s*val\s*=\s*$',prefix)
                if sampled:
                    symbol=re.escape(sampled[1])
                    member=r'\b'+symbol+r'\s*\.\s*'
                    if all(re.search(r'\bif\s*\(\s*'+member+rf'val\s*==\s*{now}\s*&&\s*'+member+
                                     rf'last\s*==\s*{before}\s*\)\s*\{{?\s*'+member+field+r'\s*=\s*1\s*;',code)
                           for field,now,before in [('down',0,1),('up',1,0)]) and re.search(member+r'last\s*=\s*'+member+r'val\s*;',code):
                        item['button_symbol']=sampled[1]
            modules[relative] = path
            if api in wrappers:
                wrapper_drivers.setdefault(relative, set()).add(driver)
                driver_path = driver.relative_to(root).as_posix()
                proof = {'path': driver_path, 'line': register_line, 'sha256': hashes[driver_path],
                         'role': '驱动实现' if argument is None else '底层寄存器访问'}
                evidence = item.setdefault('register_evidence', [])
                if proof not in evidence: evidence.append(proof)
        # Vendor/module APIs may wrap the bus in another file. Preserve their
        # application entry even when there is no HAL call at this call site.
        signature_text = code+'\n'+path.name+'\n'+'\n'.join(re.findall(r'^\s*#\s*include\s*"([^"\n]+)"', text, re.M))
        matched = signatures(signature_text)
        for model, category, source, token in matched:
            call = next((m for m in re.finditer(r'\b(\w+)\s*\(', code) if any(s[0] == model for s in signatures(m[1]))), None)
            if call is None: continue
            key = f'{relative}::MODULE::{model}'
            endpoints[key] = {'id': key, 'family': 'MODULE', 'handle': model, 'channel': '', 'path': relative,
                              'calls': [{'api': call[1], 'line': text.count('\n', 0, call.start())+1,
                                         'arguments': [], 'sha256': hashes[relative]}],
                              'status': category+' · 驱动线索'}
            modules[relative] = path
    # Object aliases of explicitly defined bit-band GPIO macros are I/O clues.
    # Require unambiguous definitions and direct header inclusion, not a name guess.
    bases={};aliases={}
    for header,text in texts.items():
        if header.suffix!='.h':continue
        for m in re.finditer(r'^\s*#\s*define\s+(P[A-G](?:out|in))\(\w+\)\s+BIT_ADDR\(GPIO[A-G]_(?:ODR|IDR)_Addr\s*,\s*\w+\)',masked(text),re.M):bases.setdefault(m[1],[]).append(header)
        for m in re.finditer(r'^\s*#\s*define\s+(\w+)\s+(P[A-G](?:out|in))\((\d+)\)',masked(text),re.M):aliases.setdefault(m[1],[]).append((header,m[2]))
    for path,text in texts.items():
        if path.suffix not in {'.c','.cpp'}:continue
        code=masked(text);included=re.findall(r'^\s*#\s*include\s*"([^"\n]+)"',text,re.M)
        for alias,owners in aliases.items():
            if len(owners)!=1:continue
            header,base=owners[0]
            if len(bases.get(base,[]))!=1 or header.name not in included:continue
            uses=list(re.finditer(r'\b'+re.escape(alias)+r'\b',code))
            if not uses:continue
            relative=path.relative_to(root).as_posix();key=f'{relative}::MACRO_IO::{alias}'
            endpoints[key]={'id':key,'family':'MACRO_IO','handle':alias,'channel':'','path':relative,
                            'calls':[{'api':'宏 I/O 访问','line':text.count('\n',0,m.start())+1,'arguments':[alias],'sha256':hashes[relative]} for m in uses[:4]],
                            'status':'位带式宏 I/O 线索；实际引脚和设备用途待核对'}
            modules[relative]=path
    # Include implementation and directly included project headers. Constants,
    # enum IDs, frame encoding, setters/getters stay together, within a fixed budget.
    snippets = {}
    truncated = False
    excluded_tables = []
    # Bring in callers of project bus wrappers, so a generic read_register()
    # helper doesn't hide the actual sensor's register operations from the AI.
    for relative, path in modules.items():
        related = [path, *sorted(wrapper_drivers.get(relative, set()) - {path})]
        frontier = list(related)
        # gpio.c -> gpio.h -> main.h is a normal CubeMX chain. Restrict this
        # traversal to unambiguous project headers; do not attach every header.
        for _ in range(3):
            following = []
            for owner in frontier:
                for name in re.findall(r'^\s*#\s*include\s*"([^"\n]+)"', texts[owner], re.M):
                    candidates = [p for p in texts if p.suffix == '.h' and (p == owner.parent/name or p.name == name)]
                    if len(candidates) == 1 and candidates[0] not in related:
                        related.append(candidates[0]); following.append(candidates[0])
            frontier = following
        evidence_ids = []
        for source in dict.fromkeys(related):
            code = safe_excerpt(texts[source])
            if source.suffix == '.h' and re.search(r'font|bitmap|image|glyph|logo', source.stem, re.I) and len(re.findall(r'\b(?:0x[0-9a-fA-F]+|\d+)\b', code)) >= 128:
                excluded_tables.append(source.relative_to(root).as_posix())
                continue
            lines = code.splitlines()
            if len(lines) > 400: truncated = True
            for start in range(0, min(len(lines), 400), 60):
                chunk = '\n'.join(f'{i+1}: {lines[i]}' for i in range(start, min(start+60, len(lines), 400)))
                sid = f"{source.relative_to(root).as_posix()}:{start+1}-{min(start+60,len(lines),400)}"
                if len(chunk.encode()) > 10000: continue
                snippets[sid] = {'id': sid, 'path': source.relative_to(root).as_posix(), 'line': start+1,
                                 'role': '设备驱动及关联声明（字符串与注释已隐藏）',
                                 'sha256': hashes[source.relative_to(root).as_posix()], 'code': chunk}
                evidence_ids.append(sid)
        public = [name for name, owners in definitions.items() if owners == [path]]
        callers_added = 0
        for caller, text in texts.items():
            if caller == path or caller.suffix not in {'.c', '.cpp'}: continue
            code = masked(text)
            matches = [m for name in public for m in re.finditer(r'\b'+re.escape(name)+r'\s*\(', code)]
            if not matches: continue
            if callers_added >= 2:
                truncated = True
                continue
            callers_added += 1
            lines = safe_excerpt(text).splitlines()
            for match in matches[:2]:
                line = text.count('\n', 0, match.start())
                first, last = max(0,line-10), min(len(lines),line+16)
                sid = f'{caller.relative_to(root).as_posix()}:{first+1}-{last}'
                snippets[sid] = {'id': sid, 'path': caller.relative_to(root).as_posix(), 'line': line+1,
                                 'role': '驱动／总线包装函数的上层调用',
                                 'sha256': hashes[caller.relative_to(root).as_posix()],
                                 'code': '\n'.join(f'{i+1}: {lines[i]}' for i in range(first,last))}
                evidence_ids.append(sid)
        for endpoint in endpoints.values():
            if endpoint['path'] == relative: endpoint['evidence_ids'] = evidence_ids
    # Counter reads belonging to a started encoder share its endpoint; a plain
    # timer counter without encoder-mode evidence remains COUNTER.
    for key, entry in list(endpoints.items()):
        if entry['family'] != 'COUNTER': continue
        target = next((e for e in endpoints.values() if e['family']=='ENCODER' and e['path']==entry['path'] and e['handle']==entry['handle']), None)
        if target:
            target['calls'].extend(entry['calls'])
            del endpoints[key]
    for endpoint in endpoints.values():
        endpoint['source_key'] = endpoint['id']
        endpoint['id'] = 'ep_'+hashlib.sha256(endpoint['id'].encode()).hexdigest()[:12]
    # GPIO initialization masks and bit-banged drivers may reference the same
    # physical pins in different files. Link evidence only for the same port and
    # a proven subset of literal GPIO_PIN_n bits; never share all project code.
    def pin_set(e):
        if e['family']!='GPIO' or not re.fullmatch(r'GPIO_PIN_\d+(?:\s*\|\s*GPIO_PIN_\d+)*',e['channel'].strip()): return set()
        return set(re.findall(r'GPIO_PIN_\d+',e['channel']))
    for endpoint in endpoints.values():
        pins=pin_set(endpoint)
        if not pins: continue
        for other in endpoints.values():
            other_pins=pin_set(other)
            if other is not endpoint and other['handle']==endpoint['handle'] and other_pins and other_pins <= pins:
                endpoint['evidence_ids']=list(dict.fromkeys(endpoint['evidence_ids']+other['evidence_ids']))
    for endpoint in endpoints.values():
        endpoint['module_hints'] = hints(endpoint, snippets)
    if len(endpoints) > 128: truncated = True
    return {'endpoints': list(endpoints.values())[:128], 'snippets': snippets, 'truncated': truncated,
            'excluded_tables': sorted(set(excluded_tables)),
            'notice': '同一串口可能连接多个设备；PWM 也可能驱动灯。接口数量不是物理设备数量。'}


def packet(scan):
    data = scan['inventory']
    result = {'endpoints': [], 'snippets': {}, 'project': {'platform': scan['platform']},
              'privacy': '字符串、字符常量和注释已隐藏。', 'scope': '按代码证据识别设备类型、独立实例及可配置功能，不推测实际接线或在线状态。'}
    originals = {e['id']: e for e in data['endpoints']}
    wire_ids = {sid:'s_'+hashlib.sha256(sid.encode()).hexdigest()[:12] for sid in data['snippets']}
    def fits(value, limit=59500): return len(json.dumps(value, ensure_ascii=False).encode()) <= limit
    for e in data['endpoints']:
        item = {k:e[k] for k in ('id','family','handle','channel','path','status')}
        item.update(calls=e['calls'][:4], evidence_ids=[], module_hints=[{k:v for k,v in h.items() if k!='evidence'} for h in e.get('module_hints', [])])
        trial = json.loads(json.dumps(result)); trial['endpoints'].append(item)
        if fits(trial, 47500): result = trial

    def add(sid):
        nonlocal result
        wid = wire_ids[sid]
        if wid in result['snippets']: return
        snippet = dict(data['snippets'][sid])
        snippet['id'] = wid
        # Preserve original path/line/hash while removing presentation overhead.
        snippet['code'] = '\n'.join(clean for line in snippet['code'].splitlines()
                                    if (clean := re.sub(r'^\s*\d+:[ \t]?', '', line).rstrip()).strip())
        trial = json.loads(json.dumps(result)); trial['snippets'][wid] = snippet
        for e in trial['endpoints']:
            if sid in originals[e['id']]['evidence_ids']: e['evidence_ids'].append(wid)
        if fits(trial): result = trial

    # First give every endpoint an actual call-site, instead of consuming the
    # budget on main.c + font arrays and dropping the OLED module wholesale.
    for e in result['endpoints']:
        source = originals[e['id']]
        selected = None
        for call in source['calls']:
            for sid in source['evidence_ids']:
                snippet = data['snippets'][sid]
                if snippet['path'] != e['path']: continue
                bounds = sid.rsplit(':',1)[-1].split('-')
                if len(bounds)==2 and int(bounds[0]) <= call['line'] <= int(bounds[1]): selected=sid;break
            if selected: break
        if selected: add(selected)
    # Then share header definitions, followed by round-robin remaining context.
    entries = [originals[e['id']] for e in result['endpoints']]
    for e in entries:
        for sid in e['evidence_ids']:
            if data['snippets'][sid]['path'].endswith('.h'): add(sid)
    for index in range(max((len(e['evidence_ids']) for e in entries), default=0)):
        for e in entries:
            if index < len(e['evidence_ids']): add(e['evidence_ids'][index])
    result['endpoints'] = [e for e in result['endpoints'] if e['evidence_ids']]
    # Enum labels that actually select an array element / switch case in the
    # driver are instance candidates, regardless of the developer's naming.
    # They are suggestions for the model, not automatic device declarations.
    for e in result['endpoints']:
        codes = [result['snippets'][sid]['code'] for sid in e['evidence_ids']]
        declarations = '\n'.join(codes)
        enums = []
        for body in re.findall(r'\benum\s*(?:\w+\s*)?\{([^{}]+)\}', declarations):
            enums.extend(re.findall(r'(?:^|,)\s*([A-Za-z_]\w*)', body))
        implementation = '\n'.join(result['snippets'][sid]['code'] for sid in e['evidence_ids']
                                   if result['snippets'][sid]['path'] == e['path'])
        candidates = sorted({value for value in enums if re.search(r'\[\s*'+re.escape(value)+r'\s*\]|\bcase\s+'+re.escape(value)+r'\s*:', implementation)})
        if candidates:
            trial = json.loads(json.dumps(result))
            next(item for item in trial['endpoints'] if item['id']==e['id'])['instance_candidates'] = candidates[:24]
            if fits(trial): e['instance_candidates'] = candidates[:24]
    required_ids = {sid for e in data['endpoints'] for sid in e['evidence_ids']}
    result['coverage'] = {'sent': len(result['endpoints']), 'indexed': len(data['endpoints']),
                          'partial': data.get('truncated', False) or len(result['endpoints']) < len(data['endpoints']) or len(result['snippets']) < len(required_ids),
                          'context_sent':len(result['snippets']), 'context_indexed':len(required_ids),
                          'data_tables_omitted':len(data.get('excluded_tables', []))}
    return result


def validate(answer, request):
    if not isinstance(answer, dict) or not isinstance(answer.get('devices'), list): raise ValueError('设备识别结果缺少 devices 列表')
    if len(answer['devices']) > 48: raise ValueError('设备数量超过本次分析上限')
    known = {e['id']: e for e in request['endpoints']}
    result, seen = [], set()
    for device in answer['devices']:
        if not isinstance(device, dict): raise ValueError('设备格式错误')
        ids = device.get('endpoint_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(i,str) or i not in known for i in ids):
            raise ValueError('设备引用了未知接口，已拒绝')
        for key, limit in [('name', 100), ('kind', 40), ('instance', 100), ('reason', 1500)]:
            if not isinstance(device.get(key), str) or not device[key].strip() or len(device[key]) > limit:
                raise ValueError('设备说明字段缺失或过长：'+key)
        allowed = {sid for i in ids for sid in known[i]['evidence_ids']}
        evidence = device.get('evidence')
        if not isinstance(evidence, list) or not evidence: raise ValueError('设备判断缺少代码依据')
        proof = []
        for citation_number, cite in enumerate(evidence, 1):
            if not isinstance(cite, dict) or not isinstance(cite.get('snippet_id'), str): raise ValueError('设备依据格式错误')
            quote = cite.get('quote')
            sid = cite['snippet_id']
            corrected = False
            if sid not in allowed or not quote_exists(quote, request['snippets'][sid]['code']):
                # Caller windows can overlap the main driver chunks. Repair an
                # ID only by exact code tokens in an already allowed snippet.
                # Never search unrelated interfaces or manufacture a quote.
                matches = [s for s in sorted(allowed) if quote_exists(quote, request['snippets'][s]['code'])]
                if not matches:
                    raise ValueError('设备依据不属于该接口' if sid not in allowed else f'第 {citation_number} 段引文未匹配片段 {sid}；已跳过此设备，请重试')
                sid = matches[0]; corrected = True
            snippet = request['snippets'][sid]
            proof.append({**snippet, 'quote': quote, 'reference_corrected': corrected})
        instance_binding = '代码中的实例标识'
        if not any(tokens(device['instance']) == [device['instance']] and device['instance'] in tokens(p['quote']) for p in proof):
            composite_gpio = False
            for eid in ids:
                ep = known[eid]
                if ep['family'] != 'GPIO': continue
                aliases = {ep['handle']+'_'+ep['channel'], ep['handle']+'_'+ep['channel'].removeprefix('GPIO_')}
                if device['instance'] not in aliases: continue
                for call in ep['calls']:
                    text = call['api']+'('+','.join(call['arguments'])+')'
                    if any(quote_exists(text,p['quote']) for p in proof): composite_gpio=True
            bound_call = None
            if not composite_gpio:
                for eid in ids:
                    ep = known[eid]
                    if device['instance'] not in {ep['handle'], ep['channel']}: continue
                    for call in ep['calls']:
                        call_text = call['api']+'('+','.join(call['arguments'])+')'
                        if ep['family'] == 'MODULE': call_text = call['api']+'('
                        for sid in ep['evidence_ids']:
                            snippet = request['snippets'][sid]
                            if snippet['path']==ep['path'] and quote_exists(call_text, snippet['code']):
                                bound_call = {**snippet, 'quote': call_text, 'role': '本地补充：实例绑定调用'}
                                break
                        if bound_call: break
                    if bound_call: break
            if not composite_gpio and not bound_call:
                raise ValueError('设备实例标识必须出现在引文中，或能由本地已核验的接口调用绑定')
            if composite_gpio: instance_binding = '由已核验的同一 GPIO 调用中的端口／引脚组合'
            else:
                proof.append(bound_call)
                instance_binding = '本地已核验的接口调用补充绑定'
        identity = '|'.join(sorted(set(ids)))+'::'+device['instance']
        if identity in seen: raise ValueError('模型重复列出同一设备实例')
        seen.add(identity)
        features = device.get('features', [])
        if not isinstance(features, list) or len(features) > 12 or any(not isinstance(f,str) or len(f)>120 for f in features):
            raise ValueError('设备功能列表格式错误')
        result.append({'id': hashlib.sha256(identity.encode()).hexdigest()[:18],
                       **{k: device[k] for k in ('name','kind','instance','reason')},
                       'endpoint_ids': list(dict.fromkeys(ids)), 'interfaces': [known[i] for i in dict.fromkeys(ids)],
                       'features': features, 'evidence': proof, 'status': 'AI 识别 · 待确认', 'writable': False})
        result[-1]['instance_binding'] = instance_binding
    return enrich(result, request['endpoints'])


def validate_partial(answer, request):
    if not isinstance(answer, dict) or not isinstance(answer.get('devices'), list): raise ValueError('设备识别结果缺少 devices 列表')
    if len(answer['devices']) > 48: raise ValueError('设备数量超过本次分析上限')
    accepted, warnings, seen = [], [], set()
    for index, item in enumerate(answer['devices'], 1):
        name = item.get('name', '未命名设备') if isinstance(item, dict) else '格式错误项'
        try:
            item, repairs = canonical_candidate(item, request)
            try:
                device = validate({'devices': [item]}, request)[0]
            except ValueError as error:
                # A valid device must not disappear solely because the model
                # appended one unrelated/bad citation. Retain only exact quotes
                # from its own interfaces and re-run ALL instance checks.
                if not any(term in str(error) for term in ('引文','依据')): raise
                allowed={sid for e in request['endpoints'] if e['id'] in item.get('endpoint_ids',[]) for sid in e['evidence_ids']}
                evidence=item.get('evidence',[])
                retained=[c for c in evidence if isinstance(c,dict) and any(quote_exists(c.get('quote'),request['snippets'][sid]['code']) for sid in allowed)]
                if not retained or len(retained)==len(evidence): raise
                item=dict(item,evidence=retained,features=['仅部分代码依据通过核验；具体功能需要复核'])
                device=validate({'devices':[item]},request)[0]
                device['evidence_partial']=True
                device['status']='部分引文已核对 · 功能待复核'
                repairs.append('剔除 '+str(len(evidence)-len(retained))+' 段未通过核验的模型引文；实例绑定仍按保留的原代码验证。')
            device['local_repairs'] = repairs
            if device['id'] in seen: raise ValueError('重复的设备实例，已合并')
            seen.add(device['id'])
            accepted.append(device)
        except ValueError as error:
            warnings.append({'index': index, 'name': str(name)[:100], 'reason': str(error)})
    return accepted, warnings


def canonical_candidate(item, request):
    """Repair references from source facts, never from a guessed device name."""
    if not isinstance(item, dict): return item, []
    item = dict(item)
    evidence = item.get('evidence', [])
    if not isinstance(evidence, list) or any(not isinstance(c, dict) for c in evidence): return item, []
    known = {e['id']: e for e in request['endpoints']}
    ids = item.get('endpoint_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids): return item, []
    repairs = []
    if any(i not in known for i in ids):
        recovered = set()
        for cite in evidence:
            snippet = request['snippets'].get(cite.get('snippet_id'))
            if not snippet or not quote_exists(cite.get('quote'), snippet['code']): continue
            for e in known.values():
                if e['path'] != snippet['path'] or snippet['id'] not in e['evidence_ids'] or e['family']=='MODULE': continue
                for call in e['calls']:
                    text = call['api']+'('+','.join(call['arguments'])+')'
                    if quote_exists(text, cite['quote']): recovered.add(e['id'])
        if not recovered: return item, repairs
        item['endpoint_ids'] = list(dict.fromkeys([i for i in ids if i in known] + sorted(recovered)))
        repairs.append('模型接口编号有误，已按引文中的完整接口调用重新绑定。')
    endpoints = [known[i] for i in item['endpoint_ids']]
    instance = item.get('instance')
    if not isinstance(instance, str) or not re.fullmatch(r'[A-Za-z_]\w*', instance): return item, repairs
    # A shortened pin namespace can be normalized only to the exact channel
    # present in the quoted source, not to any similarly named project symbol.
    if not any(instance in tokens(c.get('quote', '')) for c in evidence):
        aliases = {e['channel'] for e in endpoints if e['family']=='GPIO' and e['channel']==instance+'_Pin'
                   and any(e['channel'] in tokens(c.get('quote', '')) for c in evidence)}
        # A namespace like OLED is a display label, not a C token. Bind it to
        # an actual quoted driver entry; this is a code label, not a hardware UID.
        for e in endpoints:
            for cite in evidence:
                if cite.get('snippet_id') not in e['evidence_ids']: continue
                for function in re.findall(r'\b('+re.escape(instance)+r'_\w+)\s*\(', cite.get('quote', ''), re.I):
                    aliases.add(function)
        if aliases:
            item['instance'] = sorted(aliases)[0]
            repairs.append('模型实例简称 '+instance+' 已规范为源码标识 '+item['instance']+'。')
            instance = item['instance']
        # Remove a model-created TIMn_CHANNEL_m label only when the quoted HAL
        # call proves the actual channel. Do not infer timer identity from htim
        # naming: users may name handles arbitrarily.
        channel_alias = re.fullmatch(r'TIM\d+_(?:CHANNEL_|CH)(\d+)', instance)
        if channel_alias:
            channel = 'TIM_CHANNEL_'+channel_alias[1]
            matching = [e for e in endpoints if e['family']=='PWM' and e['channel']==channel and
                        any(quote_exists(call['api']+'('+','.join(call['arguments'])+')', cite.get('quote',''))
                            for call in e['calls'] for cite in evidence)]
            if matching:
                item['instance'] = channel
                repairs.append('模型复合通道标签 '+instance+' 已按完整接口调用规范为 '+channel+'，未据此确认定时器别名。')
                instance = channel
    # A GPIO alias may be declared in main.h while the driver uses literal pins.
    # Prove both port and pin, then append their actual macro declarations.
    if instance.endswith('_Pin') and not any(instance in tokens(c.get('quote', '')) for c in evidence):
        declarations = {}
        for e in endpoints:
            for sid in e['evidence_ids']:
                for line in request['snippets'][sid]['code'].splitlines():
                    m = re.fullmatch(r'\s*#\s*define\s+(\w+)\s+([A-Za-z_]\w*)\s*', line)
                    if m: declarations[m[1]] = (m[2], sid, line)
        port = instance[:-4]+'_GPIO_Port'
        for e in endpoints:
            if e['family']!='GPIO' or instance not in declarations or port not in declarations: continue
            if (declarations[instance][0], declarations[port][0]) != (e['channel'], e['handle']): continue
            item['evidence'] = list(evidence) + [{'snippet_id':declarations[key][1], 'quote':declarations[key][2]}
                                               for key in (instance, port)]
            repairs.append('已通过头文件的端口和引脚定义补充验证 GPIO 别名。')
            break
    return item, repairs


def supplement_common_clues(devices, request):
    """Keep documented local clues visible when the model omits/rejects them.

    A row groups code entry points, explicitly NOT a physical instance count.
    """
    present = {(h['model'],h['category']) for d in devices for h in d.get('recognition_hints',[])}
    pending = {}
    for endpoint in request['endpoints']:
        for hint in endpoint.get('module_hints', []):
            key = hint['model'],hint['category']
            if key in present: continue
            pending.setdefault(key, []).append((endpoint,hint))
    added = []
    for (model,category), entries in pending.items():
        proof = []
        for endpoint,_ in entries:
            for call in endpoint['calls']:
                quote = call['api']+'('+','.join(call['arguments'])+')'
                if endpoint['family']=='MODULE': quote=call['api']+'('
                sid = next((sid for sid in endpoint['evidence_ids']
                            if request['snippets'][sid]['path']==endpoint['path'] and
                            quote_exists(quote,request['snippets'][sid]['code'])), None)
                if sid:
                    proof.append({**request['snippets'][sid], 'quote':quote, 'role':'本地驱动线索'});break
        if not proof: continue
        endpoints = [entry[0] for entry in entries]
        hint = entries[0][1]
        identity = 'local-clue::'+model+'::'+'|'.join(sorted(e['id'] for e in endpoints))
        added.append({'id':hashlib.sha256(identity.encode()).hexdigest()[:18],
                      'name':category+'（'+model+'；实例待确认）', 'kind':'sensor_candidate',
                      'instance':'驱动线索分组（非单个硬件实例）', 'endpoint_ids':[e['id'] for e in endpoints],
                      'interfaces':endpoints, 'features':['源码中存在模块线索，具体功能和实例数量待核对'],
                      'reason':'AI 未形成可核验的独立实例，本地保留已提取的模块证据。这是代码线索，不表示实物已连接。',
                      'evidence':proof, 'status':'本地补充线索 · 实例未确认', 'writable':False,
                      'category':category,'model':model,'driver_state':hint['driver_state'],
                      'classification_basis':hint['confidence'],'recognition_hints':[hint],
                      'local_repairs':[], 'origin':'local_clue'})
        if hint.get('module_model'):
            added[-1]['module_model']=hint['module_model'];added[-1]['components']=hint['components']
            added[-1]['name']='IMU963RA 九轴模块线索（实例待确认）'
    return added
