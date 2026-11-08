// A guided presentation of real local reports over explicitly synthetic records.
const demoState={records:null,reports:{},comparison:null,scenario:'oscillating',stage:0,loaded:false,loading:false,time:0,timer:null,playing:false,after:false};
const demoScenes={
  oscillating:{title:'车身一直在晃，先看数据怎么说。',copy:'目标是保持直立。角度反复穿过目标，摆动没有很快消失。',finding:'持续震荡候选',direction:'先检查反馈、采样与限幅，再做单变量试验。'},
  noise:{title:'细小但很快的抖动，未必该加大 D。',copy:'把高频抖动与微分项、控制输出放在一起看，避免仅凭曲线改参数。',finding:'高频抖动与微分项同步候选',direction:'先看微分滤波与采样，避免放大测量噪声。'},
  windup:{title:'输出已经到顶，再追目标也未必有效。',copy:'控制输出被限制在上限，积分项仍在累积。先分清执行器约束与参数问题。',finding:'输出饱和并伴随积分累积',direction:'先检查限幅与抗积分饱和，再考虑改动增益。'}
};
function demoFormat(value,digits=2){return Number.isFinite(value)?value.toFixed(digits):'—';}
function demoConfig(meta){return {...meta.info.snapshot,mapping:{angle:'angle_deg',target:'target_deg',gyro:'gyro_dps',output:'control_out',integral:'i_out',derivative:'d_out'},tolerance:.3,parameters_confirmed:true,feedback_verified:true,confirmation_origin:'已知的内置模拟数据标签；非设备参数回读'};}
function findDemoGroup(records){
  const groups=new Map();for(const record of records){const id=record.info?.experiment_id,key=record.info?.tuning_scenario;if(record.source!=='simulation'||record.state==='recording'||!id||!['oscillating','damped','noise','windup'].includes(key))continue;
    if(!groups.has(id))groups.set(id,{});groups.get(id)[key]=record;}
  return [...groups.values()].find(group=>['oscillating','damped','noise','windup'].every(key=>group[key]?.info?.snapshot&&group[key].samples>=80))||null;
}
function setDemoBusy(busy){
  demoState.loading=busy;$('demo-start').disabled=busy;$('demo-start').classList.toggle('demo-loading',busy);$('demo-next').disabled=busy||!demoState.loaded;
  for(const key of Object.keys(demoScenes))$('demo-scenario-'+key).disabled=busy;
  for(let i=0;i<4;i++)$('demo-step-'+i).disabled=busy||!demoState.loaded;
}
async function prepareShowcase(){
  if(demoState.loading)return;stopDemoReplay();setDemoBusy(true);$('demo-status').className='';$('demo-status').textContent='正在载入模拟记录并运行本地诊断…';
  const started=Date.now();
  try{
    if(!demoState.records){let records=findDemoGroup((await api('records')).records||[]);if(!records)records=findDemoGroup((await api('tuning-demo',{})).records);if(!records)throw new Error('模拟记录不完整，请重试');demoState.records=records;}
    const records=demoState.records;
    const keys=['oscillating','damped','noise','windup'];
    const results=await Promise.all(keys.map(key=>api('tuning-diagnose',{id:records[key].id,config:demoConfig(records[key])})));
    const comparison=await api('tuning-compare',{before:records.oscillating.id,after:records.damped.id,config:demoConfig(records.oscillating)});
    demoState.reports=Object.fromEntries(keys.map((key,i)=>[key,results[i]]));demoState.comparison=comparison;demoState.loaded=true;demoState.stage=0;demoState.time=0;demoState.after=false;
    renderShowcase();$('demo-status').textContent='4 组模拟记录已就绪 · 本地处理 '+((Date.now()-started)/1000).toFixed(1)+' 秒 · 可点击步骤或「分析这段波形」继续。';
    $('demo-start').textContent='重新开始演示 ↻';if(!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)playDemoReplay();
  }catch(error){$('demo-status').className='demo-error';$('demo-status').textContent='载入失败：'+error.message+'。点击开始可重试。';}
  finally{setDemoBusy(false);}
}
function setDemoStage(stage){
  if(!demoState.loaded)return;demoState.stage=Math.max(0,Math.min(3,stage));demoState.after=demoState.stage===3&&demoState.scenario==='oscillating';demoState.time=0;renderShowcase();
  $('demo-status').textContent=demoState.after?'当前叠加两组模拟角度曲线；姿态示意跟随绿色对照数据。':'当前展示的是模拟记录。诊断依据和参数快照保存在本机。';
}
function demoMetric(key,label,value,copy){$('demo-metric-'+key+'-label').textContent=label;$('demo-metric-'+key).textContent=value;$('demo-metric-'+key+'-copy').textContent=copy;}
function renderShowcase(){
  const s=demoState,scene=demoScenes[s.scenario],report=s.reports[s.scenario],m=report?.metrics,stage=s.stage,hasComparison=s.scenario==='oscillating';
  for(const key of Object.keys(demoScenes)){const selected=key===s.scenario;$('demo-scenario-'+key).classList.toggle('active',selected);$('demo-scenario-'+key).setAttribute('aria-pressed',String(selected));}
  for(let i=0;i<4;i++){$('demo-step-'+i).setAttribute('aria-current',i===stage?'step':'false');$('demo-step-'+i).disabled=!s.loaded||s.loading;}
  $('demo-final-step').textContent=hasComparison?'对照数据':'诊断小结';$('demo-stage-label').textContent=['01 / 看到问题','02 / 找到依据','03 / 给出方向',hasComparison?'04 / 对照数据':'04 / 诊断小结'][stage];
  $('demo-stage-title').textContent=stage===0?scene.title:stage===1?'用数据解释现象，保留判断依据。':stage===2?'给出下一步，而不是直接猜一组参数。':hasComparison?'两组数据，差异一眼可见。':'把排查方向带回工程。';
  $('demo-stage-copy').textContent=stage===0?scene.copy:stage===1?'角度告诉我们发生了什么；输出、积分与微分项帮助缩小排查范围。':stage===2?'每次只动一个变量，记录当时的参数，保留一条可回溯的试验路径。':hasComparison?'橙色是持续震荡样本，绿色是人工构造的回稳样本；用同一时间轴比较表现。':'数据先留下来，带着证据检查实现与配置，之后再验证实车响应。';
  $('demo-next').textContent=stage===0?'分析这段波形 →':stage===1?'查看处理方向 →':stage===2?(hasComparison?'对照两组数据 →':'查看诊断小结 →'):'从头再看 ↻';
  $('demo-next').disabled=!s.loaded||s.loading;$('demo-details').disabled=!s.loaded;$('demo-play').disabled=!s.loaded;$('demo-cursor').disabled=!s.loaded;
  $('demo-chart-badge').textContent=s.loaded?(s.after?'两组模拟记录对照':'模拟数据 · 50 Hz'):'等待载入';$('demo-before-legend').textContent=s.after?'持续震荡样本':'实际角度';$('demo-after-legend').hidden=!s.after;
  $('demo-chart-note').textContent=s.after?'两条曲线分别人工构造，不证明将 Kp 从 15 改成 14.25 能让实车得到此响应。':'模拟信号用于验证软件流程；姿态示意跟随记录数据，不代表真实机械模型。';
  $('demo-insight-label').textContent=['这一步看什么','本地诊断发现','下一步怎么做',hasComparison?'对照样本表现':'这次带走什么'][stage];
  $('demo-insight-title').textContent=stage===0?'先看到现象':stage===1?scene.finding:stage===2?(report?.proposal?'单独试调 Kp':'先排查，再改参数'):hasComparison?'从持续摆动，到逐渐回稳':'一份可回溯的报告';
  $('demo-insight-copy').textContent=stage===0?'曲线不对劲，不等于已经知道哪个参数有问题。先把目标与实际值放到一起看。':stage===1?scene.direction:stage===2?(report?.proposal?'模拟参数标签：Kp '+demoFormat(report.proposal.before)+' → '+demoFormat(report.proposal.after)+'。这是待验证的小步试验，不是最优参数。':scene.direction):hasComparison?'对照数据约 '+demoFormat(s.reports.damped?.metrics.settling_seconds,1)+' 秒进入 ±0.3° 误差带。这里只展示两段样本的统计差别。':'原始曲线、信号映射、参数标签和诊断依据都已留在本机。';
  if(!s.loaded||stage===0){demoMetric('a','观察窗口','12 秒','同一时间轴，连续观察。');demoMetric('b','运行来源','模拟数据','无需开发板与 API Key。');demoMetric('c','分析方式','本地计算','点击下一步，查看实际计算的结果。');}
  else if(stage===1){
    if(s.scenario==='windup'){demoMetric('a','后段输出饱和占比',demoFormat(m.saturation_fraction*100,0)+'%','输出已贴近配置的限幅。');demoMetric('b','后段积分项净变化','+'+demoFormat(m.integral_change,1),'积分项仍在累积（输出单位）。');}
    else{demoMetric('a','震荡频率约',demoFormat(m.frequency_hz)+' Hz','由当前模拟样本计算。');demoMetric('b',s.scenario==='noise'?'D 项与输出相关系数':'后段角度摆幅约',s.scenario==='noise'?demoFormat(m.d_output_correlation,3):'±'+demoFormat(m.amplitude)+'°',s.scenario==='noise'?'相关不等于因果，需要检查实现。':'目标固定，摆动没有明显消退。');}
    demoMetric('c','证据可回看',report.metrics.samples+' 个样本','展开下方依据，可查看保存的诊断结果。');
  }else if(stage===2){
    demoMetric('a',report.proposal?'本次仅试一个参数':'优先排查',report.proposal?'Kp −5%':s.scenario==='noise'?'采样 / 滤波':'限幅 / 积分','条件化方向，仍需硬件验证。');
    demoMetric('b',report.proposal?'试验值（模拟标签）':'数值方案',report.proposal?demoFormat(report.proposal.before)+' → '+demoFormat(report.proposal.after):'暂不生成',report.proposal?'小步试验值，不是自动整定结果。':'当前现象不足以直接给出替代参数。');demoMetric('c','工程与设备状态','未修改','建议与报告留存在本机。');
  }else if(hasComparison){
    const c=s.comparison;demoMetric('a','持续震荡样本 · 后段 RMS',demoFormat(c.before.tail_rms_error,2)+'°','RMS 是均方根误差，越小表示越接近目标。');demoMetric('b','回稳样本 · 后段 RMS',demoFormat(c.after.tail_rms_error,3)+'°','两组样本使用同一统计窗口。');demoMetric('c','回稳样本进入误差带',demoFormat(c.after.settling_seconds,1)+' 秒','仅对这段模拟曲线成立。');
  }else{demoMetric('a','先处理',s.scenario==='noise'?'采样与滤波':'输出约束',scene.direction);demoMetric('b','本机已保存','诊断报告','数据依据、参数与记录指纹可回溯。');demoMetric('c','下一步','实车验证','在完整工作台中复核源码与参数。');}
  if(report){const proof=$('demo-proof-content');proof.textContent='';proof.append(element('p','记录：'+s.records[s.scenario].id+' · 模拟样本 '+report.metrics.samples+' 个'));for(const f of report.findings)proof.append(element('p',f.title+'：'+f.evidence.join('；')));proof.append(element('p','报告位置：'+report.report_path));const details=element('details');details.append(element('summary','参数快照与样本指纹'),element('pre',JSON.stringify({模拟参数标签:report.record_snapshot,样本SHA256:report.data_sha256,proposal:report.proposal},null,2)));proof.append(details);}
  drawDemoChart();
}
function stopDemoReplay(){if(demoState.timer!==null)clearInterval(demoState.timer);demoState.timer=null;demoState.playing=false;$('demo-play').textContent='播放';}
function playDemoReplay(){
  if(!demoState.loaded||demoState.playing)return;demoState.playing=true;$('demo-play').textContent='暂停';
  demoState.timer=setInterval(()=>{if(workspaceView!=='demo'){stopDemoReplay();return;}const points=demoState.reports[demoState.scenario].series,end=points[points.length-1].t;demoState.time=demoState.time+.05;if(demoState.time>end)demoState.time=0;drawDemoChart();},50);
}
function drawDemoChart(){
  const s=demoState,canvas=$('demo-chart'),ctx=canvas.getContext('2d'),rect=canvas.getBoundingClientRect?.();
  if(rect?.width>0&&rect.height>0)canvas.height=Math.max(220,Math.round(rect.height*canvas.width/rect.width));
  const w=canvas.width,h=canvas.height,report=s.reports[s.scenario];
  ctx.clearRect(0,0,w,h);ctx.fillStyle='#12222d';ctx.fillRect(0,0,w,h);ctx.font='17px Segoe UI';
  const points=report?.series||[],after=s.after?s.reports.damped.series:[],times=points.map(p=>p.t),first=times[0]||0,end=times[times.length-1]||12;
  const limit=Math.max(1,...points.map(p=>Math.abs(p.angle)),...after.map(p=>Math.abs(p.angle)))*1.15;
  const x=t=>65+(t-first)/Math.max(end-first,1e-6)*(w-95),y=v=>h-44-(v+limit)/(2*limit)*(h-72);
  ctx.lineWidth=1;ctx.strokeStyle='#304856';ctx.fillStyle='#9fb9c9';
  for(let i=-2;i<=2;i++){const value=limit*i/2;ctx.beginPath();ctx.moveTo(60,y(value));ctx.lineTo(w-25,y(value));ctx.stroke();ctx.fillText(value.toFixed(1)+'°',2,y(value)+5);}
  for(let i=0;i<=4;i++){const t=first+(end-first)*i/4;ctx.fillText(t.toFixed(1)+'s',x(t)-16,h-12);}
  const line=(series,key,color,dashed=false)=>{ctx.strokeStyle=color;ctx.lineWidth=dashed?1.5:3;ctx.setLineDash(dashed?[7,7]:[]);ctx.beginPath();series.forEach((p,i)=>{if(i)ctx.lineTo(x(p.t),y(p[key]));else ctx.moveTo(x(p.t),y(p[key]));});ctx.stroke();ctx.setLineDash([]);};
  line([{t:first,target:0},{t:end,target:0}],'target','#819eae',true);line(points,'angle','#edb57b');if(after.length)line(after,'angle','#79d5bc');
  if(points.length){const active=after.length?after:points;let current=active[0];for(const p of active){if(p.t<=s.time)current=p;else break;}
    ctx.strokeStyle='#7898a8';ctx.lineWidth=1;ctx.setLineDash([4,6]);ctx.beginPath();ctx.moveTo(x(s.time),15);ctx.lineTo(x(s.time),h-40);ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.fillStyle=after.length?'#b4f5d5':'#f8d3a5';ctx.arc(x(current.t),y(current.angle),5,0,2*Math.PI);ctx.fill();
    $('demo-angle-value').textContent=(current.angle>=0?'+':'')+demoFormat(current.angle,1);$('demo-robot').style.transform='rotate('+Math.max(-30,Math.min(30,current.angle))+'deg)';$('demo-robot-state').textContent=after.length?'跟随对照数据':s.scenario==='noise'?'高频抖动示例':s.scenario==='windup'?'饱和示例':'持续晃动示例';
  }else{ctx.fillStyle='#a7bdca';ctx.fillText('点击「开始一分钟演示」载入数据',w*.25,h*.4);}
  $('demo-clock').textContent=demoFormat(s.time)+' s';$('demo-cursor').value=String(1000*(s.time-first)/Math.max(end-first,1e-6));
}
$('demo-start').onclick=prepareShowcase;
$('demo-present').onclick=()=>{const enabled=!document.body.classList.contains('demo-presentation');document.body.classList.toggle('demo-presentation',enabled);$('demo-present').textContent=enabled?'退出投屏':'投屏模式';$('demo-present').setAttribute('aria-pressed',String(enabled));drawDemoChart();};
window.addEventListener('resize',()=>{if(workspaceView==='demo')drawDemoChart();});
for(const key of Object.keys(demoScenes))$('demo-scenario-'+key).onclick=()=>{stopDemoReplay();demoState.scenario=key;demoState.stage=0;demoState.after=false;demoState.time=0;renderShowcase();$('demo-status').textContent=demoState.loaded?'场景已切换，点击下一步查看本机诊断。':'场景已选好，点击「开始一分钟演示」。';};
for(let i=0;i<4;i++)$('demo-step-'+i).onclick=()=>setDemoStage(i);
$('demo-next').onclick=()=>setDemoStage((demoState.stage+1)%4);
$('demo-play').onclick=()=>demoState.playing?stopDemoReplay():playDemoReplay();
$('demo-cursor').oninput=()=>{stopDemoReplay();if(!demoState.loaded)return;const points=demoState.reports[demoState.scenario].series;demoState.time=points[0].t+(points[points.length-1].t-points[0].t)*Number($('demo-cursor').value)/1000;drawDemoChart();};
$('demo-details').onclick=async()=>{try{stopDemoReplay();await refreshRecords();$('record-list').value=demoState.records[demoState.scenario].id;selectRecord();const report=demoState.reports[demoState.scenario],config=report.config||demoConfig(demoState.records[demoState.scenario]);
  for(const [key,value] of Object.entries(config.mapping))$('tuning-'+key).value=value;
  for(const key of ['kp','ki','kd'])$('tuning-'+key).value=config.pid[key];
  for(const [key,value] of Object.entries({loop:'',unit:config.unit,tolerance:config.tolerance,dt:config.sample_dt,lower:config.lower,upper:config.upper}))$('tuning-'+key).value=value;
  $('tuning-confirmed').checked=true;$('tuning-feedback').checked=true;workspaceNavigated=true;showWorkspace('records');renderTuningReport(report);$('tuning-metrics').scrollIntoView({behavior:'smooth',block:'start'});
}catch(error){$('demo-status').textContent=error.message;}};
