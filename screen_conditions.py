"""Read C statement extents, including dangling else; do not execute C."""
import re
import operator
from usage_analysis import balanced


COMPARISONS = {
    '==': operator.eq, '!=': operator.ne, '<': operator.lt,
    '<=': operator.le, '>': operator.gt, '>=': operator.ge,
}
OPPOSITE = {'==':'!=', '!=':'==', '<':'>=', '<=':'>', '>':'<=', '>=':'<'}


def parse_guard(text, constants):
    text = text.strip()
    if len(text) > 512:
        return None
    while text.startswith('(') and balanced(text, 0) == len(text)-1:
        text = text[1:-1].strip()
    for token, key in (('||', 'any'), ('&&', 'all')):
        parts = []
        depth = start = 0
        for i, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if depth == 0 and text.startswith(token, i):
                parts.append(text[start:i])
                start = i + 2
        if parts:
            terms = [parse_guard(part, constants) for part in [*parts, text[start:]]]
            return {key: terms} if all(terms) else None
    match = re.fullmatch(
        r'(HAL_GetTick\s*\(\s*\)\s*-\s*\w+|[A-Za-z_]\w*)\s*'
        r'(==|!=|<=|>=|<|>)\s*(-?\d+|[A-Za-z_]\w*)', text)
    if not match:
        return None
    lhs, op, rhs = match.groups()
    value = int(rhs) if re.fullmatch(r'-?\d+', rhs) else constants.get(rhs)
    if value is None:
        return None
    name = re.sub(r'\s+', '', lhs)
    guard = dict(name=name, op=op, value=value)
    if name.startswith('HAL_GetTick()'):
        if op not in ('>=', '>') or not 0 <= value < 1e9:
            return None
        guard['refresh_seed'] = value + (op == '>')
    return guard


def negate(guard):
    for source, target in (('all', 'any'), ('any', 'all')):
        if source in guard:
            return {target: [negate(g) for g in guard[source]]}
    return dict(guard, op=OPPOSITE[guard['op']])


def leaves(guard):
    children = guard.get('all', guard.get('any'))
    if children is None:
        yield guard
    else:
        for child in children:
            yield from leaves(child)


def check(guard, values):
    """Return true, false, or unknown with the missing inputs for that decision."""
    for key, decisive in (('all', False), ('any', True)):
        if key in guard:
            missing = set()
            for child in guard[key]:
                result, inputs = check(child, values)
                if result is decisive:
                    return decisive, set()
                missing.update(inputs)
            return (None, missing) if missing else (not decisive, set())
    name = guard['name']
    if name not in values:
        return None, {name}
    return COMPARISONS[guard['op']](values[name], guard['value']), set()


def regions(code, start, end, constants=None):
    conditions=[];blocked=[]

    def whitespace(pos):
        while pos<end and code[pos].isspace():pos+=1
        return pos

    def word(pos,name):
        return code.startswith(name,pos) and (pos+len(name)>=end or not (code[pos+len(name)].isalnum() or code[pos+len(name)]=='_'))

    def statement(pos,depth=0):
        pos=whitespace(pos)
        if pos>=end or depth>80:return end
        if code[pos]=='{':
            close=balanced(code,pos,'{','}')
            return close+1 if close is not None else end
        if word(pos,'if'):
            op=whitespace(pos+2)
            close=balanced(code,op) if op<end and code[op]=='(' else None
            if close is None:return end
            stop=statement(close+1,depth+1);other=whitespace(stop)
            return statement(other+4,depth+1) if word(other,'else') else stop
        i=pos
        while i<end:
            if code[i] in '([{':
                close=balanced(code,i,code[i],{'(':')','[':']','{':'}'}[code[i]])
                if close is None:return end
                i=close+1
            elif code[i]==';':return i+1
            else:i+=1
        return end

    def add_region(a,b,guards,unknown):
        if unknown:blocked.append((a-1,b))
        else:
            conditions.extend(dict(g,start=a-1,end=b) for g in guards)

    def branch(pos,inherited=(),unknown=False,depth=0):
        if depth>80:return statement(pos)
        op=whitespace(pos+2);cl=balanced(code,op) if op<end and code[op]=='(' else None
        if cl is None:return end
        guard=parse_guard(code[op+1:cl], constants or {})
        a=whitespace(cl+1);b=statement(a)
        add_region(a,b,[*inherited,*([guard] if guard else [])],unknown or guard is None)
        walk(a,b,depth+1)
        other=whitespace(b)
        if not word(other,'else'):return b
        a=whitespace(other+4)
        reverse=negate(guard) if guard else None
        inherited=[*inherited,*([reverse] if reverse else [])]
        if word(a,'if'):return branch(a,inherited,unknown or guard is None,depth+1)
        b=statement(a);add_region(a,b,inherited,unknown or guard is None);walk(a,b,depth+1)
        return b

    def walk(a,b,depth=0):
        if depth>80:return
        pos=a
        # The block itself is a container, not a second copy of its if statement.
        if pos<b and code[pos]=='{':pos+=1
        while pos<b:
            m=re.search(r'\b(if|for|while|switch|do)\b',code[pos:b])
            if not m:return
            at=pos+m.start()
            if m[1]=='if':pos=branch(at,depth=depth+1)
            elif m[1]=='do':
                stop=statement(whitespace(at+2));blocked.append((at-1,stop));pos=stop
            else:
                op=whitespace(at+len(m[1]));cl=balanced(code,op) if op<b and code[op]=='(' else None
                if cl is None:pos=at+len(m[1]);continue
                stop=statement(cl+1);blocked.append((at-1,stop));pos=stop

    walk(start,end)
    # Nested statements inherit enclosing regions through their source extents.
    return conditions,blocked
