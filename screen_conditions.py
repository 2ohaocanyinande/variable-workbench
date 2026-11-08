"""Read C statement extents, including dangling else; do not execute C."""
import re
from usage_analysis import balanced


def regions(code, start, end):
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
        m=re.fullmatch(r'\s*([A-Za-z_]\w*)\s*(==|!=)\s*(\d+)\s*',code[op+1:cl])
        guard=dict(name=m[1],op=m[2],value=int(m[3])) if m else None
        a=whitespace(cl+1);b=statement(a)
        add_region(a,b,[*inherited,*([guard] if guard else [])],unknown or guard is None)
        walk(a,b,depth+1)
        other=whitespace(b)
        if not word(other,'else'):return b
        a=whitespace(other+4)
        reverse=dict(guard,op='!=' if guard['op']=='==' else '==') if guard else None
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
    unique={tuple(c[k] for k in ('name','op','value','start','end')):c for c in conditions}
    return list(unique.values()),blocked
