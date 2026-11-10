"""Index RTOS configuration and application call sites without running firmware."""
from collections import defaultdict
from pathlib import Path
import re

from screen_drivers import functions
from source_screen import arguments, literal
from usage_analysis import balanced, masked


TASKS = {'xTaskCreate':6, 'xTaskCreateStatic':7, 'xTaskCreatePinnedToCore':7,
         'xTaskCreateStaticPinnedToCore':8, 'osThreadNew':3, 'osThreadCreate':2}
OBJECTS = {
    '队列': ('xQueueCreate', 'xQueueCreateStatic', 'osMessageQueueNew', 'osMessageCreate'),
    '信号量': ('xSemaphoreCreateBinary', 'xSemaphoreCreateBinaryStatic', 'xSemaphoreCreateCounting',
            'xSemaphoreCreateCountingStatic', 'osSemaphoreNew', 'osSemaphoreCreate'),
    '互斥锁': ('xSemaphoreCreateMutex', 'xSemaphoreCreateMutexStatic', 'xSemaphoreCreateRecursiveMutex',
            'xSemaphoreCreateRecursiveMutexStatic', 'osMutexNew', 'osMutexCreate'),
    '事件组': ('xEventGroupCreate', 'xEventGroupCreateStatic', 'osEventFlagsNew'),
    '软件定时器': ('xTimerCreate', 'xTimerCreateStatic', 'osTimerNew', 'osTimerCreate'),
}
CATEGORY = {api:kind for kind, apis in OBJECTS.items() for api in apis}
SCHEDULER = {'vTaskStartScheduler':'启动调度器', 'osKernelStart':'启动调度器',
             'osKernelInitialize':'初始化内核', 'MX_FREERTOS_Init':'初始化入口'}
CALL = re.compile(r'\b('+'|'.join([*TASKS,*CATEGORY,*SCHEDULER,'osThreadDef'])+r')\s*\(')
ATTR = re.compile(r'\bosThreadAttr_t\s+(\w+)\s*=\s*\{')
IDENTIFIER = re.compile(r'[A-Za-z_]\w*')
MAX_ROWS = 300


def index(root, texts, hashes, platform):
    raw = {path.relative_to(root).as_posix():text for path,text in texts.items()}
    sources = {path:text for path,text in raw.items() if Path(path).suffix.lower() in {'.c','.cpp','.h'}}
    code = {path:masked(text) for path,text in sources.items()}
    evidence, tasks, objects, scheduler = [], [], [], []
    freertos = platform == 'esp32'
    cmsis = False
    truncated = False
    attrs, thread_defs = defaultdict(list), defaultdict(list)

    def anchor(path, offset, role):
        return dict(path=path,line=raw[path].count('\n',0,offset)+1,sha256=hashes[path],role=role)

    for path,text in raw.items():
        if path.lower().endswith('.ioc'):
            m = re.search(r'^(?:Mcu\.IP\d+=FREERTOS(?:_\w+)?[ \t]*\r?$|FREERTOS\.[^=\r\n]+=)',text,re.M)
            if m:
                freertos = True
                evidence.append(anchor(path,m.start(),'CubeMX FreeRTOS 配置'))
        if path not in sources:
            continue
        if Path(path).name.casefold() == 'freertosconfig.h':
            freertos = True
            evidence.append(anchor(path,0,'FreeRTOSConfig.h'))
        for m in re.finditer(r'^\s*#\s*include\s*[<"]([^>"\r\n]+)[>"]',text,re.M):
            if '#' not in code[path][m.start():m.start(1)]:
                continue
            header = Path(m[1]).name.casefold()
            if header in {'freertos.h','freertosconfig.h'}:
                freertos = True
                evidence.append(anchor(path,text.index('#',m.start(),m.start(1)),'FreeRTOS 头文件'))
            elif header in {'cmsis_os.h','cmsis_os2.h'}:
                cmsis = True
                evidence.append(anchor(path,text.index('#',m.start(),m.start(1)),'CMSIS-RTOS 头文件'))
        for m in ATTR.finditer(code[path]):
            end = balanced(code[path],m.end()-1,'{','}')
            if end is None:
                continue
            fields = {}
            for value in arguments(text,code[path],m.end(),end):
                field = re.fullmatch(r'\.(name|priority|stack_size)\s*=\s*(.+)',value,re.S)
                if field:
                    fields[field[1]] = field[2].strip()
            attrs[m[1]].append((path,fields,anchor(path,m.start(),'任务属性')))

    def unique(definitions, name, path):
        matches = definitions.get(name,[])
        local = [item for item in matches if item[0] == path]
        candidates = local or matches
        return candidates[0] if len(candidates)==1 else None

    for path,text in code.items():
        for m in re.finditer(r'\bosThreadDef\s*\(',text):
            prefix=text[text.rfind('\n',0,m.start())+1:m.start()]
            if re.match(r'\s*#',prefix):
                continue
            end=balanced(text,m.end()-1)
            if end is None:
                continue
            args=arguments(sources[path],text,m.end(),end)
            if len(args) in (4,5) and IDENTIFIER.fullmatch(args[0]):
                thread_defs[args[0]].append((path,args,anchor(path,m.start(),'任务定义')))
                cmsis=True

    defs = functions(sources) if any(CALL.search(text) for text in code.values()) else {}
    calls = []
    for entries in defs.values():
        for fn in entries:
            path = fn['path']
            start = fn['opening']+1
            for m in CALL.finditer(code[path],start,fn['end']):
                prefix = code[path][code[path].rfind('\n',0,m.start())+1:m.start()]
                if re.match(r'\s*(?:#|extern\b)',prefix):
                    continue
                end = balanced(code[path],m.end()-1)
                if end is None or end>=fn['end']:
                    continue
                api = m[1]
                args = arguments(sources[path],code[path],m.end(),end)
                proof = anchor(path,m.start(),api)
                if api=='osThreadDef':
                    continue
                handle = re.search(r'\b(\w+)\s*=\s*$',prefix)
                calls.append((path,fn['name'],api,args,proof,handle[1] if handle else ''))

    for path, caller, api, args, proof, handle in calls:
        family = 'CMSIS-RTOS' if api.startswith('os') else 'FreeRTOS'
        cmsis |= family == 'CMSIS-RTOS'
        freertos |= family == 'FreeRTOS'
        row = dict(api=api,caller=caller,evidence=[proof],family=family)
        if api in SCHEDULER:
            row.update(kind=SCHEDULER[api],name=api)
            scheduler.append(row)
            continue
        if api in CATEGORY:
            row.update(kind=CATEGORY[api],name=handle or api,details={})
            if api in {'xQueueCreate','xQueueCreateStatic','osMessageQueueNew'} and len(args)>=2:
                row['details']={'容量':args[0],'每项字节数':args[1]}
            elif len(args)>=2 and (api.startswith('xSemaphoreCreateCounting') or api=='osSemaphoreNew'):
                row['details']={'最大计数':args[0],'初始计数':args[1]}
            objects.append(row)
            continue
        if len(args)!=TASKS[api]:
            continue
        name,entry,priority,stack,unit = handle,'','','',''
        if api.startswith('xTask'):
            entry,name,stack,priority=args[0],literal(args[1]) or args[1],args[2],args[4]
            unit='字节' if platform=='esp32' else 'StackType_t 元素'
        elif api=='osThreadNew':
            entry=args[0]
            attr = unique(attrs,args[2].lstrip('&').strip(),path)
            if attr:
                _,fields,location=attr
                name=literal(fields.get('name','')) or name
                priority,stack,unit=fields.get('priority',''),fields.get('stack_size',''),'字节'
                row['evidence'].append(location)
        else:
            match=re.fullmatch(r'osThread\s*\(\s*(\w+)\s*\)',args[0])
            definition=unique(thread_defs,match[1],path) if match else None
            if definition:
                _,fields,location=definition
                name=fields[0]
                entry=fields[1] if len(fields)==5 else fields[0]
                priority,stack,unit=fields[-3],fields[-1],'按 v1 封装核对'
                row['evidence'].append(location)
        if IDENTIFIER.fullmatch(entry):
            candidates=defs.get(entry,[])
            local=[f for f in candidates if f['path']==path]
            matches=local or [f for f in candidates if not code[f['path']][f['start']:f['opening']].lstrip().startswith('static ')]
            if len(matches)==1:
                target=matches[0]
                row['evidence'].append(anchor(target['path'],target['start'],'任务入口'))
        row.update(kind='任务',name=name or entry or api,entry=entry,priority=priority,
                   stack=stack,stack_unit=unit)
        tasks.append(row)
    for rows in (evidence,tasks,objects,scheduler):
        truncated |= len(rows)>MAX_ROWS
        del rows[MAX_ROWS:]
    status = 'FreeRTOS 线索已发现' if freertos else 'CMSIS-RTOS 接口线索，内核待核对' if cmsis else '未发现 RTOS 配置或受支持的调用'
    return dict(status=status,tasks=tasks,objects=objects,scheduler=scheduler,
                evidence=evidence,truncated=truncated)
