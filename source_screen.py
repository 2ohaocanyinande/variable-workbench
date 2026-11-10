"""Static screen-call extraction. Never executes project code or model output."""
import ast
import hashlib
from pathlib import Path
import re
import math
from usage_analysis import masked,balanced
import screen_drivers
import screen_conditions

APIS={'OLED_ShowString':'text','OLED_ShowChar':'char','OLED_ShowNum':'number','OLED_ShowSignedNum':'signed','OLED_ShowHexNum':'hex','OLED_ShowBinNum':'binary','OLED_Clear':'clear'}
LCD_APIS={'LCD_DisplayStringLine':'text','LCD_DisplayChar':'char','LCD_Clear':'clear','LCD_ClearLine':'clear_line','LCD_SetTextColor':'foreground','LCD_SetBackColor':'background','LCD_ShowString':'text','LCD_ShowChar':'char'}
ALL_APIS={**APIS,**LCD_APIS}
LOW_LEVEL=re.compile(r'^(?:LCD|OLED)_(?:Write|Read|SetCursor|Ctrl|Bus|Power|DisplayOn|DisplayOff|SetDisplayWindow|WindowMode|Init|DrawChar|DrawPoint|SetPoint|I2C|W_SCL|W_SDA)')

def buffer_name(expr):
    return re.sub(r'^\(\s*(?:const\s+)?(?:u8|char|uint8_t)\s*\*\s*\)\s*','',expr).strip()

def constant_index(sources):
    definitions={}
    for raw in sources.values():
        for m in re.finditer(r'(?m)^\s*#define\s+(\w+)[ \t]+([^\n]+)',masked(raw)):
            definitions.setdefault(m[1],set()).add(m[2].strip())
    values={}
    for _ in range(12):
        changed=False
        for name,expressions in definitions.items():
            if name in values or len(expressions)!=1:continue
            value=evaluate(next(iter(expressions)),values)
            if value is not None:values[name]=value;changed=True
        if not changed:break
    return values

def initial_values(sources,defs,constants):
    found={}
    for path,raw in sources.items():
        code=masked(raw)
        # Only file-scope declarations. Runtime assignments are not initial values.
        spans=[f for fs in defs.values() for f in fs if f['path']==path]
        for f in spans:code=code[:f['start']]+' '*(f['end']+1-f['start'])+code[f['end']+1:]
        for m in re.finditer(r'\b(?:float|double|int|uint\d+_t|int\d+_t|u8|u16|u32|vu16)\s+([^;{}\n]+);',code):
            prefix=code[:m.start()]
            if prefix.count('{')!=prefix.count('}'):continue
            qualifier=re.split(r'[;{}]',prefix)[-1]
            if re.search(r'\b(?:extern|typedef)\b',qualifier):continue
            for item in m[1].split(','):
                part=re.fullmatch(r'\s*(\w+)\s*=\s*([^=]+)',item)
                zero=not part and name_is_scalar(item) and path.endswith(('.c','.cpp'))
                if not part and not zero:continue
                value=0 if zero else evaluate(part[2],constants)
                symbol=item.strip() if zero else part[1]
                if value is not None:found.setdefault(symbol,[]).append(dict(value=value,path=path,line=raw.count('\n',0,m.start())+1,origin='zero' if zero else 'explicit'))
    return {name:items[0] for name,items in found.items() if len(items)==1}

def name_is_scalar(text):
    return bool(re.fullmatch(r'\s*[A-Za-z_]\w*\s*',text))

def expression_symbols(expr):
    # A member path is one selectable input, never two independent identifiers.
    return set(re.sub(r'\s+','',m[0]) for m in re.finditer(r'\b[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*',masked(expr)))

def arguments(raw,code,start,end):
    result=[];first=start;depth=0
    for i in range(start,end):
        if code[i] in '([{':depth+=1
        elif code[i] in ')]}':depth-=1
        elif code[i]==',' and depth==0:result.append(raw[first:i].strip());first=i+1
    if raw[first:end].strip():result.append(raw[first:end].strip())
    return result

def literal(expr):
    parts=re.findall(r'"(?:\\.|[^"\\])*"',expr)
    if not parts or re.sub(r'"(?:\\.|[^"\\])*"','',expr).strip():return None
    try:return ''.join(ast.literal_eval(p) for p in parts)
    except (ValueError,SyntaxError):return None

def extract(scan):
    sources={}
    for name,sha in scan['files'].items():
        if not name.endswith(('.c','.cpp','.h')):continue
        path=(Path(scan['root'])/name).resolve()
        if not path.is_relative_to(Path(scan['root']).resolve()):continue
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('源码已变化，请重新扫描')
        try:sources[name]=raw.decode('utf-8-sig')
        except UnicodeDecodeError:sources[name]=raw.decode('gb18030',errors='replace')
    constants=constant_index(sources)
    profiles,defs=screen_drivers.detect(sources,constants)
    initial=initial_values(sources,defs,constants)
    # Initial foreground/background are traced to file-scope declarations or the
    # straight-line prefix of main. This is a preview seed, not runtime state.
    colors={k:int(initial[n]['value']) for k,n in [('foreground','TextColor'),('background','BackColor')] if n in initial}
    main=screen_drivers.one(defs,'main')
    if main:
        prefix=re.split(r'\b(?:if|for|while|switch)\s*\(',main['body'],maxsplit=1)[0]
        for m in re.finditer(r'LCD_Set(Text|Back)Color\s*\(([^()]*)\)',prefix):
            value=evaluate(m[2],constants)
            if value is not None:colors['foreground' if m[1]=='Text' else 'background']=int(value)
    for p in profiles.values():p['colors']=colors if p['id']!='oled' else dict(foreground=0xb3f6bc,background=0x071710,rgb24=True)
    groups=[];unsupported=[]
    for name,raw in sources.items():
        if not name.endswith(('.c','.cpp')):continue
        code=masked(raw)
        for fn in re.finditer(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t*]+)+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{',code):
            end=balanced(code,fn.end()-1,'{','}')
            if end is None or fn[1] in {'if','for','while','switch'} or fn[1] in ALL_APIS or LOW_LEVEL.match(fn[1]):continue
            calls=[]
            conditions,branches=screen_conditions.regions(code,fn.end(),end,constants)
            def guards_at(position):
                return [{k:v for k,v in c.items() if k not in ('start','end')}
                        for c in conditions if c['start']<position<c['end']]
            for call in re.finditer(r'\b('+ '|'.join(ALL_APIS)+r')\s*\(',code[fn.end():end]):
                pos=fn.end()+call.start();opening=fn.end()+call.end()-1;closing=balanced(code,opening)
                if closing is None:continue
                args=arguments(raw,code,opening+1,closing);kind=ALL_APIS[call[1]]
                profile='oled' if call[1] in APIS else 'lcd_xy' if call[1] in ('LCD_ShowString','LCD_ShowChar') else 'lcd_line'
                ei=1 if call[1]=='LCD_DisplayStringLine' else 2
                if kind in ('text','char','number','signed','hex','binary') and len(args)<=ei:continue
                expr=args[ei] if kind in ('text','char','number','signed','hex','binary') else '';text=literal(buffer_name(expr)) if kind=='text' else None
                producer=None
                buffer=buffer_name(expr)
                if kind=='text' and text is None and re.fullmatch(r'\w+',buffer):
                    for fmt in re.finditer(r'\b(snprintf|sprintf)\s*\(',code[fn.end():pos]):
                        op=fn.end()+fmt.end()-1;cl=balanced(code,op)
                        if cl is None:continue
                        fa=arguments(raw,code,op+1,cl);fi=2 if fmt[1]=='snprintf' else 1
                        if len(fa)>fi and fa[0]==buffer and literal(fa[fi]) is not None and not re.search(r'\b'+re.escape(buffer)+r'\b',code[cl+1:pos]):
                            if guards_at(op)==guards_at(pos) and not any(a<op<b and not a<pos<b for a,b in branches):
                                producer={'format':literal(fa[fi]),'expressions':fa[fi+1:],'source':raw[fn.end()+fmt.start():cl+1]}
                variables=sorted(expression_symbols(expr)) if text is None else []
                variables=[v for v in variables if v not in {'float','double','int','uint8_t','uint16_t','uint32_t','int16_t','int32_t'}]
                if producer:variables=sorted(expression_symbols(' '.join(producer['expressions'])))
                extra=args[:1] if profile=='lcd_line' else args[:2]
                if profile=='lcd_xy':extra+=args[3:6]
                variables=sorted((set(variables)|expression_symbols(' '.join(extra))) - set(constants))
                line=raw.count('\n',0,pos)+1
                calls.append({'id':f'{name}:{line}:{pos}','api':call[1],'kind':kind,'arguments':args,'expression':expr,'text':text,'variables':variables,
                              'path':name,'line':line,'sha256':scan['files'][name],'source':raw[pos:closing+1],'producer':producer,
                              'profile':profile,'blocked_condition':any(a<pos<b for a,b in branches),
                              'guards':guards_at(pos)})
            if not calls:continue
            buttons=[];guard_names={g['name'] for c in calls for guard in c['guards'] for g in screen_conditions.leaves(guard)}
            for cond in conditions:
                if cond.get('op')!='==':continue
                for assign in re.finditer(r'\b(\w+)\s*=\s*(\d+)\s*;',code[cond['start']+1:cond['end']]):
                    if assign[1] in guard_names:buttons.append({'input':cond['name'],'equals':cond['value'],'variable':assign[1],'value':int(assign[2]),'line':raw.count('\n',0,cond['start'])+1})
            identifier=hashlib.sha256((name+'::'+fn[1]+'::'+str(fn.start())).encode()).hexdigest()[:18]
            # Keep independent displays apart even if one function draws both.
            drawing_profiles={c['profile'] for c in calls if c['kind'] not in ('foreground','background','clear','clear_line')}
            for pid in sorted(drawing_profiles):
                subset=[c for c in calls if c['profile']==pid or (pid=='lcd_xy' and c['api'] in ('LCD_Clear','LCD_SetTextColor','LCD_SetBackColor'))]
                terms=[g for c in subset for guard in c['guards'] for g in screen_conditions.leaves(guard)]
                names=sorted({v for c in subset for v in c['variables']}|{g['name'] for g in terms}|{b['input'] for b in buttons})
                defaults={n:initial[n] for n in names if n in initial}
                for term in terms:
                    if 'refresh_seed' in term:
                        key=term['name'];value=term['refresh_seed']
                        if key not in defaults or defaults[key]['value']<value:
                            defaults[key]=dict(value=value,path=name,line=raw.count('\n',0,fn.start(1))+1,origin='refresh')
                groups.append({'id':identifier+'-'+pid,'name':fn[1],'path':name,'line':raw.count('\n',0,fn.start(1))+1,'calls':subset,'buttons':buttons,
                               'grid_verified':pid in profiles,'profile':profiles.get(pid),'constants':constants,'defaults':defaults,'variables':names})
    for name,raw in sources.items():
        if name.endswith(('.c','.cpp')):
            for m in re.finditer(r'\b((?:LCD|OLED|lv_label|u8g2)\w*)\s*\(',masked(raw)):
                owner=next((f for fs in defs.values() for f in fs if f['path']==name and f['opening']<m.start()<f['end']),None)
                if not owner or owner['name'] in ALL_APIS or LOW_LEVEL.match(owner['name']) or owner['name'].startswith('LCD_Draw'):continue
                if m[1] not in ALL_APIS and not LOW_LEVEL.match(m[1]):unsupported.append({'path':name,'line':raw.count('\n',0,m.start())+1,'api':m[1]})
    groups.sort(key=lambda g:(g['name']!='main',g['path'],g['line'],g['id']))
    # Recognize only a direct boolean toggle under a simple key condition. More
    # involved key state machines stay in the source table instead of being invented.
    for group in groups:
        guard_names={g['name'] for c in group['calls'] for guard in c['guards'] for g in screen_conditions.leaves(guard)}
        for fs in defs.values():
            for fn in fs:
                raw=sources[fn['path']];code=masked(raw)
                for m in re.finditer(r'\bif\s*\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\)\s*\{\s*(\w+)\s*=\s*!\s*\2\s*;',code[fn['opening']+1:fn['end']]):
                    if m[2] not in guard_names:continue
                    pos=fn['opening']+1+m.start()
                    group['buttons'].append(dict(input=m[1],variable=m[2],operation='toggle',path=fn['path'],line=raw.count('\n',0,pos)+1))
    return {'project_hash':scan['project_hash'],'root':scan['root'],'groups':groups[:100],'unsupported':unsupported[:60],
            'notice':'源码静态近似预览。支持数值或宏比较、且/或组合，以及明确标注的 HAL 定时刷新假定值。按函数内源码顺序组合所选调用，复杂控制流与真实硬件状态仍需核对。'}

def evaluate(expr,values):
    if len(expr)>200:return None
    try:
        expr=re.sub(r'(?<![\w.])(0[xX][0-9a-fA-F]+)[uUlL]+\b',r'\1',expr)
        expr=re.sub(r'(?<![\w.])(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]+\b',r'\1',expr)
        node=ast.parse(expr,mode='eval').body
        def walk(n,depth=0):
            if depth>12:raise ValueError()
            if isinstance(n,ast.Constant) and type(n.value) in (int,float):return n.value
            if isinstance(n,ast.Name):return float(values[n.id])
            if isinstance(n,ast.Attribute):
                parts=[];base=n
                while isinstance(base,ast.Attribute):parts.append(base.attr);base=base.value
                if not isinstance(base,ast.Name):raise ValueError()
                parts.append(base.id)
                if any(p.startswith('_') for p in parts):raise ValueError()
                return float(values['.'.join(reversed(parts))])
            if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):return walk(n.operand,depth+1)*(1 if isinstance(n.op,ast.UAdd) else -1)
            if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
                a,b=walk(n.left,depth+1),walk(n.right,depth+1)
                return a+b if isinstance(n.op,ast.Add) else a-b if isinstance(n.op,ast.Sub) else a*b if isinstance(n.op,ast.Mult) else a/b
            raise ValueError()
        value=walk(node)
        return value if math.isfinite(value) and abs(value)<=1e12 else None
    except (ValueError,TypeError,KeyError,SyntaxError,ZeroDivisionError,OverflowError):return None


def formatted(producer,values):
    index=0;warnings=[]
    def replace(match):
        nonlocal index
        if match[0]=='%%':return '%'
        expression=producer['expressions'][index] if index<len(producer['expressions']) else '?';index+=1
        value=evaluate(expression,values)
        if value is None:return '{'+expression+'}'
        flags,width,precision,kind=match.groups();width=min(int(width or 0),24);precision=min(int((precision or '.6')[1:]),6)
        if kind in 'diu':result=str(int(value))
        elif kind in 'xX':result=format(int(value),kind)
        elif kind=='f':result=f'{value:.{precision}f}'
        else:return '{'+expression+'}'
        if '+' in flags and value>=0:result='+'+result
        if '0' in flags:return result.zfill(width)
        return result.ljust(width) if '-' in flags else result.rjust(width)
    return re.sub(r'%%|%([+\-0 ]*)(\d*)(\.\d+)?[lh]*([diuxXfs])',replace,producer['format'])[:2000]


def render(report,data):
    group=next((g for g in report['groups'] if g['id']==data.get('group')),None)
    if not group:raise ValueError('屏幕调用组已变化，请重新读取源码')
    values=data.get('values',{});selected=data.get('calls',[])
    if not isinstance(values,dict) or len(values)>100 or not isinstance(selected,list) or len(selected)>500:raise ValueError('预览输入格式无效')
    if any(not isinstance(k,str) or len(k)>100 or type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e9 for k,v in values.items()):raise ValueError('预览变量应为有限数值')
    warnings=[]
    if not group['grid_verified']:return {'rows':[],'warnings':['未验证该工程的屏幕坐标约定，只能查看源码调用表，不生成猜测画面。']}
    profile=group['profile'];cols=profile['columns'];rows=profile['rows'];canvas=[[' ']*cols for _ in range(rows)]
    constants=group.get('constants',{});env={**constants,**values};draws=[]
    def color(value,rgb24=False):
        if value is None or not 0<=value<=0xffffff:return None
        value=int(value)
        if rgb24:return '#%06x'%value
        if value>0xffff:return None
        return '#%02x%02x%02x'%(((value>>11)&31)*255//31,((value>>5)&63)*255//63,(value&31)*255//31)
    colors=profile.get('colors',{});fg=color(colors.get('foreground'),colors.get('rgb24',False)) or '#ffffff';bg=color(colors.get('background'),colors.get('rgb24',False)) or '#000000'
    initial_bg=bg;missing_conditions=set();blocked_calls=[]
    for call in group['calls']:
        if call['id'] not in selected:continue
        condition, missing = screen_conditions.check({'all':call['guards']}, values)
        if condition is False:continue
        if missing:missing_conditions.update(missing);continue
        if call.get('blocked_condition'):blocked_calls.append(call['id']);continue
        args=call['arguments'];kind=call['kind'];pid=profile['id']
        if kind in ('foreground','background'):
            c=color(evaluate(args[0],env)) if args else None
            if c is None:warnings.append('颜色未确定：'+call['id']);continue
            if kind=='foreground':fg=c
            else:bg=c
            continue
        if kind=='clear':
            c=color(evaluate(args[0],env)) if args and call['api']=='LCD_Clear' else bg
            if c is None:warnings.append('清屏颜色未确定：'+call['id']);continue
            canvas=[[' ']*cols for _ in range(rows)];draws.append(dict(kind='clear',background=c));continue
        fw,fh=profile.get('font_width',0),profile.get('font_height',0);cf,cb=fg,bg
        if pid=='oled':
            row,col=(evaluate(a,env) for a in args[:2]);x=(col-1)*fw if col is not None else None;y=(row-1)*fh if row is not None else None
        elif pid=='lcd_line':
            y=evaluate(args[0],env);x=0 if call['api'] in ('LCD_DisplayStringLine','LCD_ClearLine') else 319-evaluate(args[1],env) if evaluate(args[1],env) is not None else None
            row=y/fh+1 if y is not None else None;col=x/fw+1 if x is not None else None
        else:
            if len(args)<6:warnings.append('SPI 文字参数不完整：'+call['id']);continue
            x,y=(evaluate(a,env) for a in args[:2]);size=evaluate(args[5],env)
            if size is None or size!=int(size) or size not in (12,16,24,32):warnings.append('未支持的字高：'+call['id']);continue
            fw,fh=int(size)//2,int(size);cf=color(evaluate(args[3],env));cb=color(evaluate(args[4],env))
            if cf is None or cb is None:warnings.append('文字颜色未确定：'+call['id']);continue
            if len(args)>6 and evaluate(args[6],env)!=0:warnings.append('叠加模式未适配，跳过 '+call['id']);continue
            row=col=1
        if x is None or y is None or x!=int(x) or y!=int(y) or not 0<=x<profile['width'] or not 0<=y<profile['height'] or (pid!='lcd_xy' and (row!=int(row) or col!=int(col))):warnings.append('坐标未确定或超出已核对布局：'+call['id']);continue
        if kind=='clear_line':
            canvas[int(row)-1]=[' ']*cols;draws.append(dict(kind='fill',x=0,y=int(y),width=profile['width'],height=fh,background=bg));continue
        if kind=='text':text=formatted(call['producer'],env) if call.get('producer') else call['text'] if call['text'] is not None else '{'+call['expression']+'}'
        elif call['kind']=='char':
            try:text=ast.literal_eval(call['expression'])
            except (ValueError,SyntaxError):text='{'+call['expression']+'}'
            if not isinstance(text,str):text='?'
        else:
            value=evaluate(call['expression'],env);width=evaluate(args[3],env) if len(args)>3 else None
            if value is None:text='{'+call['expression']+'}'
            elif width is None or not 1<=width<=16:text='?';warnings.append('数值宽度未确定：'+call['id'])
            else:
                width=int(width);number=int(value);kind=call['kind']
                if kind!='signed' and number<0:text='?';warnings.append('无符号显示传入负数，C 类型转换未模拟')
                else:
                    base=16 if kind=='hex' else 2 if kind=='binary' else 10
                    digits=format(abs(number),'X' if base==16 else 'b' if base==2 else 'd')[-width:].zfill(width)
                    text=(('+' if number>=0 else '-') if kind=='signed' else '')+digits
        text=text[:max(0,(profile['width']-int(x))//fw)]
        draws.append(dict(kind='text',x=int(x),y=int(y),text=text,font_width=fw,font_height=fh,foreground=cf,background=cb))
        if pid!='lcd_xy':
            for i,char in enumerate(text):canvas[int(row)-1][int(col)-1+i]=char
    if missing_conditions:warnings.insert(0,'请填写页面/条件的预览值：'+', '.join(sorted(missing_conditions)))
    if blocked_calls:warnings.append('有 '+str(len(blocked_calls))+' 项绘图位于暂未支持的条件或循环中，已跳过；详见下方调用表。')
    return {'rows':[''.join(row) for row in canvas],'draws':draws,'profile':profile,'background':initial_bg,'warnings':list(dict.fromkeys(warnings)),
            'notice':profile['title']+' · '+profile['transport']+'。'+report['notice']}
