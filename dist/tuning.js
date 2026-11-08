// Local diagnostics and replay: no model calls, no device writes.
let tuningReport=null,tuningTimer=null,tuningSelected='',tuningTime=0,tuningPlaying=false,tuningStale=false;
function tuningOptions(id,choices,current=''){
  const el=$(id);el.textContent='';for(const [value,label] of choices){const option=element('option',label);option.value=value;el.append(option);}if(choices.some(c=>c[0]===current))el.value=current;
}
function tuningRecordLabel(meta){return (meta.source==='simulation'?'[模拟] ':'[实采] ')+(meta.info?.scenario||new Date(meta.created*1000).toLocaleString())+' · '+meta.id.slice(0,6);}
function refreshTuning(){
  const meta=selectedRecord(),channels=meta?.channels||[],changed=tuningSelected!==meta?.id;
  const records=localRecords.filter(r=>r.state!=='recording').map(r=>[r.id,tuningRecordLabel(r)]);
  tuningOptions('tuning-before',records,$('tuning-before').value);tuningOptions('tuning-after',records,$('tuning-after').value);
  tuningOptions('tuning-loop',[['','只诊断数据，不关联源码'],...(state.scan?.pid?.loops||[]).map(l=>[l.id,l.symbol])],$('tuning-loop').value);
  if(changed){
    tuningSelected=meta?.id||'';tuningReport=null;stopTuningReplay();$('tuning-replay').hidden=true;$('tuning-metrics').textContent='';$('tuning-findings').textContent='';$('tuning-snapshot').textContent='完成诊断后显示。';$('tuning-comparison-result').textContent='';
    const defaults={angle:'angle_deg',target:'target_deg',gyro:'gyro_dps',output:'control_out',integral:'i_out',derivative:'d_out'};
    for(const key of Object.keys(defaults))tuningOptions('tuning-'+key,[['','请选择'],...channels.map(c=>[c,c])],defaults[key]);
    const snapshot=meta?.info?.snapshot;
    for(const key of ['kp','ki','kd'])$('tuning-'+key).value=snapshot?.pid?.[key]??'';
    for(const [id,key] of [['dt','sample_dt'],['lower','lower'],['upper','upper']])$('tuning-'+id).value=snapshot?.[key]??'';
    $('tuning-unit').value=snapshot?.unit||'deg';$('tuning-tolerance').value=snapshot?.unit==='rad'?.005:.3;
    $('tuning-confirmed').checked=false;$('tuning-feedback').checked=false;
    $('tuning-status').textContent=meta?.source==='simulation'?'[模拟数据] 已带入模拟参数标签。需要数值试调方案时，请展开第 2 步核对并确认条件。':'实采记录请绑定信号，并填写对应的运行参数。未确认条件时仅分析现象。';
  }
  $('tuning-diagnose').disabled=!meta||meta.state==='recording';$('tuning-demo').disabled=recordActive;
  $('tuning-draft').disabled=tuningStale||!tuningReport?.proposal||!tuningReport?.source_snapshot?.loop_id;
}
const selectRecordWithoutTuning=selectRecord;
selectRecord=function(){selectRecordWithoutTuning();refreshTuning();};
$('record-list').onchange=selectRecord;
function tuningNumber(id){const value=$(id).value.trim();return value===''?null:Number(value);}
function tuningConfig(){
  const mapping={};for(const key of ['angle','target','gyro','output','integral','derivative'])mapping[key]=$('tuning-'+key).value;
  return {mapping,loop_id:$('tuning-loop').value,unit:$('tuning-unit').value,tolerance:tuningNumber('tuning-tolerance'),pid:{kp:tuningNumber('tuning-kp'),ki:tuningNumber('tuning-ki'),kd:tuningNumber('tuning-kd')},sample_dt:tuningNumber('tuning-dt'),lower:tuningNumber('tuning-lower'),upper:tuningNumber('tuning-upper'),parameters_confirmed:$('tuning-confirmed').checked,feedback_verified:$('tuning-feedback').checked};
}
function tuningAction(id,fn){$(id).onclick=async()=>{const button=$(id);button.disabled=true;$('tuning-status').textContent='正在本机处理…';try{await fn();}catch(error){$('tuning-status').textContent=error.message;notice(error.message,true);}finally{button.disabled=false;$('tuning-draft').disabled=tuningStale||!tuningReport?.proposal||!tuningReport?.source_snapshot?.loop_id;}};}
tuningAction('tuning-demo',async()=>{
  const result=await api('tuning-demo',{});await refreshRecords();const before=result.records.find(r=>r.info.tuning_scenario==='oscillating'),after=result.records.find(r=>r.info.tuning_scenario==='damped');
  $('record-list').value=before.id;selectRecord();$('tuning-before').value=before.id;$('tuning-after').value=after.id;
  $('tuning-status').textContent='已保存 4 组模拟记录，各 600 样本：持续震荡、改善曲线、微分噪声、饱和积分。当前选中持续震荡，可直接诊断。';
});
function renderTuningReport(report){
  tuningReport=report;tuningStale=false;const m=report.metrics;stopTuningReplay();
  $('tuning-metrics').textContent='';for(const [label,value] of [['后段 RMS 误差',m.tail_rms_error],['震荡频率 Hz',m.frequency_hz],['输出饱和占比',m.saturation_fraction==null?'未绑定':(100*m.saturation_fraction).toFixed(1)+'%'],['回稳时间 s',m.settling_seconds??'窗口内未回稳']]){const card=element('div',undefined,'record-metric');card.append(element('span',label),element('strong',typeof value==='string'?value:numberText(value)));$('tuning-metrics').append(card);}
  $('tuning-findings').textContent='';for(const f of report.findings){const card=element('article',undefined,'tuning-finding');card.append(element('h3',f.title));card.append(element('p','数据依据：'+f.evidence.join('；')));card.append(element('p','可能原因：'+f.possible_causes.join('；'),'hint'));card.append(element('p','先检查：'+f.checks.join('；')));card.append(element('p',f.direction,'tuning-direction'));$('tuning-findings').append(card);}
  if(report.proposal){const p=report.proposal;const box=element('article',undefined,'tuning-proposal');box.append(element('h3',p.parameter.toUpperCase()+' 试调：'+numberText(p.before)+' → '+numberText(p.after)),element('p',p.reason),element('strong',(report.source==='simulation'?'[模拟] ':'')+p.status));$('tuning-findings').append(box);}
  for(const warning of report.warnings)$('tuning-findings').append(element('p',warning,'hint'));
  $('tuning-findings').append(element('p',report.notice,'hint'));
  $('tuning-snapshot').textContent=JSON.stringify({记录来源:report.source,记录时快照:report.record_snapshot,本次诊断与源码快照:report.source_snapshot,样本SHA256:report.data_sha256,报告:report.report_path},null,2);
  $('tuning-replay').hidden=false;tuningTime=report.series[0].t;$('tuning-cursor').value=0;drawTuningReplay();
  $('tuning-status').textContent=(report.source==='simulation'?'[模拟数据] ':'[实采记录] ')+'诊断完成，报告已保存：'+report.report_path;
}
tuningAction('tuning-diagnose',async()=>{renderTuningReport(await api('tuning-diagnose',{id:$('record-list').value,config:tuningConfig()}));});
tuningAction('tuning-draft',async()=>{const result=await api('tuning-draft',{record_id:tuningReport.record_id,diagnosis_id:tuningReport.id});state.scan.pid.draft=result.draft;renderPid();$('tuning-status').textContent=result.notice;});
tuningAction('tuning-compare',async()=>{
  const result=await api('tuning-compare',{before:$('tuning-before').value,after:$('tuning-after').value,config:tuningConfig()});const box=$('tuning-comparison-result');box.textContent='';const table=element('table');
  for(const cells of [['指标','之前','之后'],['后段 RMS 误差',numberText(result.before.tail_rms_error),numberText(result.after.tail_rms_error)],['后段平均偏差',numberText(result.before.tail_bias),numberText(result.after.tail_bias)],['回稳时间 s',result.before.settling_seconds==null?'未回稳':numberText(result.before.settling_seconds),result.after.settling_seconds==null?'未回稳':numberText(result.after.settling_seconds)],['饱和占比',result.before.saturation_fraction==null?'未知':(result.before.saturation_fraction*100).toFixed(1)+'%',result.after.saturation_fraction==null?'未知':(result.after.saturation_fraction*100).toFixed(1)+'%']]){const row=element('tr');for(const value of cells)row.append(element('td',value));table.append(row);}box.append(table);
  if(result.rms_reduction_percent!=null)box.append(element('p','这两段数据的后段 RMS 降低 '+result.rms_reduction_percent.toFixed(2)+'%（仅为统计比较）','tuning-direction'));
  for(const message of result.warnings)box.append(element('p',message,'hint'));
  const details=element('details');details.append(element('summary','对比记录时的参数快照'),element('pre',JSON.stringify(result.snapshots,null,2)));box.append(details,element('p',result.notice,'hint'));$('tuning-status').textContent='对照报告已保存：'+result.report_path;
});
function stopTuningReplay(){if(tuningTimer!==null)clearInterval(tuningTimer);tuningTimer=null;tuningPlaying=false;$('tuning-play').textContent='播放';}
function drawTuningReplay(){
  if(!tuningReport)return;const points=tuningReport.series,first=points[0].t,last=points[points.length-1].t;
  let current=points[0];for(const p of points){if(p.t<=tuningTime)current=p;else break;}
  $('tuning-time').textContent=numberText(tuningTime)+' s · 角度 '+numberText(current.angle)+' · 角速度 '+numberText(current.gyro)+' · 输出 '+numberText(current.output);
  for(const [id,keys] of [['angle',['angle','target']],['gyro',['gyro']],['output',['output']]]){
    const canvas=$('tuning-'+id+'-plot'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,values=points.flatMap(p=>keys.map(k=>p[k]).filter(Number.isFinite));
    ctx.clearRect(0,0,w,h);ctx.fillStyle='#12212b';ctx.fillRect(0,0,w,h);ctx.font='13px Segoe UI';ctx.fillStyle='#c5d2de';
    if(!values.length){ctx.fillText('未绑定此通道',20,40);continue;}
    const low=Math.min(...values),high=Math.max(...values),span=Math.max(high-low,1e-6),x=t=>65+(t-first)/Math.max(last-first,1e-6)*(w-90),y=v=>h-28-(v-low+.08*span)/(1.16*span)*(h-45);
    ctx.lineWidth=1;ctx.strokeStyle='#344958';for(let i=0;i<=3;i++){const v=low+(high-low)*i/3;ctx.beginPath();ctx.moveTo(60,y(v));ctx.lineTo(w-20,y(v));ctx.stroke();ctx.fillText(numberText(v),4,y(v)+4);}
    for(let i=0;i<=4;i++){const t=first+(last-first)*i/4;ctx.fillText(t.toFixed(1)+'s',x(t)-15,h-7);}
    for(const [index,key] of keys.entries()){ctx.strokeStyle=index?'#c4d0df':'#75d4b7';ctx.lineWidth=2;ctx.setLineDash(index?[6,5]:[]);ctx.beginPath();let active=false;for(const p of points){if(!Number.isFinite(p[key])){active=false;continue;}if(active)ctx.lineTo(x(p.t),y(p[key]));else ctx.moveTo(x(p.t),y(p[key]));active=true;}ctx.stroke();}ctx.setLineDash([]);ctx.strokeStyle='#f5bd7b';ctx.beginPath();ctx.moveTo(x(tuningTime),10);ctx.lineTo(x(tuningTime),h-25);ctx.stroke();
  }
}
$('tuning-cursor').oninput=()=>{stopTuningReplay();if(!tuningReport)return;const p=tuningReport.series;tuningTime=p[0].t+(p[p.length-1].t-p[0].t)*Number($('tuning-cursor').value)/1000;drawTuningReplay();};
$('tuning-play').onclick=()=>{
  if(tuningPlaying){stopTuningReplay();return;}if(!tuningReport)return;const p=tuningReport.series,end=p[p.length-1].t,start=p[0].t;if(tuningTime>=end)tuningTime=start;tuningPlaying=true;$('tuning-play').textContent='暂停';
  tuningTimer=setInterval(()=>{if(workspaceView!=='records'){stopTuningReplay();return;}tuningTime=Math.min(end,tuningTime+.05);$('tuning-cursor').value=1000*(tuningTime-start)/(end-start);drawTuningReplay();if(tuningTime>=end)stopTuningReplay();},50);
};
for(const id of ['loop','unit','tolerance','angle','target','gyro','output','integral','derivative','kp','ki','kd','dt','lower','upper','confirmed','feedback'])$('tuning-'+id).addEventListener('change',()=>{if(tuningReport){tuningStale=true;$('tuning-draft').disabled=true;$('tuning-status').textContent='设置已变化。下方保留的是上次诊断，请重新诊断后加入方案。';}});
// Freeze declared run settings at recording start; never label them device readback.
const startRecordButton=$('record-start');
startRecordButton.onclick=async()=>{startRecordButton.disabled=true;try{const result=await api('record-start',{config:tuningConfig()});await refreshRecords();$('record-list').value=result.id;selectRecord();$('record-status').textContent='开始记录；运行参数声明和源码线索已随记录保存（非设备参数回读）。';}catch(e){notice(e.message,true);}finally{syncRecordButtons();}};
