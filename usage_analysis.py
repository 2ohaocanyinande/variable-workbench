"""Bounded source evidence index. Heuristic C/C++ extraction, never a write authority.

Does not expand macros, resolve overloads, or prove data flow. Ambiguous cross-file
names are left unresolved. API findings remain hypotheses, even with valid quotes.
"""
import hashlib
import json
import re
from code_evidence import quote_exists

NETWORK_EFFECTS = {
    'esp_wifi_set_config': 'Wi-Fi 配置', 'esp_wifi_get_config': 'Wi-Fi 配置读取',
    'esp_wifi_connect': 'Wi-Fi 连接', 'esp_wifi_disconnect': 'Wi-Fi 断开',
    'esp_netif_get_ip_info': 'IP 信息读取',
    'esp_mqtt_client_init': 'MQTT 配置', 'esp_mqtt_client_start': 'MQTT 连接启动',
    'esp_mqtt_client_publish': 'MQTT 发布', 'esp_mqtt_client_subscribe': 'MQTT 订阅',
    'esp_mqtt_client_subscribe_single': 'MQTT 订阅',
    'esp_ble_gap_start_scanning': 'BLE 扫描', 'esp_ble_gattc_open': 'BLE 客户端连接',
    'esp_ble_gattc_write_char': 'BLE 特征写入',
    'esp_event_handler_instance_register': 'Wi-Fi/IP 状态事件注册',
    'esp_ble_gap_register_callback': 'BLE GAP 事件注册',
    'esp_ble_gattc_register_callback': 'BLE GATT 事件注册',
}
STM32_EFFECTS = {
    'HAL_TIM_PWM_Start': 'STM32 PWM 启动', '__HAL_TIM_SET_COMPARE': 'STM32 定时器比较值设置',
    'HAL_ADC_GetValue': 'STM32 ADC 采样值读取', 'HAL_GPIO_WritePin': 'STM32 GPIO 输出',
    'HAL_ADC_Start_DMA': 'STM32 ADC DMA 采样启动',
    'HAL_TIM_Encoder_Start': 'STM32 编码器模式启动', 'HAL_TIM_Encoder_Start_IT': 'STM32 编码器模式启动（中断）',
    'HAL_TIM_Encoder_Init': 'STM32 编码器模式配置',
    'HAL_TIM_Encoder_Start_DMA': 'STM32 编码器模式启动（DMA）', '__HAL_TIM_GET_COUNTER': 'STM32 定时器计数读取',
    '__HAL_TIM_SET_COUNTER': 'STM32 定时器计数设置', 'TIM_GetCounter': 'STM32 标准库计数读取',
    'HAL_I2C_Master_Transmit': 'STM32 I2C 发送', 'HAL_SPI_Transmit': 'STM32 SPI 发送',
    'GPIO_SetBits': 'STM32 标准库 GPIO 置位', 'GPIO_ResetBits': 'STM32 标准库 GPIO 复位',
    'GPIO_WriteBit': 'STM32 标准库 GPIO 输出', 'ADC_GetConversionValue': 'STM32 标准库 ADC 读取',
    'USART_SendData': 'STM32 标准库串口发送', 'USART_ReceiveData': 'STM32 标准库串口接收',
}
for _channel in range(1, 5): STM32_EFFECTS[f'TIM_SetCompare{_channel}'] = 'STM32 标准库定时器比较值设置'
for _direction, _label in [('Transmit', '发送'), ('Receive', '接收')]:
    for _mode in ('', '_IT', '_DMA'):
        STM32_EFFECTS['HAL_UART_'+_direction+_mode] = 'STM32 串口'+_label+('（'+_mode[1:]+'）' if _mode else '')
for _function, _label in {'HAL_I2C_Master_Transmit': 'I2C 发送', 'HAL_I2C_Master_Receive': 'I2C 接收',
                           'HAL_I2C_Mem_Read': 'I2C 寄存器读取', 'HAL_SPI_Transmit': 'SPI 发送',
                           'HAL_SPI_Receive': 'SPI 接收', 'HAL_SPI_TransmitReceive': 'SPI 双向收发'}.items():
    for _mode in ('', '_IT', '_DMA'):
        STM32_EFFECTS[_function+_mode] = 'STM32 '+_label+('（'+_mode[1:]+'）' if _mode else '')
for _name, _role in {'socket': '创建套接字', 'connect': '套接字连接', 'send': '套接字发送',
                     'recv': '套接字接收', 'sendto': '套接字发送到地址', 'recvfrom': '套接字接收及来源地址'}.items():
    NETWORK_EFFECTS[_name] = 'TCP/UDP：' + _role
    NETWORK_EFFECTS['lwip_' + _name] = 'TCP/UDP：' + _role


def safe_excerpt(text):
    """Hide literal contents and comments before cloud submission, keep line count."""
    pattern = r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    def hide(match):
        value = match[0]
        if value.startswith(('/*', '//')): return re.sub(r'[^\n]', ' ', value)
        quote = value[0]
        return quote + '<hidden>' + '\n' * value.count('\n') + quote
    return re.sub(pattern, hide, text)


def masked(text):
    return re.sub(r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: re.sub(r'[^\n]', ' ', m[0]), text)


def balanced(code, start, left='(', right=')'):
    depth = 0
    for i in range(start, len(code)):
        if code[i] == left: depth += 1
        elif code[i] == right:
            depth -= 1
            if depth == 0: return i
    return None


def index_usage(root, texts, active, hashes):
    functions = []
    snippets = {}

    def excerpt(path, position, role):
        text = texts[path]
        lines = safe_excerpt(text).splitlines()
        line = text.count('\n', 0, position) + 1
        first, last = max(1, line - 3), min(len(lines), line + 5)
        relative = path.relative_to(root).as_posix()
        key = f'{relative}:{first}-{last}'
        if key not in snippets:
            snippets[key] = {'id': key, 'path': relative, 'line': line, 'start': first, 'end': last,
                             'role': role, 'sha256': hashes[relative],
                             'code': '\n'.join(f'{i}: {lines[i-1]}' for i in range(first, last + 1))}
        return key

    for path, text in texts.items():
        if path.suffix not in {'.c', '.cpp'}: continue
        code = masked(text)
        # Deliberately limited to ordinary function definitions, not C++ methods.
        pattern = r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t*]+)+([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{'
        for match in re.finditer(pattern, code):
            end = balanced(code, match.end()-1, '{', '}')
            if end is None: continue
            body_start = match.end()
            fn = {'name': match[1], 'path': path.relative_to(root).as_posix(),
                  'active': path.resolve() in active, 'calls': [],
                  'evidence': [excerpt(path, match.start(1), '函数定义')],
                  'body': code[body_start:end], 'start': body_start, 'end': end,
                  'signature_start': match.start(),
                  'file': path}
            for call in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', fn['body']):
                if call[1] in {'if', 'for', 'while', 'switch', 'sizeof', 'return'}: continue
                opening = body_start + call.end() - 1
                closing = balanced(code, opening)
                if closing is None or closing > end: continue
                fn['calls'].append({'name': call[1], 'arguments': code[opening+1:closing][:500],
                                    'evidence': excerpt(path, body_start+call.start(), '调用及实参')})
            functions.append(fn)

    # Resolve local definitions first; otherwise only unique external definitions.
    def resolve(fn, name):
        local = [g for g in functions if g['name'] == name and g['path'] == fn['path']]
        options = local or [g for g in functions if g['name'] == name]
        return options[0] if len(options) == 1 else None

    # API effects are peripheral-level clues, never a claim of a physical motor.
    effects = {'ledc_set_duty': 'PWM 输出值', 'ledc_set_duty_with_hpoint': 'PWM 输出值',
               'gpio_set_level': '数字引脚输出', 'adc_oneshot_read': 'ADC 采样读取',
               'temperature_sensor_get_celsius': '芯片温度读取'}
    effects.update(NETWORK_EFFECTS)
    effects.update(STM32_EFFECTS)

    def effect(fn, name):
        if resolve(fn, name): return None  # project function with the same name
        if name == 'esp_event_handler_instance_register':
            if not any(c['name'] == name and re.match(r'\s*(?:WIFI_EVENT|IP_EVENT)\s*,', c['arguments']) for c in fn['calls']):
                return None
        if name in {'socket', 'connect', 'send', 'recv', 'sendto', 'recvfrom'}:
            source = texts[fn['file']]
            if not re.search(r'#\s*include\s*[<"](?:lwip/sockets|sys/socket)\.h[>"]', source): return None
        return effects.get(name)

    callbacks = {}
    for fn in functions:
        for call in fn['calls']:
            name = call['name']
            if name not in {'esp_event_handler_instance_register', 'esp_ble_gap_register_callback', 'esp_ble_gattc_register_callback'}: continue
            role = effect(fn, name)
            if not role: continue
            args = call['arguments'].split(',')
            index = 2 if name == 'esp_event_handler_instance_register' else 0
            if len(args) <= index or not re.fullmatch(r'\s*&?\s*\w+\s*', args[index]): continue
            target = resolve(fn, args[index].strip().lstrip('&').strip())
            if target:
                callbacks.setdefault((target['path'], target['name']), []).append((role, call['evidence']))

    network = []
    stm32_entries = []
    for fn in functions:
        calls = [call for call in fn['calls'] if call['name'] in NETWORK_EFFECTS and effect(fn, call['name'])]
        registered = callbacks.get((fn['path'], fn['name']), [])
        if not calls and not registered: continue
        proof = list(dict.fromkeys(fn['evidence'] + [c['evidence'] for c in calls] + [e for role, e in registered]))[:18]
        network.append({'id': fn['path']+'::function::'+fn['name']+'@'+str(fn['start']),
                        'symbol': fn['name'], 'scope': fn['name'], 'path': fn['path'],
                        'line': snippets[fn['evidence'][0]]['line'], 'active': fn['active'],
                        'type': 'function', 'clues': sorted({effect(fn, c['name']) for c in calls} | {role for role, e in registered}),
                        'call_chains': [[fn['name'], c['name']] for c in calls][:12],
                        'evidence_ids': proof, 'truncated': len(calls) >= 18,
                        'warning': '网络调用证据，不代表当前已联网；协议、状态与回调需结合代码核对。'})
    for fn in functions:
        calls = [c for c in fn['calls'] if c['name'] in STM32_EFFECTS and effect(fn, c['name'])]
        if not calls: continue
        proof = list(dict.fromkeys(fn['evidence'] + [c['evidence'] for c in calls]))[:18]
        stm32_entries.append({'id': fn['path']+'::function::'+fn['name']+'@'+str(fn['start']),
                              'symbol': fn['name'], 'scope': fn['name'], 'path': fn['path'],
                              'line': snippets[fn['evidence'][0]]['line'], 'active': fn['active'], 'type': 'function',
                              'clues': sorted({effect(fn, c['name']) for c in calls}),
                              'call_chains': [[fn['name'], c['name']] for c in calls][:12],
                              'evidence_ids': proof, 'truncated': len(calls) >= 18,
                              'warning': '仅确认源码调用，不代表物理用途、引脚接线或实时状态已验证。'})
    candidates = []
    truncated = False
    for path, text in texts.items():
        if path.suffix not in {'.c', '.cpp'}: continue
        code = masked(text)
        # Includes locals and parameters; identities contain scope and line.
        records = []
        for record in re.finditer(r'\b(?:struct|union|enum)\s*(?:\w+\s*)?\{', code):
            end = balanced(code, record.end()-1, '{', '}')
            if end is not None: records.append((record.end()-1, end))
        decl = r'\b(float|double|bool|int|char|void|struct\s+\w+|uint\d+_t|int\d+_t|u(?:8|16|32)|[A-Za-z_]\w*TypeDef|[A-Za-z_]\w*_t)\s+\*?\s*([A-Za-z_]\w*)\s*(?=[=;,\)\[])'
        for match in re.finditer(decl, code):
            if any(start < match.start() < end for start, end in records): continue
            if len(candidates) >= 800:
                truncated = True
                break
            symbol = match[2]
            owner = next((f for f in functions if f['file'] == path and f['signature_start'] <= match.start() <= f['end']), None)
            # Function parameters precede the opening brace.
            if owner is None:
                owner = next((f for f in functions if f['file'] == path and match.end() < f['start'] and
                              '\n' not in code[match.end():f['start']] and ';' not in code[match.end():f['start']]), None)
            line = text.count('\n', 0, match.start(2)) + 1
            relative = path.relative_to(root).as_posix()
            scope = owner['name'] if owner else 'global'
            cid = f'{relative}::{scope}::{symbol}@{line}'
            refs = [f for f in functions if f['file'] == path and
                    (f is owner if owner else re.search(r'\b'+re.escape(symbol)+r'\b', f['body']))]
            evidence = [excerpt(path, match.start(2), '变量声明（作用域为启发式定位）')]
            for fn in refs[:5]:
                for use in list(re.finditer(r'\b'+re.escape(symbol)+r'\b', fn['body']))[:6]:
                    evidence.append(excerpt(path, fn['start']+use.start(), '变量使用或赋值附近代码'))
            chains, clues = [], []
            for fn in refs[:5]:
                for role, sid in callbacks.get((fn['path'], fn['name']), []):
                    clues.append(role)
                    evidence.append(sid)

            def visit(fn, chain, depth, seen):
                key = fn['path']+'::'+fn['name']
                if key in seen: return
                seen = seen | {key}
                evidence.extend(fn['evidence'])
                for call in fn['calls'][:30]:
                    evidence.append(call['evidence'])
                    role = effect(fn, call['name'])
                    if role:
                        clues.append(role)
                        chains.append(chain+[call['name']])
                    if depth < 2:
                        target = resolve(fn, call['name'])
                        if target: visit(target, chain+[call['name']], depth+1, seen)

            for fn in refs[:5]: visit(fn, [fn['name']], 0, set())
            if not refs: continue
            # Cap each candidate independently. The UI exposes truncation.
            evidence = list(dict.fromkeys(evidence))
            candidates.append({'id': cid, 'symbol': symbol, 'type': match[1], 'scope': scope,
                               'path': relative, 'line': line, 'active': path.resolve() in active,
                               'clues': sorted(set(clues)), 'call_chains': chains[:12],
                               'evidence_ids': evidence[:18], 'truncated': len(evidence) > 18,
                               'warning': '调用可达不等于数值必然流入；需核对赋值、实参、条件编译及硬件接线。'})
    # Numeric object macros often contain the actual user-adjustable parameters.
    # Index definitions and their uses without claiming preprocessing/data-flow proof.
    for path,text in texts.items():
        if path.suffix not in {'.c','.h','.cpp'}:continue
        code=masked(text)
        for match in re.finditer(r'(?m)^\s*#\s*define[ \t]+([A-Za-z_]\w*)[ \t]+(\(?[+-]?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*\)?)[ \t]*$',code):
            if len(candidates)>=800:truncated=True;break
            symbol=match[1];refs=[fn for fn in functions if re.search(r'\b'+re.escape(symbol)+r'\b',fn['body'])]
            if not refs:continue
            relative=path.relative_to(root).as_posix();line=text.count('\n',0,match.start(1))+1
            evidence=[excerpt(path,match.start(1),'数值宏定义（未展开预处理条件）')];clues=[];chains=[]
            for fn in refs[:5]:
                for use in list(re.finditer(r'\b'+re.escape(symbol)+r'\b',fn['body']))[:3]:evidence.append(excerpt(fn['file'],fn['start']+use.start(),'数值宏使用处'))
                for call in fn['calls'][:8]:
                    evidence.append(call['evidence']);role=effect(fn,call['name'])
                    if role:clues.append(role);chains.append([fn['name'],call['name']])
            evidence=list(dict.fromkeys(evidence))
            candidates.append({'id':f'{relative}::macro::{symbol}@{line}','symbol':symbol,'type':'numeric_macro','scope':'preprocessor',
                               'path':relative,'line':line,'active':any(fn['active'] for fn in refs),'literal':match[2],
                               'clues':sorted(set(clues)),'call_chains':chains[:12],'evidence_ids':evidence[:18],
                               'truncated':len(evidence)>18,'warning':'宏引用是文本线索；未验证包含关系、重定义、条件编译或最终生效值，不能直接当成可安全修改的变量。'})
    if len(network) > 100: truncated = True
    network = network[:100]
    unique = {}
    if len(stm32_entries) > 100: truncated = True
    for entry in network + stm32_entries[:100]:
        if entry['id'] in unique:
            previous = unique[entry['id']]
            previous['clues'] = sorted(set(previous['clues'] + entry['clues']))
            previous['evidence_ids'] = list(dict.fromkeys(previous['evidence_ids'] + entry['evidence_ids']))[:18]
            previous['call_chains'] += entry['call_chains']
        else: unique[entry['id']] = dict(entry)
    candidates.extend(unique.values())
    used = {key for c in candidates for key in c['evidence_ids']}
    return {'candidates': candidates, 'snippets': {k: v for k, v in snippets.items() if k in used},
            'network': network,
            'stm32': stm32_entries[:100],
            'truncated': truncated, 'method': '局部声明 + 调用图（最多 2 层包装）+ 周边源码；非完整 AST/数据流证明',
            'limits': '最多 800 个变量/数值宏，每项 18 片段；宏表达式展开、复杂 C++、函数指针与跨文件全局引用待支持。'}


def make_packet(scan, question, scope='all'):
    usage = scan['usage']
    # Hardware-related candidates first, followed by others. Names are not ranked.
    candidates = sorted(usage['candidates'], key=lambda c: (not bool(c['clues']), not c['active']))
    # Explicit symbol selection identifies the object; it does not infer purpose.
    requested = [c for c in candidates if re.search(r'(?<!\w)'+re.escape(c['symbol'])+r'(?!\w)', str(question))]
    if requested:candidates=requested
    elif scope == 'network':
        roles = set(NETWORK_EFFECTS.values())
        candidates = [c for c in candidates if roles.intersection(c['clues'])]
    elif scope == 'stm32':
        candidates = [c for c in candidates if set(STM32_EFFECTS.values()).intersection(c['clues'])]
    # An explicit user reference narrows the request; names do not determine purpose.
    packet = {'question': str(question)[:1000], 'scope': scope, 'method': usage['method'],
              'privacy': '字符串、字符常量与注释内容已隐藏；数字常量和变量名仍保留。', 'candidates': [], 'snippets': {}}
    packet['project'] = {'platform': scan.get('platform', 'unknown'),
                         'devices': scan.get('project_info', {}).get('devices', []),
                         'build_evidence': scan.get('build_source', 'unknown')}
    for candidate in candidates:
        trial = json.loads(json.dumps(packet))
        trial['candidates'].append(candidate)
        for key in candidate['evidence_ids']: trial['snippets'][key] = usage['snippets'][key]
        if len(json.dumps(trial, ensure_ascii=False).encode()) > 48000: continue
        packet = trial
        if len(packet['candidates']) == 24: break
    packet['coverage'] = {'sent': len(packet['candidates']), 'indexed': len(usage['candidates']),
                          'matched': len(candidates),
                          'partial': usage['truncated'] or len(packet['candidates']) < len(usage['candidates'])}
    return packet


def validate_findings(answer, packet):
    if not isinstance(answer, dict) or not isinstance(answer.get('findings'), list):
        raise ValueError('模型结果缺少 findings 列表')
    allowed = {c['id']: c for c in packet['candidates']}
    findings, seen = [], set()
    for item in answer['findings']:
        if not isinstance(item, dict) or item.get('candidate_id') not in allowed:
            raise ValueError('模型引用了未发送的变量，已拒绝')
        candidate = allowed[item['candidate_id']]
        if candidate['id'] in seen: raise ValueError('模型重复返回同一个变量')
        seen.add(candidate['id'])
        citations = item.get('evidence', [])
        if not isinstance(citations, list) or not citations: raise ValueError('用途判断必须有代码依据')
        verified = []
        for citation in citations:
            if not isinstance(citation, dict): raise ValueError('依据格式错误')
            sid, quote = citation.get('snippet_id'), citation.get('quote')
            if sid not in candidate['evidence_ids'] or not isinstance(quote, str) or len(quote.strip()) < 4:
                raise ValueError('模型依据不属于该变量')
            snippet = packet['snippets'][sid]
            # Whitespace-normalized quote must be present in the exact submitted excerpt.
            if not quote_exists(quote, snippet['code']):
                raise ValueError('模型引用了不存在的代码，已拒绝')
            verified.append({**snippet, 'quote': quote})
        purpose, reason = item.get('purpose'), item.get('reason')
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 160:
            raise ValueError('用途说明格式错误')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError('判断理由格式错误')
        findings.append({'candidate': candidate, 'purpose': purpose, 'reason': reason,
                         'evidence': verified, 'status': 'AI 推测 · 待确认', 'selectable': False})
    return findings
