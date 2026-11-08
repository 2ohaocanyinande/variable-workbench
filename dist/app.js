const $ = id => document.getElementById(id);
let state = {}, selected = new Set(), polling = false;
let serialCursor=0, serialSession=null, serialEvents=[], serialModeTouched=false;
const cards = new Map(), labels = new Map(), chosenDevices = new Set(), deviceNames = new Map();
function friendlyLabel(f){const name=labels.get(f.id)||f.label;return name==='目标占空比'?'输出强度（%）':name==='使能'?'电机开关':name;}
function instanceKey(f){return f.id.split("::")[0]+"::"+(f.variable||f.module);}
function renderInstances(){
  const groups=new Map();for(const f of state.scan.fields){const k=instanceKey(f);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(f);}
  $('instances').textContent='';let motorIndex=0,sensorIndex=0,pendingIndex=0,chosen=0;
  for(const [key,fields] of groups){
    const supported=fields.filter(f=>f.selectable), count=supported.filter(f=>selected.has(f.id)).length;
    if(!supported.length)continue;
    const motor=fields.some(f=>f.kind.startsWith('motor_')), sensor=fields.some(f=>f.kind==='temperature');
    const title=motor?'电机 '+(++motorIndex):sensor?'温度传感器 '+(++sensorIndex):'待确认项目 '+(++pendingIndex);
    if(count)chosen++;
    const row=element('tr'),cell=element('td'),check=element('input');check.type='checkbox';check.disabled=!supported.length;check.checked=!!supported.length&&count===supported.length;check.indeterminate=count>0&&count<supported.length;check.setAttribute('aria-label','选择'+title);
    check.onchange=()=>{for(const f of supported){if(check.checked)selected.add(f.id);else selected.delete(f.id);}renderFields();};cell.append(check);row.append(cell);
    const name=element('td');name.append(element('span',title,'field-name'));
    const detail=element('details');detail.append(element('summary','查看对应代码'),element('span',key,'sub'));name.append(detail);
    const purpose=element('td',supported.length?(motor?'调节输出、开启或关闭':sensor?'查看芯片温度':'查看数据'):'暂不能使用');
    const options=element('td');
    for(const f of supported){const label=element('label',undefined,'feature-choice'),input=element('input');input.type='checkbox';input.checked=selected.has(f.id);input.onchange=()=>{if(input.checked)selected.add(f.id);else selected.delete(f.id);renderFields();};label.append(input,element('span',friendlyLabel(f)));options.append(label);}
    if(!supported.length)options.append(element('span','尚未找到可靠的读写方式，需要进一步适配。','sub'));
    row.append(name,purpose,options);$('instances').append(row);
  }
  $('selection-help').textContent=chosen?'已选择 '+chosen+' 个设备，共 '+selected.size+' 项功能。下一步：生成面板。':'请勾选至少一个设备或一项功能。';
  $('generate').disabled=selected.size===0||state.scan.platform!=='esp32';
}
async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function notice(text, error=false) { $('notice').textContent = text; $('notice').className = error ? 'error' : ''; }
function element(tag, text, className) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(className)n.className=className;return n; }
function renderFields() {
  const scan=state.scan;if(!scan)return;$('choose').hidden=scan.platform==='stm32';$('panel').hidden=scan.platform==='stm32';$('template-section').hidden=scan.platform!=='stm32';
  $('project-path').value=scan.root;
  $('file-count').textContent=scan.file_count+' 个源文件 / 配置';
  $('build-source').textContent=scan.build_source;
  $('scope').textContent=scan.scope;const info=scan.project_info||{};$('platform-info').textContent=(scan.platform==='stm32'?'已识别 STM32 工程':scan.platform==='esp32'?'已识别 ESP32 工程':'CMake 工程')+' · '+(info.formats||[]).join(' / ')+(info.devices?.length?' · '+info.devices.join(' / '):'')+(scan.platform==='stm32'?'。支持代码用途分析和普通串口收发；STM32 实时控制面板仍需接入固件协议。':'');
  const platformDetail=$('platform-info').textContent;$('platform-info').title=platformDetail;const chip=(info.devices||[]).find(d=>/^STM32[A-Z0-9]+$/.test(d)&&d.length>10)||(info.devices||[])[0];$('platform-info').textContent=[scan.platform==='stm32'?'STM32':scan.platform==='esp32'?'ESP32':'CMake',(info.formats||[]).join(' / '),chip].filter(Boolean).join('　·　');
  $('total').textContent=scan.fields.length;
  $('supported').textContent=scan.fields.filter(f=>f.selectable).length;
  $('pending').textContent=scan.fields.filter(f=>!f.selectable).length;
  renderInstances();renderUsage();renderDevices();renderPid();updateWorkspace();
  const filter=$('filter').value.toLowerCase();$('fields').textContent='';
  for(const f of scan.fields) {
    if(![f.id,f.label,f.module,f.data_source].join(' ').toLowerCase().includes(filter))continue;
    const row=element('tr');const check=element('input');check.type='checkbox';check.disabled=!f.selectable;check.checked=selected.has(f.id);
    check.onchange=()=>{if(check.checked)selected.add(f.id);else selected.delete(f.id);renderInstances();};
    const c=element('td');c.append(check);row.append(c);
    const name=element('td');const label=element('input');label.value=labels.get(f.id)||f.label;label.setAttribute('aria-label',f.id+' 显示名称');label.disabled=!f.selectable;label.maxLength=60;label.oninput=()=>{labels.set(f.id,label.value);renderInstances();};name.append(label,element('span',f.module+' · '+f.symbol,'sub'));row.append(name);
    const type=element('td');type.append(element('span',f.type+' / '+f.access,'tag'),element('span',f.unit?f.unit+(f.min!==null&&f.max!==null?' · '+f.min+'–'+f.max:''):'单位未确认 / 无单位','sub'));row.append(type);
    const source=element('td');source.append(element('span',f.data_source),element('span',f.status,'sub'));row.append(source);
    const askVar=element('button','问此变量','outline ask-item');askVar.onclick=()=>openQuestion('native-field:'+f.id);name.append(askVar);const proof=element('td');for(const e of f.evidence){const b=element('button',e.path+':'+e.line,'source-link');b.onclick=()=>showSource(e);proof.append(b,element('br'));}row.append(proof);$('fields').append(row);
  }
}
async function showSource(e) {
  try {
    const result=await api('source?path='+encodeURIComponent(e.path)+'&line='+e.line);
    $('source-title').textContent=e.role+' · '+result.path;
    $('source-status').textContent=result.changed?'源码已变化，此绑定需要复核':'文件哈希与扫描记录一致 · '+e.sha256.slice(0,16);
    $('source-code').textContent='';
    for(const line of result.lines)$('source-code').append(element('span',String(line.number).padStart(4)+'  '+line.text,'source-row'+(line.number===result.line?' target':'')));
    $('source-modal').showModal();
  }catch(e){notice(e.message,true);}
}
function renderPanel() {
  $('controls').textContent='';cards.clear();
  const m=state.manifest;
  if(state.scan?.platform==='stm32'){$('controls').append(element('div','STM32 工程当前可分析变量用途；实时读写需要后续适配串口协议。','empty'));return;}if(!m){$('controls').append(element('div','先完成第 2 步：选择设备并生成面板。','empty'));return;}
  $('schema').textContent='SCHEMA '+m.schema_id.slice(0,14);
  for(const f of m.fields){
    const card=element('div',undefined,'control');const groupIds=[...new Set(m.fields.filter(x=>x.kind.startsWith('motor_')).map(instanceKey))];const deviceName=f.kind.startsWith('motor_')?'电机 '+(groupIds.indexOf(instanceKey(f))+1):f.kind==='temperature'?'芯片温度':'设备数据';card.append(element('span',deviceName,'tag'),element('h3',friendlyLabel(f)));
    const ask=element('button','问这项','outline ask-item');ask.onclick=()=>openQuestion('native-field:'+f.id);card.append(ask);
    const number=element('div','—','number stale');card.append(number);
    const origin=element('span',f.data_source,'sub');card.append(origin);
    const time=element('span','等待实时数据','sub');card.append(time);
    let input,ack;
    if(f.access==='rw'){
      const edit=element('div',undefined,'edit');input=element(f.type==='bool'?'select':'input');
      if(f.type==='bool'){for(const [v,t] of [['false','关闭'],['true','开启']]){const o=element('option',t);o.value=v;input.append(o);}}
      else{input.type='number';input.min=f.min;input.max=f.max;input.step='0.1';input.value=f.min;}
      input.addEventListener('input',()=>{input.dataset.edited='1';});
      const button=element('button','应用修改');button.disabled=!state.bridge_connected;input.disabled=!state.bridge_connected;
      ack=element('div','','ack');button.onclick=async()=>{button.disabled=true;try{const value=f.type==='bool'?input.value==='true':Number(input.value);ack.textContent='发送中…';const r=await api('write',{field:f.id,value});delete input.dataset.edited;input.value=String(r.readback);ack.textContent='已生效，设备返回： '+r.readback;notice('写入与回读一致：'+f.label);}catch(e){ack.textContent=e.message;notice(e.message,true);}finally{button.disabled=!state.bridge_connected;}};
      edit.append(input,button);card.append(edit,ack);
    }
    const canvas=element('canvas');canvas.width=700;canvas.height=180;card.append(canvas);
    $('controls').append(card);cards.set(f.id,{f,number,time,canvas,input,updated:0});
  }
}
function graph(canvas,points){
  const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);
  ctx.strokeStyle='#33465a';ctx.lineWidth=1;for(let y=25;y<h;y+=45){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  if(points.length<2)return;const low=Math.min(...points),high=Math.max(...points),span=Math.max(high-low,1);
  ctx.beginPath();points.forEach((v,i)=>{const x=i*w/(points.length-1),y=h-15-(v-low)*(h-30)/span;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle='#43c6ad';ctx.lineWidth=3;ctx.stroke();
}
function renderData(data){
  for(const [id,c] of cards){const value=data.sample.values[id];
    if(value&&typeof value==='object'){c.number.textContent='读取失败';c.number.className='number stale';c.time.textContent=value.error;continue;}
    if(typeof value!=='number'&&typeof value!=='boolean')continue;
    c.number.textContent=typeof value==='boolean'?(value?'开启':'关闭'):value.toFixed(2);c.number.className='number';if(c.f.unit)c.number.append(element('small',c.f.unit));
    c.updated=Date.now();c.time.textContent='刚刚收到开发板的数据';
    if(c.input&&!c.input.dataset.edited&&document.activeElement!==c.input)c.input.value=String(value);
    const values=data.history.map(p=>p.values[id]).filter(v=>typeof v==='number'||typeof v==='boolean').map(Number);graph(c.canvas,values);
  }
  $('logs').textContent=data.log.map(x=>new Date(x.time*1000).toLocaleTimeString()+'  '+x.text).join('\n');
}
async function refresh(render=false){state=await api('state');$('connection').textContent=state.connected?(state.bridge_connected?'面板协议已连接':'串口已打开 · 普通收发'):'尚未连接开发板';$('connection').className='pill'+(state.connected?' online':'');$('api-dot').textContent=state.api_enabled?'已启用':'离线';
  const old=$('ports').value;$('ports').textContent='';for(const p of state.ports){const o=element('option',p.name+' · '+p.description);o.value=p.name;$('ports').append(o);}if([...$('ports').options].some(o=>o.value===old))$('ports').value=old;
  if(render){renderFields();renderPanel();}if(state.scan?.platform==='stm32')$('generate').disabled=true;renderSerialConnection();
}
function action(id,fn){$(id).onclick=async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){notice(e.message,true);}finally{b.disabled=false;if(['connect','disconnect','refresh-ports','serial-send'].includes(id))renderSerialConnection();if(id.startsWith('record-'))syncRecordButtons();}};}
action('scan',async()=>{notice('扫描源码与构建记录…');state.scan=await api('scan',{path:$('project-path').value});await refresh();selected.clear();labels.clear();chosenDevices.clear();deviceNames.clear();if(state.scan.platform==='stm32')$('usage-scope').value='stm32';renderFields();renderPanel();notice(state.scan.platform==='stm32'?'STM32 工程已打开。下一步：查看外设线索，或配置 AI 助手并点击「分析变量用途」。':'已找到工程里的设备。下一步：在第 2 步勾选你需要的设备和功能。');});
$('filter').oninput=renderFields;
$('select-all').onclick=()=>{selected=new Set(state.scan.fields.filter(f=>f.selectable).map(f=>f.id));renderFields();};
action('generate',async()=>{state.manifest=await api('generate',{ids:[...selected],labels:Object.fromEntries(labels)});renderPanel();$('next-step').textContent='面板已生成。请先编译、烧录配套固件，再连接开发板。具体操作见下方说明。';notice('面板已生成。开发板还需更新配套固件，更新后才能使用新面板。');$('panel').scrollIntoView({behavior:'smooth'});});
action('refresh-ports',()=>refresh());
action('connect',async()=>{const mode=$('serial-mode').value;notice(mode==='raw'?'正在打开串口…':'正在核对面板协议…');await api('connect',{port:$('ports').value,mode,baudrate:Number($('serial-baud').value)});serialCursor=0;serialSession=null;serialEvents=[];await refresh(true);notice(mode==='raw'?'串口已打开。可以接收数据，或发送固件支持的命令。':'面板协议已连接，可以查看数据和调整已适配参数。');});
action('disconnect',async()=>{await api('disconnect',{});await refresh(true);notice('串口已断开');});
$('source-close').onclick=()=>$('source-modal').close();$('api-close').onclick=()=>$('api-modal').close();
$('api-open').onclick=()=>{
  $('api-enabled').checked=!!state.api_enabled;
  $('api-remember').checked=!!state.api_remembered||!state.api_configured;
  if(state.api_settings?.url)$('api-url').value=state.api_settings.url;
  if(state.api_settings?.model)$('api-model').value=state.api_settings.model;
  $('api-key').placeholder=state.api_configured?'已配置，留空保留当前 Key':'请输入 Key';
  $('api-state').textContent=state.api_store_error||(state.api_remembered?'已使用 Windows 加密保存在本机，下次启动自动恢复。':state.api_configured?'当前仅在内存中使用，勾选记住设置并应用可保存。':'填写后点击应用设置。');
  $('api-modal').showModal();
};
action('api-save',async()=>{
  const r=await api('settings',{enabled:$('api-enabled').checked,remember:$('api-remember').checked,url:$('api-url').value,model:$('api-model').value,key:$('api-key').value});
  $('api-key').value='';await refresh();
  $('api-state').textContent=!r.enabled?'已关闭模型建议，内存和本机保存的 API 设置已清除。':r.remembered?'已加密保存在本机，下次启动自动恢复。可以关闭此窗口并进行分析。':'已应用，本次运行可用。未保存到磁盘，重启后需重新填写。';
});
action('api-forget',async()=>{
  await api('forget-settings',{});$('api-key').value='';$('api-key').placeholder='请输入 Key';$('api-enabled').checked=false;$('api-remember').checked=true;
  await refresh();$('api-state').textContent='已清除本机保存的设置和内存中的 Key，模型建议已关闭。';
});
action('suggest',async()=>{notice('请求模型筛选候选字段…');const r=await api('suggest',{query:$('query').value});selected=new Set(r.field_ids);renderFields();notice('模型建议已勾选，仍可手动调整。'+r.reason);});
async function poll(){if(state.connected&&!polling){polling=true;try{if(state.serial_mode==='raw')renderSerialData(await api('serial-data?after='+serialCursor));else renderData(await api('data'));}catch(e){notice(e.message,true);for(const c of cards.values()){c.number.classList.add('stale');c.time.textContent='数据已过期 · '+e.message;}await refresh().catch(()=>{});}finally{polling=false;}}setTimeout(poll,500);}
refresh(true).then(()=>{if(state.manifest){for(const f of state.manifest.fields)labels.set(f.id,f.label);selected=new Set(state.manifest.fields.map(f=>f.id));renderFields();}notice('工程已就绪。通过左侧导航查看控制环、设备清单或串口连接。');poll();}).catch(e=>notice(e.message,true));

// Keep the local service alive independently of Edge launcher process handoff.
function heartbeat(){fetch("/api/heartbeat",{cache:"no-store"}).catch(()=>{});}
heartbeat();setInterval(heartbeat,15000);
window.addEventListener("pagehide",()=>navigator.sendBeacon("/api/window-close","{}"));

function renderUsage(){
  const usage=state.scan?.usage;if(!usage)return;
  $('usage-summary').textContent='已在本机整理 '+usage.candidates.length+' 个变量及相关代码。配置好左下角的 AI 助手后，点击分析，就能看到用途说明和判断依据。复杂工程可能只找到其中一部分。';
  renderNetwork();
  const report=state.scan.usage_report;$('usage-results').textContent='';if(!report)return;
  const info=element('p','本次分析 '+report.coverage.sent+' / '+report.coverage.indexed+' 个已提取变量'+(report.coverage.partial?'（仅覆盖部分工程）':'')+'。'+report.notice,'hint');$('usage-results').append(info);
  if(!report.findings.length){$('usage-results').append(element('p','模型未返回可核验的用途判断，请换一个更具体的问题。','hint'));return;}
  const table=element('table'),head=element('tr');for(const t of ['变量 / 位置','推测用途','判断理由','对应代码','接入状态'])head.append(element('th',t));table.append(head);
  for(const f of report.findings){const row=element('tr'),name=element('td');name.append(element('span',f.candidate.symbol,'field-name'),element('span',f.candidate.path+':'+f.candidate.line+' · '+f.candidate.scope,'sub'));const askVar=element('button','问此变量','outline ask-item');askVar.onclick=()=>openQuestion('usage:'+f.candidate.id);name.append(askVar);const proof=element('td');for(const e of f.evidence){const b=element('button',e.path+':'+e.line,'source-link');b.onclick=()=>showSource(e);proof.append(b,element('span',e.quote,'sub'));}row.append(name,element('td',f.purpose),element('td',f.reason),proof,element('td','AI 推测 · 待确认读写入口'));table.append(row);}
  $('usage-results').append(table);
}
action('usage-preview',async()=>{const r=await api('analyze-usage',{preview:true,scope:$('usage-scope').value,query:$('usage-query').value});$('source-title').textContent='发送前预览（此操作不调用模型）';$('source-status').textContent='包含 '+r.packet.coverage.sent+' 个变量，输入约 '+r.bytes+' 字节。只有点击分析才发送。';$('source-code').textContent=JSON.stringify(r.packet,null,2);$('source-modal').showModal();});
async function runAnalysis(mode='variables'){
  const deviceMode=mode==='devices',prefix=deviceMode?'device':'usage';
  const button=$(deviceMode?'device-analyze':'usage-analyze'),status=$(prefix+'-status'),text=$(prefix+'-status-text'),spinner=$(prefix+'-spinner');
  if(button.disabled)return;
  if(!deviceMode){delete state.scan.usage_report;renderUsage();}
  button.disabled=true;button.textContent='正在分析…';button.setAttribute('aria-busy','true');
  status.hidden=false;status.className='';spinner.hidden=false;
  const started=Date.now();let phase='正在准备并请求模型';let checking=false;
  const update=()=>{text.textContent=phase+' · 已等待 '+Math.floor((Date.now()-started)/1000)+' 秒'+(Date.now()-started>20000?'，较大工程可能需要更久':'');};update();
  notice('分析已开始，进度和结果会显示在分析按钮下方。');
  const timer=setInterval(async()=>{update();if(checking)return;checking=true;try{const s=await api('analysis-status');const phases={preparing:'正在整理相关代码',waiting:'正在等待模型返回分析结果',verifying:'已收到结果，正在核对代码依据'};if(phases[s.phase])phase=phases[s.phase];}catch(e){}finally{checking=false;}},1000);
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),110000);
  try{
    const response=await fetch('/api/analyze-usage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,scope:$('usage-scope').value,query:$('usage-query').value||'分析变量的实际用途，解释配置、状态、控制与收发数据，名称仅作辅助'}),signal:controller.signal});
    let r;try{r=await response.json();}catch(e){throw new Error('本地服务未返回有效结果，请检查程序是否仍在运行。');}
    if(!response.ok)throw new Error(r.error||'分析失败，请重试。');
    if(deviceMode){state.scan.device_report=r;chosenDevices.clear();renderDevices();}else{state.scan.usage_report=r;renderUsage();}status.className='done';text.textContent='分析完成 · 耗时 '+Math.ceil((Date.now()-started)/1000)+' 秒 · 返回 '+(deviceMode?r.devices.length+' 个设备候选':r.findings.length+' 项用途说明')+'。';if(deviceMode&&r.warnings?.length){status.className=r.devices.length?'partial':'failed';text.textContent=(r.devices.length?'部分完成':'未获得可核验结果')+' · 保留 '+r.devices.length+' 项，跳过 '+r.warnings.length+' 项，原因见下方。';}notice(deviceMode?'设备分析结束，请查看清单及核验提示。':'用途分析完成，结果在分析区域下方。');
    $(deviceMode?'device-list':'usage-results').scrollIntoView({behavior:'smooth',block:'nearest'});
  }catch(e){status.className='failed';text.textContent=e.name==='AbortError'?'等待超过 110 秒，已停止本页等待。后台请求可能仍在结束中，请稍后重试。':e.message;notice('分析未完成，请看分析按钮下方的错误说明。',true);
  }finally{clearInterval(timer);clearTimeout(timeout);spinner.hidden=true;button.disabled=false;button.textContent=deviceMode?'AI 识别设备':'分析变量用途';button.removeAttribute('aria-busy');}
}
$('usage-analyze').onclick=()=>runAnalysis('variables');
$('device-analyze').onclick=()=>runAnalysis('devices');

function renderNetwork(){
  const box=$('network-summary');box.textContent='';
  const scope=$('usage-scope').value;if(scope!=='network'&&scope!=='stm32')return;
  const entries=(scope==='stm32'?state.scan?.usage?.stm32:state.scan?.usage?.network)||[];
  if(!entries.length){box.append(element('p',scope==='stm32'?'本次没有匹配到已支持的 STM32 外设调用。仍可选择「全部功能」让模型分析代码。':'本次没有找到已支持的联网或蓝牙调用。它表示当前代码中未匹配到，不代表开发板不支持联网。','hint'));return;}
  box.append(element('p','找到 '+entries.length+' 个包含'+(scope==='stm32'?'STM32 外设':'联网或蓝牙')+'调用的函数。下表是源码线索，不代表已验证硬件或运行状态。','hint'));
  const detail=element('details',undefined,'advanced');detail.append(element('summary','查看底层调用与代码入口（高级）'));const table=element('table'),head=element('tr');for(const t of ['涉及功能','代码入口','查看依据'])head.append(element('th',t));table.append(head);
  for(const e of entries){const row=element('tr'),proof=element('td');for(const sid of e.evidence_ids){const snippet=state.scan.usage.snippets[sid];const b=element('button',snippet.path+':'+snippet.line,'source-link');b.onclick=()=>showSource(snippet);proof.append(b,element('br'));}row.append(element('td',e.clues.join('、')),element('td',e.symbol+' · '+e.path),proof);table.append(row);}detail.append(table);box.append(detail);
}
$('usage-scope').onchange=()=>{renderNetwork();$('usage-query').placeholder=$('usage-scope').value==='network'?'例如：找出联网配置、连接状态与收发缓冲区':$('usage-scope').value==='stm32'?'例如：找出 PWM 输出、ADC 采样、串口收发涉及的变量':'例如：找出控制输出和传感器采样相关变量';};

let pickerState=null,pickerBusy=false;
async function browseProject(path){
  if(pickerBusy)return;pickerBusy=true;$('picker-use').disabled=true;$('picker-message').textContent='正在读取文件夹…';
  try{const r=await api('browse-project',{path});pickerState=r;$('picker-path').textContent=r.path;$('picker-up').disabled=!r.parent;$('picker-locations').textContent='';for(const location of r.locations){const b=element('button',location.name,'outline');b.onclick=()=>browseProject(location.path);$('picker-locations').append(b);}
    $('picker-folders').textContent='';if(r.is_project){const entry=element('div','📄 '+(r.markers||[]).join('、')+' · 工程入口已找到','project-entry');$('picker-folders').append(entry);}
    for(const folder of r.directories){const b=element('button','📁 '+folder.name,'folder-entry');b.onclick=()=>browseProject(folder.path);$('picker-folders').append(b);}
    if(!r.directories.length&&!r.is_project)$('picker-folders').append(element('p','此处没有子文件夹。','hint'));
    $('picker-use').disabled=!r.is_project;$('picker-message').textContent=r.is_project?'可以选择这个工程。':'这里没有受支持的工程入口，请进入包含 .ioc、.uvprojx、CubeIDE 或 CMakeLists.txt 的工程文件夹。';if(r.truncated)$('picker-message').textContent+=' 此目录较大，仅显示前 1000 个子文件夹。';
  }catch(e){$('picker-message').textContent=e.message;}finally{pickerBusy=false;}
}
$('pick-project').onclick=()=>{$('project-picker').showModal();browseProject($('project-path').value);};
$('picker-close').onclick=()=>$('project-picker').close();
$('picker-up').onclick=()=>{if(pickerState?.parent)browseProject(pickerState.parent);};
$('picker-use').onclick=()=>{if(pickerState?.is_project&&!pickerBusy){$('project-path').value=pickerState.path;$('project-picker').close();notice('工程文件夹已选好。下一步：点击「查找工程里的设备」。');}};

function deviceSelection(){
  if(typeof updateTemplateVisibility==='function')updateTemplateVisibility();
  $('device-selection').textContent=chosenDevices.size?'已选择 '+chosenDevices.size+' 项关注设备。此处可命名和查看功能，STM32 实时读写仍需适配通信协议。':'勾选你想关注的设备；这里只选择和命名，不会向硬件发送指令。';
}
function renderDevices(){
  const inventory=state.scan?.inventory,report=state.scan?.device_report;const box=$('device-list');box.textContent='';
  const endpoints=inventory?.endpoints||[],devices=report?.devices;
  $('device-count').textContent=devices?'已整理 '+devices.length+' 项候选：AI '+(report.ai_devices_count??devices.length)+' 项'+(report.local_clues_count?'，本地补充线索 '+report.local_clues_count+' 项':'')+'。代码引文已核对，设备类型与实例仍需确认。':endpoints.length?'本地找到 '+endpoints.length+' 项接口线索，尚未确定对应哪些物理设备。点击「AI 识别设备」继续。':'本次没有匹配到可分组的接口。仍可在下方分析变量用途；未匹配不代表没有设备。';
  const rows=devices?.length?devices:endpoints.map(e=>{const hint=e.module_hints?.length===1?e.module_hints[0]:null;return {id:e.id,name:hint?hint.category+'（'+hint.model+'）':e.family+' 接口（设备类型待识别）',kind:'unknown',category:hint?.category,model:hint?.model,module_model:hint?.module_model,components:hint?.components,driver_state:hint?.driver_state,classification_basis:hint?.confidence,instance:e.handle+(e.channel?' / '+e.channel:''),interfaces:[e],features:['需要结合驱动实现判断设备功能'],evidence:e.calls.slice(0,3).map(c=>({path:e.path,line:c.line,sha256:c.sha256,role:c.api})),status:hint?'本地常见模块线索 · 待确认':'本地接口线索'};});
  if(report?.coverage?.partial)$('device-count').textContent+=' 本次只覆盖部分接口或代码，清单可能不完整。';
  if(report?.restored_from_cache)$('device-count').textContent+=' 已恢复源码哈希一致的历史模型结果，结论仍需核对。';
  if(report?.warnings?.length){const warning=element('div',undefined,'validation-warning');warning.append(element('strong','部分 AI 结果未通过核验：已保留 '+(report.ai_devices_count??devices.length)+' 项，跳过 '+report.warnings.length+' 项。'));for(const item of report.warnings)warning.append(element('p','第 '+item.index+' 项（'+item.name+'）：'+item.reason));if(!devices.length)warning.append(element('p','没有得到可核验的设备结果，以下仍显示本地接口线索。请重试；程序不会采用虚构引用。'));box.append(warning);}
  const table=element('table'),head=element('tr');for(const t of ['选择','设备 / 显示名称','接口 / 实例','功能与判断依据'])head.append(element('th',t));table.append(head);
  for(const d of rows){const row=element('tr'),select=element('td'),check=element('input');check.type='checkbox';check.checked=chosenDevices.has(d.id);check.setAttribute('aria-label','关注 '+d.name+' '+d.instance);check.onchange=()=>{if(check.checked)chosenDevices.add(d.id);else chosenDevices.delete(d.id);deviceSelection();};select.append(check);
    const name=element('td'),alias=element('input');const ask=element('button','问这项','outline ask-item');ask.onclick=()=>openQuestion((devices?.length?'device:':'interface:')+d.id);name.append(ask);alias.value=deviceNames.get(d.id)||d.name;alias.setAttribute('aria-label',d.instance+' 的显示名称');alias.maxLength=80;alias.oninput=()=>deviceNames.set(d.id,alias.value);name.append(alias,element('span',d.status,'sub'));if(d.category)name.append(element('span','类别：'+d.category,'sub'));if(d.model)name.append(element('span','型号：'+d.model,'sub'));if(d.driver_state)name.append(element('span','驱动：'+d.driver_state,'sub'));if(d.classification_basis)name.append(element('span',d.classification_basis,'sub'));if(d.module_model)name.append(element('strong',d.module_model,'sub'));for(const component of d.components||[])name.append(element('span',component.name+'：'+component.state,'module-component'));
    if(d.features.some(f=>/[0-9°%]/.test(f)))name.append(element('span','功能中的数值／单位尚未逐项验证；引用存在不代表参数已正确归属此设备。','sub validation-warning'));
    const link=element('td');link.append(element('span',d.instance,'field-name'),element('span',d.interfaces.map(e=>e.family+' '+e.handle+(e.channel?' / '+e.channel:'')).join('、'),'sub'));
    const info=element('td');for(const feature of d.features)info.append(element('span',feature,'sub'));const details=element('details');details.append(element('summary','为什么这样判断？'));if(d.reason)details.append(element('p',d.reason,'hint'));if(d.instance_binding)details.append(element('p','实例溯源：'+d.instance_binding,'hint'));for(const repair of d.local_repairs||[])details.append(element('p',repair,'hint'));if(d.evidence.some(e=>e.reference_corrected))details.append(element('p','重叠片段的引用编号已按原代码重新定位。','hint'));for(const e of d.evidence){const button=element('button',e.path+':'+e.line,'source-link');button.onclick=()=>showSource(e);details.append(button,element('br'));}info.append(details);row.append(select,name,link,info);table.append(row);
  }box.append(table);deviceSelection();
}

function renderSerialConnection(){
  const connected=!!state.connected, bridgeAvailable=state.scan?.platform==='esp32'&&!!state.manifest;
  const mode=$('serial-mode');mode.querySelector('option[value="bridge"]').disabled=!bridgeAvailable;
  if(connected)mode.value=state.serial_mode||'raw';
  else if(!serialModeTouched)mode.value=bridgeAvailable?'bridge':'raw';
  if(!bridgeAvailable&&mode.value==='bridge')mode.value='raw';
  if(connected){$('ports').value=state.serial_port;$('serial-baud').value=state.serial_baudrate;}
  const bridge=mode.value==='bridge';if(bridge)$('serial-baud').value=115200;
  mode.disabled=connected;$('ports').disabled=connected;$('serial-baud').disabled=connected||bridge;
  $('connect').disabled=connected||!$('ports').value;$('disconnect').disabled=!connected;
  $('record-start').disabled=!connected||bridge||!!state.active_record;$('record-stop').disabled=!state.active_record;$('serial-send').disabled=!connected||bridge;$('raw-console').hidden=bridge;
  $('serial-help').textContent=!state.ports.length&&!connected?'电脑尚未识别到 COM 口。接好数据线或 USB 转串口后，点击「重新查找」。':bridge?'此方式会发送 hello 握手，并核对固件与当前面板是否匹配。':'请选择与固件一致的波特率。连接后先查看接收区；只有点「发送」才向开发板发送数据。';
}
function drawSerialEvents(){
  const hex=$('serial-view').value==='hex';
  const lines=serialEvents.map(e=>'['+new Date(e.time*1000).toLocaleTimeString()+'] '+e.direction+' '+e.bytes+' 字节  '+(hex?e.hex:e.text));
  $('serial-log').textContent=lines.join('\n').slice(-65536)||(state.connected?'已连接，等待开发板发来数据…':'连接后在这里显示开发板发来的数据。');
  $('serial-log').scrollTop=$('serial-log').scrollHeight;
}
function renderSerialData(data){
  if(serialSession!==data.session){serialSession=data.session;serialCursor=0;serialEvents=[];}
  if(data.history_truncated)$('serial-send-status').textContent='较早记录已滚动移除，接收计数保留。';
  for(const e of data.events){if(e.id>serialCursor){serialEvents.push(e);serialCursor=e.id;}}
  serialEvents=serialEvents.slice(-200);drawSerialEvents();
  $('serial-count').textContent='接收 '+data.rx_bytes+' 字节 · 发送 '+data.tx_bytes+' 字节';
}
$('serial-mode').onchange=()=>{serialModeTouched=true;renderSerialConnection();};
$('serial-view').onchange=drawSerialEvents;
$('serial-format').onchange=()=>{$('serial-ending').disabled=$('serial-format').value==='hex';};
action('serial-send',async()=>{const r=await api('serial-send',{content:$('serial-input').value,format:$('serial-format').value,ending:$('serial-ending').value});$('serial-send-status').textContent='已发送 '+r.sent_bytes+' 字节；设备是否接受需查看返回。';});
action('serial-clear',async()=>{await api('serial-clear',{});serialCursor=0;serialSession=null;serialEvents=[];drawSerialEvents();$('serial-count').textContent='接收 0 字节 · 发送 0 字节';});

const pidEditors=new Map();
function renderPid(){
  const index=state.scan?.pid,loops=index?.loops||[];if(!index?.suggestions&&!$('pid-status').className.includes('busy'))$('pid-status').textContent='';pidEditors.clear();$('pid-list').textContent='';$('pid-edges').textContent='';
  $('pid-summary').textContent=loops.length?'找到 '+loops.length+' 个有增益计算依据的控制器候选。展开后可配置参数。':(index?.limits||'打开工程后查找 PID 控制器。')+' 本次未匹配不代表工程没有 PID。';
  $('pid-save').disabled=!loops.length;$('pid-analyze').disabled=!loops.length;
  const suggestions=new Map((index?.suggestions||[]).map(s=>[s.id,s]));
  const drafts=new Map((index?.draft?.loops||[]).map(s=>[s.id,s]));
  const names=new Map(loops.map(l=>[l.id,suggestions.get(l.id)?.name||l.symbol]));
  for(const e of index?.edges||[]){const row=element('p',names.get(e.from)+' → '+names.get(e.to)+' · '+e.kind+' · 信号 '+e.signal+' 进入 '+e.argument,'pid-edge');for(const proof of e.evidence){const b=element('button',proof.path+':'+proof.line,'source-link');b.onclick=()=>showSource(proof);row.append(element('br'),b);} $('pid-edges').append(row);}
  for(const loop of loops){
    const suggestion=suggestions.get(loop.id),draft=drafts.get(loop.id),card=element('details',undefined,'pid-card');
    const heading=element('summary');heading.append(element('span',draft?.name||suggestion?.name||loop.symbol,'pid-card-name'),element('span',(draft?.category||suggestion?.category||'待确认')+(suggestion&&!draft?' · 建议':''),'pid-type'),element('span',loop.symbol,'pid-code-name'));const askLoop=element('button','问此控制环','outline ask-item');askLoop.onclick=()=>openQuestion('pid:'+loop.id);card.append(heading,askLoop);
    const name=element('input');name.value=draft?.name||suggestion?.name||loop.symbol;name.maxLength=80;name.setAttribute('aria-label',loop.symbol+' 环名称');
    const category=element('select');for(const t of ['待确认','速度环','位置环','角度环','角速度环','转向环','电流环','其他控制环']){const o=element('option',t);o.value=t;category.append(o);}category.value=draft?.category||suggestion?.category||'待确认';
    const bar=element('div',undefined,'connect-bar');bar.append(name,category);card.append(bar,element('p','代码实例：'+loop.symbol+' · '+loop.type+' · '+(loop.calls.length?'已找到 '+loop.calls.length+' 处调用':'未找到直接调用，不能确定是否实际使用')+' · 在线写入未接入','hint'));
    if(loop.calls.some(c=>c.conditional_span))card.append(element('p','调用位于条件编译代码，当前编译分支尚未确认。','hint'));
    const aiExplanation=suggestion?element('p','AI 建议（待确认）：'+suggestion.reason,'hint'):null;
    const gains={},gainGroup=element('div',undefined,'pid-gains');
    for(const [key,gain] of Object.entries(loop.gains)){
      const row=element('div',undefined,'pid-gain'),label=element('label',key.toUpperCase()),input=element('input');input.type='number';input.step='any';input.value=draft?.gains?.[key]?.value??gain.value??'';input.placeholder='数值尚未确定';input.setAttribute('aria-label',loop.symbol+' '+key);label.append(input);
      const source=element('select'),none=element('option','仅保存方案（未绑定赋值）');none.value='';source.append(none);
      gain.sources.forEach((s,i)=>{const o=element('option',s.path+':'+s.line+' = '+s.literal);o.value=String(i);source.append(o);});
      source.value=draft?.gains?.[key]?(draft.gains[key].source_index!=null?String(draft.gains[key].source_index):''):gain.sources.length===1?'0':'';
      source.setAttribute('aria-label',loop.symbol+' '+key+' 赋值来源');source.onchange=()=>{if(source.value!=='')input.value=gain.sources[Number(source.value)].value;};row.append(label,source);gainGroup.append(row);gains[key]={input,source};
    }
    card.append(gainGroup);const proof=element('details',undefined,'pid-proof');proof.append(element('summary','计算与源码依据'));if(aiExplanation)proof.append(aiExplanation);
    for(const e of [...loop.evidence,...loop.kernels,...loop.calls,...Object.values(loop.gains).flatMap(g=>g.sources)]){const b=element('button',e.path+':'+e.line+' · '+(e.role||e.function),'source-link');b.onclick=()=>showSource(e);proof.append(b,element('br'));}
    for(const call of loop.calls)proof.append(element('pre',call.function+'('+call.arguments.join(', ')+')'));
    card.append(proof);$('pid-list').append(card);pidEditors.set(loop.id,{name,category,gains});
  }
}
action('pid-save',async()=>{
  const loops=[];for(const [id,editor] of pidEditors){const gains={};for(const [key,ui] of Object.entries(editor.gains)){if(ui.input.value.trim()!==''){const value=Number(ui.input.value);if(!Number.isFinite(value))throw new Error('PID 参数必须是有限数值');gains[key]={value,source_index:ui.source.value===''?null:Number(ui.source.value)};}}loops.push({id,name:editor.name.value,category:editor.category.value,gains});}
  const r=await api('pid-config',{project_hash:state.scan.project_hash,loops});state.scan.pid.draft=r.draft;$('pid-status').textContent=r.notice;
  $('source-title').textContent='PID 调参方案 · 源码补丁预览';$('source-status').textContent=r.patch_path+' · 未绑定参数 '+r.draft.unbound.length+' 个 · 原工程和开发板均未修改';$('source-code').textContent=r.patch||JSON.stringify(r.draft,null,2);$('source-modal').showModal();
});
action('pid-analyze',async()=>{
  const start=Date.now();$('pid-status').className='hint busy';$('pid-status').textContent='正在请求模型解释环类型…';const timer=setInterval(()=>{$('pid-status').textContent='正在等待模型 · '+Math.floor((Date.now()-start)/1000)+' 秒';},1000);
  try{const r=await api('analyze-usage',{mode:'pid'});await refresh(true);$('pid-status').textContent='采用 '+r.suggestions.length+' 条环类型建议。'+r.notice+(r.warnings?.length?' 核验提示：'+r.warnings.join('；'):'');}catch(error){$('pid-status').textContent=error.message;throw error;}finally{clearInterval(timer);$('pid-status').className='hint';}
});

let workspaceView='pid',workspaceNavigated=false;
const workspaceViews={screen:{title:'源码屏幕预览',description:'预览屏幕内容与按键交互，边看边问。',sections:['screen-section']},demo:{title:'演示台',description:'一分钟，从看见异常到带着依据做决定。',sections:['demo-section']},pid:{title:'控制环与调参',description:'梳理控制关系，让每一次调参都有依据。',sections:['pid-section']},devices:{title:'设备清单',description:'从接口线索到设备实例，查看每一项判断的依据。',sections:['devices']},serial:{title:'串口连接',description:'连接开发板，接收日志，发送设备支持的指令。',sections:['serial']},records:{title:'记录与分析',description:'本地留存角度与编码器数据，回看趋势和异常候选。',sections:['records-section']},analysis:{title:'代码用途分析',description:'从计算、调用和赋值关系理解变量的作用。',sections:['understand']},panel:{title:'控制面板',description:'选择已适配字段，生成面板并连接固件。',sections:['choose','panel','template-section','log']}};
function showWorkspace(view){
  if(!workspaceViews[view])return;
  workspaceView=view;document.body?.classList.toggle('template-panel-view',view==='panel'&&state.scan?.platform==='stm32');document.body?.classList.toggle('demo-mode',view==='demo');document.body?.classList.toggle('data-view',view==='records'||view==='serial'||view==='demo'||view==='screen');if(view!=='demo'){document.body?.classList.toggle('demo-presentation',false);$('demo-present').textContent='投屏模式';$('demo-present').setAttribute('aria-pressed','false');}
  for(const [key,config] of Object.entries(workspaceViews)){
    $('nav-'+key).classList.toggle('active',key===view);$('nav-'+key).setAttribute('aria-current',key===view?'page':'false');
    for(const id of config.sections){$(id).classList.add('workspace-section');$(id).classList.toggle('view-active',key===view);}
  }
  $('workspace-title').textContent=workspaceViews[view].title;$('workspace-description').textContent=view==='panel'&&state.scan?.platform==='stm32'?'选择设备与控制环，用模板生成本机模拟面板。':workspaceViews[view].description;if(view==='screen'&&typeof loadScreen==='function')loadScreen();if(view==='demo'&&typeof renderShowcase==='function')renderShowcase();if(view==='panel'&&state.scan?.platform==='stm32'&&typeof refreshTemplatePanel==='function')refreshTemplatePanel();if(view==='records')refreshRecords().catch(e=>{$('record-status').textContent=e.message;});
}
function updateWorkspace(){
  $('nav-pid-count').textContent=String(state.scan?.pid?.loops?.length||0);
  $('nav-device-count').textContent=String(state.scan?.device_report?.devices?.length??state.scan?.inventory?.endpoints?.length??0);
  $('nav-panel').hidden=false;if(!workspaceNavigated)workspaceView='demo';showWorkspace(workspaceView);
}
for(const key of Object.keys(workspaceViews))$('nav-'+key).onclick=event=>{event.preventDefault();workspaceNavigated=true;showWorkspace(key);};

let localRecords=[],recordSelection='',recordFields='',recordActive=false,recordRefreshing=false;
const numberText=value=>typeof value==='number'&&Number.isFinite(value)?Number(value.toFixed(4)).toLocaleString():'—';
function selectedRecord(){return localRecords.find(r=>r.id===$('record-list').value);}
function configureRecordChannel(){
  const meta=selectedRecord(),channel=$('record-channel').value,simulation=meta?.source==='simulation';
  $('record-kind').value=simulation&&channel==='encoder_count'?'encoder':simulation&&channel.endsWith('_deg')?'angle':'generic';
  $('record-period').value=simulation&&channel==='encoder_count'?meta.info.encoder_period:simulation&&channel.endsWith('_deg')?360:0;
  $('record-cpr').value=simulation&&channel==='encoder_count'?meta.info.counts_per_turn:0;
  $('record-jump').value=simulation?(channel==='encoder_count'?(meta.info.encoder_jump_limit||100):channel==='angle_deg'?(meta.info.angle_jump_limit||10):0):0;
  $('record-reference').value=simulation&&channel==='angle_deg'?'target_deg':'';
  $('record-stats').textContent='';$('record-findings').textContent='';$('record-plot-wrap').hidden=true;
}
function selectRecord(){
  const meta=selectedRecord(),fields=meta?.channels||[],signature=JSON.stringify(fields),changed=recordSelection!==meta?.id;
  if(changed||recordFields!==signature){
    const old=$('record-channel').value;$('record-channel').textContent='';$('record-reference').textContent='';
    const none=element('option','不比较');none.value='';$('record-reference').append(none);
    for(const name of fields){const option=element('option',name);option.value=name;$('record-channel').append(option);const ref=element('option',name);ref.value=name;$('record-reference').append(ref);}
    if(!changed&&fields.includes(old))$('record-channel').value=old;
    recordSelection=meta?.id||'';recordFields=signature;configureRecordChannel();
  }
  $('record-analyze').disabled=!meta||!fields.length;$('record-export').disabled=!meta;
  $('record-source').textContent=meta?(meta.source==='simulation'?'模拟数据 · 非真实采集':'串口实采记录'):'';
  $('record-source').className='source-badge '+(meta?.source==='simulation'?'simulation':'real');
}
async function refreshRecords(){
  if(recordRefreshing)return;recordRefreshing=true;
  try{const result=await api('records'),old=$('record-list').value;localRecords=result.records||[];$('record-list').textContent='';
    for(const r of localRecords){const option=element('option',(r.source==='simulation'?'[模拟] ':'[串口] ')+new Date(r.created*1000).toLocaleString()+(r.info?.scenario?' · '+r.info.scenario:'')+' · '+r.samples+' 样本'+(r.state==='recording'?' · 记录中':r.state==='interrupted'?' · 未正常结束':''));option.value=r.id;$('record-list').append(option);}
    if(localRecords.some(r=>r.id===old))$('record-list').value=old;
    recordActive=!!result.active;state.active_record=result.active;
    $('record-active').textContent=result.active?'● 正在本机记录 · '+result.active.samples+' 样本':'未在记录';
    $('record-folder').textContent='本机存储目录：'+result.folder;
    $('record-start').disabled=!state.connected||state.serial_mode!=='raw'||recordActive;$('record-stop').disabled=!recordActive;$('record-demo').disabled=recordActive;
    selectRecord();
  }finally{recordRefreshing=false;}
}
function drawRecordPlot(report){
  const canvas=$('record-plot'),ctx=canvas.getContext('2d'),width=canvas.width,height=canvas.height,points=report.series;
  ctx.clearRect(0,0,width,height);ctx.fillStyle='#13202b';ctx.fillRect(0,0,width,height);
  const xs=points.map(p=>p.t),ys=points.flatMap(p=>p.reference==null?[p.value]:[p.value,p.reference]);
  const x0=Math.min(...xs),x1=Math.max(...xs),low=Math.min(...ys),high=Math.max(...ys),span=Math.max(high-low,1e-6),pad=span*.12;
  const x=t=>64+(t-x0)/Math.max(x1-x0,1e-6)*(width-88),y=v=>height-40-(v-low+pad)/(span+2*pad)*(height-65);
  ctx.font='13px Segoe UI';ctx.strokeStyle='#304151';ctx.fillStyle='#a4b4c4';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const value=low-pad+(span+2*pad)*i/4,yy=y(value);ctx.beginPath();ctx.moveTo(60,yy);ctx.lineTo(width-20,yy);ctx.stroke();ctx.fillText(numberText(value),5,yy+4);}
  for(let i=0;i<=4;i++){const t=x0+(x1-x0)*i/4;ctx.fillText(numberText(t)+'s',x(t)-15,height-13);}
  const line=(key,color,dashed)=>{ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dashed?[6,6]:[]);ctx.beginPath();let open=false;for(const p of points){if(p[key]==null){open=false;continue;}if(open)ctx.lineTo(x(p.t),y(p[key]));else{ctx.moveTo(x(p.t),y(p[key]));open=true;}}ctx.stroke();ctx.setLineDash([]);};
  line('reference','#a9b7ca',true);line('value','#46d0b0',false);ctx.fillStyle='#ffbb70';for(const p of points)if(p.spike){ctx.beginPath();ctx.arc(x(p.t),y(p.value),4,0,Math.PI*2);ctx.fill();}
}
function renderRecordReport(r){
  $('record-stats').textContent='';const metrics=[['有效样本',r.count],['数据时轴（秒）',r.duration],['平均值',r.mean],['标准差（含运动）',r.stddev],['最小 / 最大',numberText(r.min)+' / '+numberText(r.max)],['净变化',r.net_change],['平均变化率 / 秒',r.rate_mean],['回绕校正次数',r.wrap_count]];
  for(const [label,value] of metrics){const card=element('div',undefined,'record-metric');card.append(element('span',label),element('strong',typeof value==='string'?value:numberText(value)));$('record-stats').append(card);}
  $('record-findings').textContent='';const findings=[['突变候选',r.spike_count+' 处（单步阈值 '+numberText(r.spike_threshold)+'）'],['采样间隔异常候选',r.gap_count+' 处；常见间隔 '+numberText(r.median_interval)+' 秒'],['非递增时间戳',r.invalid_time_count+' 处'],['原始值范围',numberText(r.raw_min)+' / '+numberText(r.raw_max)],['未解析或未完整的数据行',(r.meta.invalid_lines||0)+' 行']];
  if(r.mae!=null)findings.push(['与参考值的平均绝对偏差',numberText(r.mae)]);
  if(r.rotation_degrees!=null)findings.push(['按配置每圈计数换算的累计角度',numberText(r.rotation_degrees)+'°']);
  for(const [label,value] of findings)$('record-findings').append(element('p',label+'：'+value));
  $('record-findings').append(element('p',r.notice,'hint'));$('record-plot-wrap').hidden=false;drawRecordPlot(r);
  $('record-status').textContent=(r.meta.source==='simulation'?'[模拟数据] ':'[串口记录] ')+'本地分析完成，报告随本条记录保存在本机。';$('record-status').title=r.report_path;
}
$('record-list').onchange=selectRecord;$('record-channel').onchange=configureRecordChannel;
$('record-kind').onchange=()=>{const kind=$('record-kind').value,meta=selectedRecord();$('record-jump').value=0;$('record-period').value=kind==='angle'?360:kind==='angle_rad'?2*Math.PI:kind==='encoder'&&meta?.source==='simulation'?meta.info.encoder_period:0;$('record-cpr').value=kind==='encoder'&&meta?.source==='simulation'?meta.info.counts_per_turn:0;};
action('record-refresh',refreshRecords);
action('record-demo',async()=>{$('record-status').textContent='正在生成明确标注的模拟记录…';const result=await api('record-demo',{});await refreshRecords();$('record-list').value=result.id;selectRecord();$('record-status').textContent='已生成 400 个模拟样本，含角度阶跃、编码器回绕、刻意突变和时间间隔异常。请选择通道并分析。';});
action('record-start',async()=>{const result=await api('record-start',{});await refreshRecords();$('record-list').value=result.id;selectRecord();$('record-status').textContent='正在本机留存原始收发与逐行数值。停止后记录仍保留；不向开发板发送指令。';});
action('record-stop',async()=>{await api('record-stop',{});await refreshRecords();$('record-status').textContent='记录已停止并保存在本机。可以分析或导出。';});
action('record-analyze',async()=>{$('record-status').textContent='正在本机分析…';const type=$('record-kind').value;const r=await api('record-analyze',{id:$('record-list').value,channel:$('record-channel').value,kind:type==='angle_rad'?'angle':type,period:Number($('record-period').value),cpr:Number($('record-cpr').value),reference:$('record-reference').value,jump_limit:Number($('record-jump').value),unit:type==='angle'?'deg':type==='angle_rad'?'rad':type==='encoder'?'count':'unknown'});renderRecordReport(r);});
action('record-export',async()=>{const id=$('record-list').value,r=await api('record-export',{id});$('record-status').textContent='CSV 已保存在本机：'+r.path;const link=element('a');link.href='/api/record-download?id='+encodeURIComponent(id);link.download='samples.csv';link.click();});
$('serial-to-records').onclick=()=>{workspaceNavigated=true;showWorkspace('records');};
setInterval(()=>{if(workspaceView==='records'&&recordActive)refreshRecords().catch(e=>{$('record-status').textContent=e.message;});},2000);

function syncRecordButtons(){
  $('record-start').disabled=!state.connected||state.serial_mode!=='raw'||recordActive;
  $('record-stop').disabled=!recordActive;$('record-demo').disabled=recordActive;
  $('record-analyze').disabled=!selectedRecord()||!$('record-channel').value;
  $('record-export').disabled=!selectedRecord();
}
