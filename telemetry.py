"""Local-only serial recordings, deterministic demo data and numeric analysis."""
import codecs
import csv
import json
import math
from pathlib import Path
import re
import statistics as stats
import time
import uuid


def record_path(base, identifier):
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier): raise ValueError('记录编号无效')
    return Path(base)/identifier


class Recorder:
    def __init__(self, base):
        self.base=Path(base);self.active=None;self.pending='';self.header=None

    def start(self, source='serial', info=None):
        if self.active: raise ValueError('请先停止当前记录')
        identifier=uuid.uuid4().hex;folder=record_path(self.base,identifier);folder.mkdir(parents=True)
        self.active={'id':identifier,'source':source,'created':time.time(),'state':'recording',
                     'samples':0,'raw_events':0,'invalid_lines':0,'channels':[], 'info':info or {}}
        self.started=time.monotonic();self.pending='';self.header=None
        self.flush();return dict(self.active)

    def flush(self):
        folder=record_path(self.base,self.active['id']);temp=folder/'meta.tmp'
        temp.write_text(json.dumps(self.active,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(folder/'meta.json')

    def stop(self):
        if not self.active: return None
        if self.pending.strip(): self.active['invalid_lines']+=1
        self.pending=''
        self.active['state']='complete';self.active['ended']=time.time();self.flush()
        result=dict(self.active);self.active=None;return result

    def sample(self,t,values):
        if not self.active: return
        valid={k:float(v) for k,v in values.items() if isinstance(k,str) and 0<len(k)<=64 and
               re.fullmatch(r'[\w .-]+',k) and type(v) in (int,float) and math.isfinite(v)}
        valid={k:v for k,v in valid.items() if k in self.active['channels'] or len(self.active['channels'])<12}
        if not valid or not math.isfinite(t): self.active['invalid_lines']+=1;return
        for key in list(valid):
            if key not in self.active['channels']:
                if len(self.active['channels'])>=12: del valid[key]
                else: self.active['channels'].append(key)
        if not valid:return
        folder=record_path(self.base,self.active['id'])
        with (folder/'samples.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps({'t':t,'values':valid},ensure_ascii=False,allow_nan=False)+'\n')
        self.active['samples']+=1
        if self.active['samples']==1 or self.active['samples']%20==0:self.flush()
        if self.active['samples']>=100000:self.stop()

    def line(self,line):
        if not self.active:return
        try:
            if line.lstrip().startswith('{'):
                data=json.loads(line)
                if not isinstance(data,dict):raise ValueError()
            elif '=' in line:
                data={k:float(v) for k,v in re.findall(r'([A-Za-z_]\w*)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)',line)}
            else:
                row=next(csv.reader([line]))
                if self.header is None:
                    if not 2<=len(row)<=12 or any(not re.fullmatch(r'[A-Za-z_]\w*',key.strip()) for key in row):raise ValueError()
                    self.header=[key.strip() for key in row];return
                if len(row)!=len(self.header):raise ValueError()
                data=dict(zip(self.header,map(float,row)))
            stamp=data.pop('t',None)
            if stamp is not None and (type(stamp) not in (int,float) or not math.isfinite(stamp)):raise ValueError()
            self.sample(float(stamp) if stamp is not None else time.monotonic()-self.started,data)
        except (ValueError,TypeError,OverflowError,csv.Error):
            if self.active:self.active['invalid_lines']+=1

    def event(self,event):
        if not self.active or self.active['source']!='serial':return
        folder=record_path(self.base,self.active['id']);raw=folder/'raw.jsonl'
        if raw.exists() and raw.stat().st_size>50_000_000:self.stop();return
        with raw.open('a',encoding='utf-8') as file:file.write(json.dumps(event,ensure_ascii=False)+'\n')
        self.active['raw_events']+=1
        if event['direction']!='RX':return
        self.pending+=event['text']
        while '\n' in self.pending and self.active:
            line,self.pending=self.pending.split('\n',1)
            if line.strip():self.line(line.strip())
        if len(self.pending)>16384:
            self.pending=''
            if self.active:self.active['invalid_lines']+=1


def listing(base):
    result=[]
    if not Path(base).exists():return result
    for folder in Path(base).iterdir():
        if not re.fullmatch('[a-f0-9]{32}',folder.name):continue
        try:
            meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'));result.append(meta)
        except (OSError,ValueError):continue
    return sorted(result,key=lambda m:m['created'],reverse=True)[:100]


def load(base,identifier):
    folder=record_path(base,identifier)
    meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    rows=[]
    path=folder/'samples.jsonl'
    if path.exists():
        if path.stat().st_size>50_000_000:raise ValueError('记录超过首版分析大小限制')
        for line in path.read_text(encoding='utf-8').splitlines():
            try: rows.append(json.loads(line))
            except ValueError:continue # active append may end in a partial line
            if len(rows)>=100000:break
    return meta,rows


def analyze(base,identifier,channel,kind='generic',period=0,cpr=0,reference='',jump_limit=0):
    meta,rows=load(base,identifier)
    if channel not in meta['channels']:raise ValueError('请选择记录中的数值通道')
    if kind not in {'generic','angle','encoder'}:raise ValueError('通道类型无效')
    if type(period) not in (int,float) or not math.isfinite(period) or not 0<=period<=1e12:raise ValueError('回绕周期无效')
    if type(cpr) not in (int,float) or not math.isfinite(cpr) or not 0<=cpr<=1e9:raise ValueError('每圈计数无效')
    if type(jump_limit) not in (int,float) or not math.isfinite(jump_limit) or not 0<=jump_limit<=1e12:raise ValueError('突变阈值无效')
    points=[(r['t'],r['values'][channel],r['values'].get(reference)) for r in rows if channel in r['values']]
    if len(points)<3:raise ValueError('至少需要 3 个有效样本')
    ts=[p[0] for p in points];raw=[p[1] for p in points];values=[raw[0]];wraps=0
    steps=[];rates=[];dts=[];invalid_time=0
    for i in range(1,len(points)):
        delta=raw[i]-raw[i-1]
        corrected=(delta+period/2)%period-period/2 if period else delta
        wraps+=int(bool(period and abs(corrected-delta)>1e-8))
        values.append(values[-1]+corrected);steps.append(abs(corrected))
        dt=ts[i]-ts[i-1]
        if dt>0:rates.append(corrected/dt);dts.append(dt)
        else:invalid_time+=1
    median_step=stats.median(steps);mad=stats.median(abs(s-median_step) for s in steps)
    ordered=sorted(steps);p95=ordered[int(.95*(len(ordered)-1))]
    threshold=jump_limit or max(median_step+6*1.4826*mad,3*p95,1e-6)
    spikes=[i+1 for i,s in enumerate(steps) if s>threshold]
    interval=stats.median(dts) if dts else 0
    gaps=sum(dt>interval*3 for dt in dts) if interval else 0
    duration=ts[-1]-ts[0]
    error=[abs((v-ref+period/2)%period-period/2) if kind=='angle' and period else abs(v-ref) for (_,v,ref) in points if ref is not None]
    spike_set=set(spikes)
    series=[{'t':ts[i],'value':values[i],'raw':raw[i],'reference':points[i][2],'spike':i in spike_set} for i in range(len(points))]
    if len(series)>2000:
        stride=math.ceil(len(series)/1800);keep=set(range(0,len(series),stride))|set(spikes[:150])|{len(series)-1}
        series=[series[i] for i in sorted(keep)]
    return {'meta':meta,'channel':channel,'kind':kind,'period':period,'cpr':cpr,'count':len(points),
            'duration':duration,'mean':stats.mean(values),'stddev':stats.pstdev(values),
            'min':min(values),'max':max(values),'raw_min':min(raw),'raw_max':max(raw),
            'net_change':values[-1]-values[0],'median_interval':interval,
            'rate_mean':stats.mean(rates) if rates else None,'rate_min':min(rates) if rates else None,
            'rate_max':max(rates) if rates else None,'spike_count':len(spikes),'spike_threshold':threshold,
            'gap_count':gaps,'invalid_time_count':invalid_time,'wrap_count':wraps,
            'reference':reference,'mae':stats.mean(error) if error else None,
            'rotation_degrees':(values[-1]-values[0])*360/cpr if kind=='encoder' and cpr else None,
            'series':series,'notice':'突变和采样间隔异常是统计候选，不能直接认定设备故障。标准差含运动变化。回绕校正假设每次变化小于半周期；t 字段须为秒，否则使用本机接收时间。'}


def demo(base):
    recorder=Recorder(base);meta=recorder.start('simulation',{'scenario':'角度阶跃、编码器回绕、突变与采样间隔异常','rate_hz':20,'encoder_period':4096,'counts_per_turn':1024,'angle_jump_limit':10,'encoder_jump_limit':100})
    for i in range(400):
        t=i*.05+(.5 if i>=300 else 0)
        target=30.0 if i>=40 else 0.0
        age=max(0,(i-40)*.05)
        angle=(30*(1-math.exp(-age*1.5)*math.cos(age*3)) if i>=40 else 0)+.15*math.sin(i*.7)
        if i==180:angle+=45
        count=(4000+i*12+(300 if i==260 else 0))%4096
        recorder.sample(t,{'angle_deg':angle,'target_deg':target,'encoder_count':count})
    return recorder.stop()


def export_csv(base,identifier):
    meta,rows=load(base,identifier);folder=record_path(base,identifier);path=folder/'samples.csv'
    fields=meta['channels']
    with path.open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file);writer.writerow(['source','t_seconds']+["'"+f if f.startswith(('=','+','-','@')) else f for f in fields])
        for row in rows:writer.writerow([meta['source'],row['t']]+[row['values'].get(f,'') for f in fields])
    return str(path)
