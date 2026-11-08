"""Evidence-based local diagnostics. Trial proposals are not plant identification."""
import hashlib
import json
import math
from pathlib import Path
import statistics as stats
import uuid
import telemetry

NOTICE='统计现象不能唯一确定 PID 根因。建议是待验证的单变量试验，不是最优参数；不会自动下发。模拟响应为人工构造，不证明改动参数导致曲线改善。'


def percentile(values,fraction):
    values=sorted(values);return values[int((len(values)-1)*fraction)]


def diagnose(base,identifier,config,source_snapshot=None,save=True):
    if not isinstance(config,dict):raise ValueError('诊断配置格式无效')
    meta,rows=telemetry.load(base,identifier)
    mapping=config.get('mapping',{})
    if not isinstance(mapping,dict):raise ValueError('通道绑定格式无效')
    angle=mapping.get('angle');target=mapping.get('target')
    if angle not in meta['channels'] or target not in meta['channels'] or angle==target:
        raise ValueError('请分别选择实际角度与目标值通道，单位必须相同')
    if meta['state']=='recording':raise ValueError('请先停止记录，再进行 PID 诊断')
    for key,value in mapping.items():
        if key not in {'angle','target','gyro','output','integral','derivative'} or (value and value not in meta['channels']):
            raise ValueError('绑定了不存在的数值通道')
    if config.get('unit') not in {'deg','rad'}:raise ValueError('请确认角度单位为度或弧度')
    tolerance=config.get('tolerance',.3)
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or tolerance<=0:raise ValueError('误差带必须为正的有限数值')
    gains=config.get('pid',{})
    if not isinstance(gains,dict):raise ValueError('PID 参数格式无效')
    for value in gains.values():
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e12):raise ValueError('PID 参数无效')
    lower,upper=config.get('lower'),config.get('upper')
    limits_valid=all(type(v) in (int,float) and math.isfinite(v) for v in (lower,upper)) and lower<upper
    points=[r for r in rows if angle in r['values'] and target in r['values']]
    if len(points)<80:raise ValueError('PID 诊断至少需要 80 个同时含实际值和目标值的样本')
    times=[p['t'] for p in points];dts=[b-a for a,b in zip(times,times[1:])];positive=[d for d in dts if d>0]
    if not positive:raise ValueError('时间戳无有效递增区间')
    dt=stats.median(positive);bad_time=sum(d<=0 or d>3*dt for d in dts)
    jitter=stats.median(abs(d-dt) for d in positive)/dt
    e=[p['values'][angle]-p['values'][target] for p in points]
    # Assess the final 60% separately from initial recovery/transient motion.
    first=int(len(points)*.4);tail=e[first:];tail_points=points[first:];tail_times=times[first:]
    target_span=max(p['values'][target] for p in tail_points)-min(p['values'][target] for p in tail_points)
    target_fixed=target_span<=tolerance
    mean=stats.mean(tail);centered=[v-mean for v in tail]
    amplitude=(percentile(tail,.95)-percentile(tail,.05))/2
    rms=lambda values:math.sqrt(stats.mean(v*v for v in values))
    middle=len(tail)//2;early=rms(centered[:middle]);late=rms(centered[middle:]);decay=late/max(early,1e-12)
    crossings=[];state=0;deadband=max(tolerance*.2,amplitude*.08)
    for i,value in enumerate(centered):
        current=1 if value>deadband else -1 if value<-deadband else 0
        if current and current!=state:
            if current==1 and state==-1:crossings.append(tail_times[i])
            state=current
    frequency=1/stats.median([b-a for a,b in zip(crossings,crossings[1:])]) if len(crossings)>=4 else None
    full_turn=360 if config['unit']=='deg' else 2*math.pi
    discontinuities=sum(abs(b['values'][angle]-a['values'][angle])>full_turn/2 for a,b in zip(points,points[1:]))
    cadence_ok=not bad_time and jitter<.1 and not discontinuities
    if frequency and frequency>=.4/dt:frequency=None
    def channel(key):
        name=mapping.get(key)
        return [p['values'][name] for p in tail_points] if name and all(name in p['values'] for p in tail_points) else None
    output=channel('output');integral=channel('integral');derivative=channel('derivative')
    def correlation(a,b):
        if not a or not b:return None
        ma,mb=stats.mean(a),stats.mean(b);sa,sb=stats.pstdev(a),stats.pstdev(b)
        return stats.mean((x-ma)*(y-mb) for x,y in zip(a,b))/(sa*sb) if sa*sb>1e-12 else None
    d_correlation=correlation(derivative,output)
    saturation=sum(v<=lower+.02*(upper-lower) or v>=upper-.02*(upper-lower) for v in output)/len(output) if output and limits_valid else None
    settling=None
    for i in range(len(points)-1,-1,-1):
        if abs(e[i])>tolerance:
            if i+1<len(points) and times[-1]-times[i+1]>=1:settling=times[i+1]-times[0]
            break
    else:settling=0.0
    metrics={'samples':len(points),'duration':times[-1]-times[0],'dt':dt,'time_anomalies':bad_time,'timing_jitter_ratio':jitter,
             'initial_error':e[0],'target_mean':stats.mean(p['values'][target] for p in points),
             'tail_rms_error':rms(tail),'tail_bias':mean,'max_abs_error':max(map(abs,e)),
             'amplitude':amplitude,'frequency_hz':frequency if cadence_ok and target_fixed else None,
             'amplitude_ratio':decay,'settling_seconds':settling,'saturation_fraction':saturation,
             'derivative_std':stats.pstdev(derivative) if derivative else None,'d_output_correlation':d_correlation,'integral_change':integral[-1]-integral[0] if integral else None}
    findings=[];warnings=[];proposal=None
    def add(code,title,evidence,causes,checks,direction):
        findings.append({'code':code,'title':title,'evidence':evidence,'possible_causes':causes,'checks':checks,'direction':direction,'confidence':'现象有数据支持，参数原因待验证'})
    if bad_time or jitter>=.1:warnings.append('时间戳存在间隔异常或抖动：暂不做频率归因和数值调参建议')
    if discontinuities:warnings.append('角度存在超过半圈的单步变化，可能回绕或异常点；请先提供连续角度，不生成数值方案')
    if not target_fixed:warnings.append('后段目标仍在变化，不能按固定目标判断持续震荡')
    persistent=cadence_ok and target_fixed and frequency is not None and amplitude>2*tolerance and decay>=.8
    derivative_dominant=bool(derivative and output and stats.pstdev(derivative)>.7*max(stats.pstdev(output),1e-9))
    if persistent:
        add('oscillation','持续震荡候选',[f'后段振幅约 {amplitude:.3g} {config["unit"]}',f'震荡频率约 {frequency:.3g} Hz',f'后半段/前半段幅度比 {decay:.3g}'],
            ['增益与阻尼不匹配','采样/滤波时延','机械间隙或摩擦','其他控制环耦合'],
            ['确认反馈方向和被调内/外环','确认输出未顶到限幅','检查采样周期及滤波延迟'],
            '在这些条件确认后，可把小幅降低 P 作为单变量试验；不能仅据角度曲线认定 P 过大或直接加大 D。')
    if cadence_ok and target_fixed and frequency and frequency>.1/dt and derivative_dominant and d_correlation is not None and abs(d_correlation)>.7:
        add('derivative_noise','高频抖动与微分项同步候选',[f'相对采样率的震荡频率 {frequency*dt:.3g}',f'D 项标准差 {stats.pstdev(derivative):.3g}',f'D 项与输出相关系数 {d_correlation:.3g}（相关不等于因果）'],
            ['测量噪声被微分放大','微分滤波或采样配置不合适'],['核对 D 的实现、单位和滤波','对比原始陀螺仪与控制输出'],
            '优先检查微分滤波与采样；必要时单独小幅降低 D，暂不自动计算替代值。')
    if saturation is not None and saturation>.2:
        growing=bool(integral and abs(integral[-1])>abs(integral[0])+tolerance)
        add('windup' if growing else 'saturation','输出饱和并伴随积分累积' if growing else '输出长时间饱和',
            [f'后段饱和占比 {saturation:.1%}']+([f'I 项净变化 {integral[-1]-integral[0]:.3g}'] if integral else []),
            ['执行器能力或限幅约束','存在积分时可能发生积分累积'],['核对真实限幅和输出单位','核对积分限幅/抗饱和','核对电源与负载'],
            '先处理输出限幅与抗积分饱和；不直接通过加大 P 或 I 追赶目标。')
    if target_fixed and abs(mean)>tolerance and stats.pstdev(tail)<tolerance:
        add('bias','稳态偏差候选',[f'后段平均误差 {mean:.3g} {config["unit"]}'],['零点偏置','摩擦或负载','积分配置'],
            ['先核对机械/传感器零点','核对是否已饱和'], '先区分零点与控制偏差，再决定是否需要积分，不能直接增大 I。')
    if not findings:
        add('no_persistent_oscillation','当前窗口未发现满足规则的持续震荡', [f'后段 RMS 误差 {rms(tail):.3g}',f'幅度比 {decay:.3g}'],
            ['可能正在衰减或已回稳；也可能数据条件不足'],['这不是实车稳定性证明','结合目标值、输出和其他工况复核'], '暂不生成数值修改。')
    confirmed=config.get('parameters_confirmed') is True and config.get('feedback_verified') is True
    declared_dt=config.get('sample_dt')
    dt_matches=type(declared_dt) in (int,float) and math.isfinite(declared_dt) and declared_dt>0 and abs(declared_dt-dt)<=dt*.1
    pid_known=all(type(gains.get(k)) in (int,float) and math.isfinite(gains[k]) and gains[k]>=0 for k in ('kp','ki','kd'))
    if persistent and saturation is not None and saturation<.05 and not derivative_dominant and confirmed and pid_known and dt_matches and gains['kp']>0:
        proposal={'parameter':'kp','before':gains['kp'],'after':gains['kp']*.95,'status':'单变量试验候选，尚未验证',
                  'reason':'持续震荡、已配置输出限幅且未明显饱和；参数、反馈方向和采样周期由用户确认。P 降低 5% 仅作保守试验步长，并非辨识或最优整定。'}
    else:warnings.append('数值方案需同时满足：参数及反馈已确认、周期吻合、输出限幅已知、未明显饱和、无明显 D 项噪声。')
    folder=telemetry.record_path(base,identifier)
    report={'id':uuid.uuid4().hex,'record_id':identifier,'source':meta['source'],'metrics':metrics,'findings':findings,'warnings':warnings,
            'proposal':proposal,'config':config,'record_snapshot':meta.get('info',{}).get('snapshot'),
            'source_snapshot':source_snapshot,'data_sha256':hashlib.sha256((folder/'samples.jsonl').read_bytes()).hexdigest(),
            'notice':NOTICE,'series':[{'t':p['t'],**{key:p['values'].get(value) for key,value in mapping.items() if value}} for p in points[::max(1,len(points)//1200)]]}
    if save:
        directory=folder/'diagnoses';directory.mkdir(exist_ok=True)
        path=directory/(report['id']+'.json');report['report_path']=str(path)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return report


def compare(base,before_id,after_id,config):
    if before_id==after_id:raise ValueError('请选择两条不同的记录')
    def report(identifier):
        meta,_=telemetry.load(base,identifier);snapshot=meta.get('info',{}).get('snapshot') or {}
        actual={**config,**{k:snapshot[k] for k in ('pid','sample_dt','lower','upper','unit') if snapshot.get(k) is not None}}
        return diagnose(base,identifier,actual,save=False)
    before=report(before_id);after=report(after_id)
    a,b=before['metrics'],after['metrics'];warnings=[]
    if before['source']!=after['source']:warnings.append('记录来源不同，不判定改善')
    if abs(a['target_mean']-b['target_mean'])>config.get('tolerance',.3):warnings.append('目标值不一致')
    if abs(a['dt']-b['dt'])>a['dt']*.1:warnings.append('采样周期不同')
    if abs(a['duration']-b['duration'])>max(a['duration'],b['duration'])*.1:warnings.append('记录长度不同')
    if abs(abs(a['initial_error'])-abs(b['initial_error']))>config.get('tolerance',.3):warnings.append('初始扰动幅度不同')
    ma,_=telemetry.load(base,before_id);mb,_=telemetry.load(base,after_id)
    sa=ma.get('info',{}).get('snapshot');sb=mb.get('info',{}).get('snapshot')
    if a['time_anomalies'] or b['time_anomalies']:warnings.append('存在异常时间戳')
    if not sa or not sb:warnings.append('缺少记录时的参数／工况快照，只展示统计值')
    elif sa.get('unit')!=sb.get('unit') or sa.get('unit')!=config['unit']:warnings.append('快照单位不匹配')
    elif not sa.get('experiment_id') or sa.get('experiment_id')!=sb.get('experiment_id'):warnings.append('未确认同一组对照工况，只展示统计值')
    if sa and sb and (sa.get('lower')!=sb.get('lower') or sa.get('upper')!=sb.get('upper')):warnings.append('两次输出限幅不同，饱和统计需分开复核')
    result={'before_id':before_id,'after_id':after_id,'source':before['source'],'before':a,'after':b,
            'snapshots':{'before':sa,'after':sb},'warnings':warnings,
            'rms_reduction_percent':100*(a['tail_rms_error']-b['tail_rms_error'])/a['tail_rms_error'] if a['tail_rms_error']>1e-12 and not warnings else None,
            'notice':'只比较这两段数据的统计表现，不证明参数改动导致改善；工况和单位需另行确认。'}
    directory=Path(base)/'comparisons';directory.mkdir(exist_ok=True)
    path=directory/(uuid.uuid4().hex+'.json');result['report_path']=str(path)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result


def demos(base):
    experiment=uuid.uuid4().hex;records=[]
    for scenario,label,pid in [('oscillating','持续震荡示例',{'kp':15,'ki':0,'kd':.75}),('damped','改善曲线示例',{'kp':14.25,'ki':0,'kd':.75}),
                               ('noise','微分噪声示例',{'kp':15,'ki':0,'kd':.75}),('windup','饱和积分示例',{'kp':15,'ki':2,'kd':.75})]:
        recorder=telemetry.Recorder(base)
        snapshot={'pid':pid,'sample_dt':.02,'lower':-1000 if scenario!='windup' else -100,'upper':1000 if scenario!='windup' else 100,
                  'unit':'deg','loop_symbol':'DEMO_ANGLE_LOOP','origin':'模拟参数标签，非实车回读','experiment_id':experiment,
                  'note':'人工构造信号用于验证诊断；不通过被控对象模型推导响应，不证明这组参数产生该曲线。'}
        meta=recorder.start('simulation',{'scenario':label,'tuning_scenario':scenario,'snapshot':snapshot,'experiment_id':experiment})
        previous=None
        for i in range(600):
            t=i*.02
            if scenario=='oscillating': angle=10*math.exp(-.015*t)*math.cos(2*math.pi*1.2*t)
            elif scenario=='damped':angle=10*math.exp(-1.1*t)*math.cos(2*math.pi*1.2*t)
            elif scenario=='noise':angle=10*math.exp(-3*t)+.4*math.sin(2*math.pi*12*t)
            else:angle=10*math.exp(-.5*t)+2
            gyro=(angle-previous)/.02 if previous is not None else 0;previous=angle
            p=-pid['kp']*angle;iterm=20*t if scenario=='windup' else 0
            d=-pid['kd']*gyro;out=max(snapshot['lower'],min(snapshot['upper'],p+iterm+d))
            if scenario=='windup':out=100
            recorder.sample(t,{'angle_deg':angle,'target_deg':0,'gyro_dps':gyro,'control_out':out,'p_out':p,'i_out':iterm,'d_out':d})
        saved=recorder.stop();records.append(saved)
    return {'experiment_id':experiment,'records':records,'notice':NOTICE}
