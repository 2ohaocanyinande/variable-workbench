"""Small documented catalogue: device category is separate from runtime identity.

Matches produce code-intent hints, never proof that hardware is attached. Short
aliases such as ISM are deliberately weak and never become an exact model.
"""
import re

CATALOG = [
    ('MPU6050', r'MPU[_-]?6050', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://github.com/adafruit/Adafruit_MPU6050'),
    ('ISM330DHCX', r'ISM330DHCX', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://www.st.com/resource/en/datasheet/ism330dhcx.pdf'),
    ('BMI270', r'BMI270', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf'),
    ('BMI088', r'BMI0?88', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi088-ds001.pdf'),
    ('ICM-42688', r'ICM[_-]?42688(?:[_-]?P)?', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://www.invensense.tdk.com/en-us/products/6-axis/icm-42688-p'),
    ('VL53L0X', r'VL53L0X', 'ToF 激光测距传感器', 'https://www.st.com/resource/en/datasheet/vl53l0x.pdf'),
    ('VL53L1X', r'VL53L1X', 'ToF 激光测距传感器', 'https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x'),
    ('VL53L1 系列（子型号待核对）', r'VL53L1', 'ToF 激光测距传感器', 'https://www.st.com/resource/en/user_manual/dm00474730-vl53l1x-api-user-manual-stmicroelectronics.pdf'),
    ('LSM6DSR', r'LSM6DSR', 'IMU 惯性传感器（陀螺仪／加速度计）', 'https://www.st.com/resource/en/datasheet/lsm6dsr.pdf'),
    ('TF-Luna', r'TF[_-]?LUNA', '激光测距模块', 'https://ai.benewake.com/en/resources/technical-documents/tf-luna-user-manual/'),
    ('TFmini 系列（子型号待核对）', r'TF[_-]?MINI(?:[_-]?S)?', '激光测距模块', 'https://ai.benewake.com/en/resources/technical-documents/tfmini-s-user-manual/'),
]


def signatures(text):
    """Caller supplies masked code / file names, never comments or log strings."""
    return [(model, category, source, match.group()) for model, pattern, category, source in CATALOG
            for match in [re.search(r'(?<![a-z0-9])'+pattern+r'(?![a-z0-9])', text, re.I)] if match]


def hints(endpoint, snippets):
    if endpoint['family'] in {'PWM', 'ENCODER', 'COUNTER'}: return []
    ids = endpoint.get('evidence_ids', [])
    code = '\n'.join(snippets[s]['code'] for s in ids)
    files = '\n'.join(snippets[s]['path'] for s in ids)
    result = []
    reads = bool(re.search(r'\b(?:HAL_(?:SPI_(?:Receive|TransmitReceive)|I2C_(?:Mem_Read|Master_Receive))\w*|\w*(?:read|Read|GetData|Ranging|Measure)\w*)\s*\(', code))
    for model, category, source, token in signatures(code+'\n'+files):
        if endpoint['family'] == 'MODULE' and endpoint['handle'] != model: continue
        if endpoint['family'] == 'GPIO' and not any(s[0] == model for s in signatures(endpoint['handle']+' '+endpoint['channel'])): continue
        if endpoint['family'] == 'UART' and not model.startswith(('TFmini', 'TF-Luna')): continue
        if endpoint['family'] == 'SPI' and model.startswith(('VL53', 'MPU6050', 'TFmini', 'TF-Luna')): continue
        identity = endpoint['handle']+' '+endpoint['channel']+' '+endpoint['path'].rsplit('/',1)[-1]+' '+ ' '.join(arg for call in endpoint['calls'] for arg in call['arguments'])
        if endpoint['family'] != 'MODULE' and not any(s[0] == model for s in signatures(identity)): continue
        # Match from code/file identity plus an actual interface/driver entry.
        proof = []
        for sid in ids:
            snippet = snippets[sid]
            if any(item[0] == model for item in signatures(snippet['code']+'\n'+snippet['path'])):
                proof.append({'snippet_id': sid, 'path': snippet['path'], 'line': snippet['line']})
        result.append({'model': model, 'category': category, 'confidence': '驱动标识匹配，硬件未实测',
                       'source': source, 'token': token, 'evidence': proof,
                       'driver_state': '存在读取相关代码，尚未验证采样' if reads else '本次片段未见采样入口',
                       'strength': 'driver_signature'})
        if model=='LSM6DSR' and re.search(r'\bIMU963RA_\w+\s*\(',code) and re.search(r'^\s*(?:\d+:\s*)?#\s*define\s+QMC5883L_\w+',code,re.M):
            # The module has two chips. Register declarations are not sampling.
            executable=re.sub(r'(?m)^\s*(?:\d+:\s*)?#\s*define[^\n]*','',code)
            magnetic_read=bool(re.search(r'\b(?:qmc5883l_\w*(?:read|Read)|IMU963RA_GetMag)\w*\s*\(',executable,re.I))
            result[-1]['module_model']='IMU963RA 九轴模块（代码型号线索，硬件未实测）'
            result[-1]['category']='九轴 IMU 模块（磁力计采样待核对）'
            result[-1]['module_source']='https://www.seekfree.com.cn/产品资料/传感器/姿态传感器/imu963ra九轴模块/'
            result[-1]['components']=[
                {'name':'LSM6DSR · 加速度 3 轴','state':'发现加速度读取入口，需验证调用和采样' if re.search(r'\bIMU963RA_GetAccel\s*\(',code) else '本次未见读取入口'},
                {'name':'LSM6DSR · 陀螺仪 3 轴','state':'发现陀螺仪读取入口，需验证调用和采样' if re.search(r'\bIMU963RA_GetGyro\s*\(',code) else '本次未见读取入口'},
                {'name':'QMC5883L · 磁力计 3 轴','state':'存在读取相关代码，仍需核对调用与采样' if magnetic_read else '仅发现寄存器定义，未发现初始化／采样调用'}]
    if not result and endpoint['family'] == 'GPIO':
        # A short family alias + CS/interrupt wiring is only a tentative category.
        # ISM can refer to other products; keep this explicit rather than inventing
        # ISM330DHCX or claiming six-axis measurements already exist.
        macros = {key: value.strip().strip('() ') for key, value in re.findall(r'#\s*define\s+(\w+)\s+([^\n]+)', code)}
        cs_pins = {'ISM_CS_Pin', macros.get('ISM_CS_Pin', '')}
        cs_ports = {'ISM_CS_GPIO_Port', macros.get('ISM_CS_GPIO_Port', '')}
        linked_cs = endpoint.get('channel') in cs_pins and endpoint.get('handle') in cs_ports
        if linked_cs and re.search(r'\bISM_CS_\w+', code) and re.search(r'\bISM_INT_\w+', code):
            result.append({'model': '型号待确认', 'category': '疑似 IMU 惯性传感器',
                           'confidence': '低：ISM 命名和片选／中断配置线索，类别也待核对',
                           'source': 'https://www.st.com/resource/en/datasheet/ism330dhcx.pdf', 'token': 'ISM_CS / ISM_INT',
                           'evidence': [{'snippet_id': sid, 'path': snippets[sid]['path'], 'line': snippets[sid]['line']} for sid in ids
                                        if 'ISM_CS' in snippets[sid]['code'] or 'ISM_INT' in snippets[sid]['code']],
                           'driver_state': '仅发现接口配置，未确认采样入口', 'strength': 'tentative_interface'})
    if not result and endpoint['family'] == 'UART':
        # Common nine-byte Benewake-family frame. Shared by several models:
        # never choose TFmini vs TF-Luna from this header alone.
        header0 = re.search(r'\b(\w+)\s*\[\s*0\s*\]\s*(?:==|!=)\s*0x59\b', code, re.I)
        header1 = re.search(r'\b(\w+)\s*\[\s*1\s*\]\s*(?:==|!=)\s*0x59\b', code, re.I)
        nine = any(len(c['arguments']) > 2 and c['arguments'][2].strip() == '9' for c in endpoint['calls'])
        distance = re.search(r'\[\s*2\s*\]', code) and re.search(r'\[\s*3\s*\].{0,15}<<\s*8', code)
        if header0 and header1 and header0[1] == header1[1] and nine and distance:
            result.append({'model': 'TFmini／TF-Luna 等兼容帧，具体型号待确认', 'category': '疑似激光测距模块',
                           'confidence': '协议形态匹配：双 0x59 帧头、9 字节和距离字段；未验证硬件',
                           'source': 'https://ai.benewake.com/en/resources/technical-documents/tf-luna-user-manual/',
                           'token': '0x59 0x59 / 9 bytes', 'evidence': [],
                           'driver_state': '存在距离帧解析代码，尚未验证实际测距', 'strength': 'protocol_shape'})
    return result


def enrich(devices, endpoints):
    by_id = {e['id']: e for e in endpoints}
    for device in devices:
        found = {}
        for eid in device['endpoint_ids']:
            if by_id[eid]['family'] in {'PWM','ENCODER','COUNTER'}: continue
            for hint in by_id[eid].get('module_hints', []): found[(hint['model'], hint['category'])] = hint
        device['recognition_hints'] = list(found.values())
        if len(found) != 1: continue
        hint = next(iter(found.values()))
        # Metadata must not contradict the primary device type. A strong module
        # endpoint can correct an AI label; a contextual hint cannot rename PWM.
        if device['kind'] in {'servo','motor'}:
            strong = all(by_id[eid]['family'] == 'MODULE' for eid in device['endpoint_ids']) and hint['strength'] == 'driver_signature'
            if not strong: continue
            device['original_ai_name'] = device['name']
            device['name'] = hint['category']+'（'+hint['model']+' 驱动线索）'
            device['kind'] = 'sensor_candidate'
            device['status'] = '类别冲突已标注 · 传感器驱动证据待核对'
            device['features'] = ['模型类型判断存在冲突，具体功能需要重新核对']
            device['reason'] += ' 模型原名称与该模块接口的传感器驱动证据冲突，原名称：'+device['original_ai_name']+'。'
        elif all(by_id[eid]['family']=='MODULE' for eid in device['endpoint_ids']) and hint['strength']=='driver_signature':
            device['original_ai_name'] = device['name']
            device['name'] = hint['category']+'（'+hint['model']+' 驱动线索）'
        device['category'] = hint['category']
        device['model'] = hint['model']
        device['driver_state'] = hint['driver_state']
        device['classification_basis'] = hint['confidence']
        if hint.get('module_model'):
            device['module_model']=hint['module_model'];device['components']=hint['components']
        # Refine broad unknowns without promoting hints to proven hardware facts.
        if device['kind'] == 'unknown':
            device['name'] = hint['category']+'（'+('型号待确认' if hint['strength']=='tentative_interface' else hint['model']+' 驱动线索')+'）'
            device['kind'] = 'sensor_candidate'
            device['status'] = '常见模块线索 · 待确认'
        if hint.get('module_model'):device['name']='IMU963RA 九轴模块（各传感器接入状态见下方）'
    return devices
