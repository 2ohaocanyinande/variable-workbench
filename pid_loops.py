"""Conservative PID-structure and local call-dependency index; no write authority."""
import hashlib
import re
from usage_analysis import masked, balanced
from device_inventory import split_arguments

NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]?'


def index(root, texts, hashes):
    functions=[]; types={}; loops=[]
    def evidence(path, offset, role):
        return {'path':path.relative_to(root).as_posix(),'line':texts[path].count('\n',0,offset)+1,
                'sha256':hashes[path.relative_to(root).as_posix()],'role':role}
    for path,text in texts.items():
        code=masked(text)
        for m in re.finditer(r'typedef\s+struct\s*(?:\w+\s*)?\{([^{}]+)\}\s*(\w+)\s*;',code):
            fields=re.findall(r'\b(?:float|double)\s+(\w+)\s*;',m[1])
            gains={f.lower():f for f in fields if f.lower() in {'kp','ki','kd'}}
            if len(gains)==3: types[m[2]]={'gains':gains,'evidence':evidence(path,m.start(),'增益字段声明')}
        if path.suffix not in {'.c','.cpp'}: continue
        definitions=list(re.finditer(r'\b(?:float|double|int|void|int\d+_t|uint\d+_t)\s+(\w+)\s*\(([^;{}]*)\)\s*\{',code))
        for number,m in enumerate(definitions):
            end=balanced(code,m.end()-1,'{','}')
            boundary=definitions[number+1].start() if number+1<len(definitions) else len(code)
            conditional=False
            # #if/#else may contain alternative opening braces. Counting both
            # branches loses the entire function. Preserve a bounded lexical
            # span, explicitly without claiming which branch is compiled.
            if (end is None or end>=boundary) and re.search(r'^\s*#\s*(?:if|ifdef|ifndef)\b',code[m.end():boundary],re.M):
                end=boundary;conditional=True
            if end is not None:
                functions.append({'name':m[1],'params':m[2],'body':code[m.end():end],
                                  'start':m.end(),'end':end,'path':path,'signature':code[m.start():m.end()],'conditional_span':conditional})
    kernels={}
    for function in functions:
        for type_name,info in types.items():
            p=re.search(r'\b'+re.escape(type_name)+r'\s*\*\s*(\w+)',function['params'])
            if not p: continue
            # A PID-like declaration alone is insufficient: gains must actually
            # participate in multiplication in a calculation function.
            used=[gain for gain in info['gains'].values() if re.search(re.escape(p[1])+r'\s*->\s*'+re.escape(gain)+r'\s*\*',function['body'])]
            if len(used)>=2: kernels.setdefault(function['name'],[]).append((function,type_name))
    for path,text in texts.items():
        if path.suffix not in {'.c','.cpp'}: continue
        code=masked(text)
        for type_name,info in types.items():
            if not any(t==type_name for group in kernels.values() for _,t in group): continue
            for m in re.finditer(r'(?m)^[ \t]*(?:static\s+)?'+re.escape(type_name)+r'\s+(\w+)\s*(?=[;=])',code):
                if code[:m.start()].count('{')!=code[:m.start()].count('}'): continue
                symbol=m[1];lid=hashlib.sha256((str(path.relative_to(root))+'::'+symbol).encode()).hexdigest()[:16]
                gains={}
                for key,field in info['gains'].items():
                    sources=[]
                    for owner,source in texts.items():
                        for a in re.finditer(r'\b'+re.escape(symbol)+r'\s*\.\s*'+re.escape(field)+r'\s*=\s*('+NUMBER+r')\s*;',masked(source)):
                            sources.append({**evidence(owner,a.start(),'增益赋值（执行条件待核对）'),
                                            'value':float(a[1].rstrip('fF')),'literal':a[1],
                                            'offset':a.start(1),'end':a.end(1)})
                    gains[key]={'field':field,'sources':sources,'value':sources[0]['value'] if len(sources)==1 else None}
                loops.append({'id':lid,'symbol':symbol,'type':type_name,'name':symbol,'category':'待确认',
                              'gains':gains,'calls':[],'kernels':[],
                              'evidence':[evidence(path,m.start(),'控制器实例声明'),info['evidence']],
                              'online_writable':False})
    edges=[]
    by_symbol={}
    for loop in loops: by_symbol.setdefault(loop['symbol'],[]).append(loop)
    # Keep calculation evidence even when a caller cannot be resolved. An
    # unused controller must not be sent to the model as a name-only record.
    for loop in loops:
        for candidates in kernels.values():
            for kernel,type_name in candidates:
                if type_name!=loop['type']: continue
                loop['kernels'].append({'function':kernel['name'],'code':kernel['body'][:5000],
                                       **evidence(kernel['path'],kernel['start'],'共享类型的计算实现，调用绑定待核对')})
    for group in by_symbol.values():
        if len(group)>1:
            for loop in group:
                for gain in loop['gains'].values(): gain['sources']=[];gain['value']=None
                loop['ambiguity']='同名实例跨文件存在，未绑定增益写入来源'
    for caller in functions:
        previous={}
        for call in re.finditer(r'\b(\w+)\s*\(',caller['body']):
            if call[1] not in kernels: continue
            end=balanced(caller['body'],call.end()-1)
            if end is None: continue
            args=split_arguments(caller['body'][call.end():end]);targets=[]
            for argument in args:
                match=re.fullmatch(r'&\s*(\w+)',argument)
                if match and len(by_symbol.get(match[1],[]))==1: targets+=by_symbol[match[1]]
            if len(targets)!=1: continue
            target=targets[0]
            compatible=[f for f,t in kernels[call[1]] if t==target['type']]
            if len(compatible)!=1: continue
            kernel=compatible[0]
            proof=evidence(caller['path'],caller['start']+call.start(),'控制器调用与输入输出关系')
            before='\n'.join(line.strip() for line in caller['body'][:call.start()].splitlines() if line.strip())[-4000:]
            after='\n'.join(line.strip() for line in caller['body'][call.start():end+500].splitlines() if line.strip())[:1800]
            sources=[]
            for argument in args:
                if not re.fullmatch(r'\w+',argument): continue
                # Follow a direct producer of this input in the same source
                # file, even if assignment occurs in a separate caller.
                file_code=masked(texts[caller['path']])
                producers=re.findall(r'\b'+re.escape(argument)+r'\s*=\s*(\w+)\s*\(',file_code)
                for producer in dict.fromkeys(producers):
                    matches=[f for f in functions if f['name']==producer and f['path']==caller['path']]
                    if len(matches)==1:
                        f=matches[0];sources.append(f['signature']+f['body'][:1800])
            context=before+'\n'+after+'\n'+'\n'.join(sources[:3])
            target['calls'].append({'function':call[1],'arguments':args,'caller':caller['name'],'conditional_span':caller['conditional_span'],'context':context,**proof})
            if not target.get('kernel_bound'):
                target['kernels']=[{'function':kernel['name'],
                                          'code':kernel['body'][:5000],**evidence(kernel['path'],kernel['start'],'PID 类计算实现')}] 
                target['kernel_bound']=True
            for output,(upstream,last_end,up_proof) in previous.items():
                between=caller['body'][last_end:call.start()]
                if re.search(r'\b'+re.escape(output)+r'\s*(?:=(?!=)|[+*/-]=|\+\+|--)',between): continue
                for argument in args:
                    if upstream!=target['id'] and re.search(r'\b'+re.escape(output)+r'\b',argument):
                        edges.append({'from':upstream,'to':target['id'],'signal':output,
                                      'kind':'条件编译下的依赖候选' if caller['conditional_span'] else ('串级候选' if argument.strip()==output else '叠加／混合依赖候选'),
                                      'argument':argument,'evidence':[up_proof,proof]})
            prefix=caller['body'][:call.start()].rsplit(';',1)[-1].rsplit('{',1)[-1]
            assignment=re.search(r'\b(\w+)\s*=\s*(?:\([^()]*\)\s*)?$',prefix)
            if assignment: previous[assignment[1]]=(target['id'],end,proof)
    unique={(e['from'],e['to'],e['signal']):e for e in edges}
    return {'loops':loops,'edges':list(unique.values()),
            'notice':'局部 C 代码索引，非完整数据流证明。环类型需结合目标、反馈、单位和执行条件确认；函数调用顺序本身不构成串级关系。',
            'limits':'首版支持结构体 Kp/Ki/Kd（大小写可不同）、数值字面量赋值和同一函数内的直接输出依赖；宏、数组控制器、独立散变量及复杂 C++ 待适配。'}
