let ssReport=null,ssWidgets=new Map(),ssSelected=new Set(),ssRequest=0;
async function loadScreen(force=false){
  loadManualScreen();if(!force&&ssReport?.project_hash===state.scan?.project_hash&&ssReport?.root===state.scan?.root)return;
  const token=++ssRequest,hash=state.scan?.project_hash,root=state.scan?.root;$('ss-status').textContent='正在读取当前工程的屏幕输出调用…';$('ss-load').disabled=true;$('ss-display').textContent='';$('ss-display').hidden=false;$('ss-canvas').hidden=true;$('ss-driver').textContent='';$('ss-calls').textContent='';$('ss-variables').textContent='';$('ss-buttons').textContent='';
  try{const result=await api('source-screen');if(token!==ssRequest||hash!==state.scan?.project_hash||root!==state.scan?.root)return;ssReport=result;$('ss-group').textContent='';for(const group of result.groups){const option=element('option',group.path+' / '+group.name);option.value=group.id;$('ss-group').append(option);}
    if(!result.groups.length){$('ss-display').textContent='当前工程未检测到支持的屏幕绘图调用';$('ss-status').textContent='没有生成默认菜单。串口打印不算屏幕；其他驱动需增加解析适配。'+(result.unsupported.length?' 检测到 '+result.unsupported.length+' 项其他显示相关符号，当前未还原。':'');for(const item of result.unsupported){const row=element('div',undefined,'ss-call');row.append(element('code',item.api+'（尚未适配）'));const source=element('button',item.path+':'+item.line,'source-link');source.onclick=()=>showSource({...item,role:'未适配显示代码',sha256:state.scan.files[item.path]});const ask=element('button','问此源码模块','outline');ask.onclick=()=>openQuestion('file:'+item.path);row.append(source,ask);$('ss-calls').append(row);}return;}
    renderSourceGroup();
  }catch(e){$('ss-status').textContent=e.message;ssReport=null;}finally{if(token===ssRequest)$('ss-load').disabled=false;}
}
function selectedSourceGroup(){return ssReport?.groups.find(g=>g.id===$('ss-group').value);}
function ssValues(){const values={};for(const [name,input] of ssWidgets){if(input.value.trim()!==''&&Number.isFinite(Number(input.value)))values[name]=Number(input.value);}return values;}
async function copySourceValue(value){try{await navigator.clipboard.writeText(value);$('ss-status').textContent='已复制：'+value;}catch(_){$('ss-status').textContent='无法自动复制，请手动复制：'+value;}}
function renderSourceGroup(){
  const group=selectedSourceGroup();ssWidgets.clear();ssSelected.clear();$('ss-variables').textContent='';$('ss-calls').textContent='';$('ss-buttons').textContent='';if(!group)return;
  $('ss-driver').textContent=group.profile?group.profile.title+' · '+group.profile.transport:'此驱动坐标尚未核对，先列出源码调用';
  for(const name of group.variables){const row=element('div',undefined,'ss-variable'),label=element('code',name),input=element('input');input.type='number';input.step='any';input.placeholder='未知；填写预览值';input.setAttribute('aria-label',name+' 预览赋值');const seed=group.defaults?.[name];if(seed){input.value=String(seed.value);input.title=(seed.origin==='zero'?'C 全局变量默认零初始化；不是运行值：':'源码初值，仅作预览：')+seed.path+':'+seed.line;}input.oninput=previewSourceScreen;const copy=element('button','复制变量名','outline');copy.onclick=()=>copySourceValue(name);row.append(label,input,copy);if(seed)row.append(element('small',(seed.origin==='zero'?'C 默认零初值 ':'源码初值 ')+seed.value+' · '+seed.path+':'+seed.line,'hint'));$('ss-variables').append(row);ssWidgets.set(name,input);}
  if(!group.variables.length)$('ss-variables').append(element('p','此调用组没有提取到动态数值表达式。','hint'));
  for(const call of group.calls){ssSelected.add(call.id);const row=element('div',undefined,'ss-call'),check=element('input');check.type='checkbox';check.checked=true;check.setAttribute('aria-label','组合预览 '+call.api+' '+call.line);check.onchange=()=>{if(check.checked)ssSelected.add(call.id);else ssSelected.delete(call.id);previewSourceScreen();};const code=element('pre',(call.producer?call.producer.source+';\n':'')+call.source),source=element('button',call.path+':'+call.line,'source-link');source.onclick=()=>showSource({...call,role:'屏幕输出源码'});const copy=element('button','复制位置','outline');copy.onclick=()=>copySourceValue(call.path+':'+call.line);const ask=element('button','问这段代码','outline');ask.onclick=()=>openQuestion('screen-group:'+group.id);row.append(check,code,source,copy,ask);if(call.guards.length)row.append(element('p','条件：'+call.guards.map(g=>g.name+' '+(g.op||'==')+' '+g.value).join(' && '),'hint'));if(call.blocked_condition)row.append(element('p','此条件尚未仿真，画面会跳过这一项。','hint'));$('ss-calls').append(row);}
  const pageValues=new Map();for(const call of group.calls)for(const g of call.guards)if((g.op||'==')==='=='){if(!pageValues.has(g.name))pageValues.set(g.name,new Set());pageValues.get(g.name).add(g.value);}
  for(const [name,values] of pageValues)if(values.size>1)for(const value of [...values].sort((a,b)=>a-b)){const b=element('button','预览 '+name+' = '+value,'outline');b.onclick=()=>{if(ssWidgets.has(name))ssWidgets.get(name).value=String(value);previewSourceScreen();};$('ss-buttons').append(b);}
  for(const b of group.buttons){const toggle=b.operation==='toggle',button=element('button',toggle?'源码按键 '+b.input+' → 切换 '+b.variable:b.input+' == '+b.equals+' → '+b.variable+' = '+b.value,'outline');button.title=b.path?b.path+':'+b.line:'';button.onclick=()=>{if(toggle){const input=ssWidgets.get(b.variable);if(!input||input.value.trim()===''){$('ss-status').textContent='请先填写 '+b.variable+' 的预览值，再模拟这个切换。';return;}input.value=Number(input.value)?'0':'1';}else{if(ssWidgets.has(b.input))ssWidgets.get(b.input).value=b.equals;if(ssWidgets.has(b.variable))ssWidgets.get(b.variable).value=b.value;}previewSourceScreen();};$('ss-buttons').append(button);}
  if(group.buttons.length)$('ss-buttons').append(element('p','以上是代码条件中的简单赋值，点击只把该赋值应用到预览；未模拟完整按键状态机。','hint'));
  previewSourceScreen();
}
let ssRenderToken=0;
async function previewSourceScreen(){
  const group=selectedSourceGroup();if(!group)return;const token=++ssRenderToken,hash=state.scan?.project_hash,root=state.scan?.root;
  try{const result=await api('source-screen-render',{project_hash:hash,group:group.id,values:ssValues(),calls:[...ssSelected]});if(token!==ssRenderToken||hash!==state.scan?.project_hash||root!==state.scan?.root)return;$('ss-display').textContent=result.rows.length?result.rows.join('\n'):'无法确认驱动坐标约定，请查看下方实际调用';drawSourceCanvas(result);$('ss-status').textContent=[...result.warnings,'静态源码预览：可修改预览值，不是实时读数；未执行完整固件，字体近似。'].join(' ');}catch(e){if(token===ssRenderToken)$('ss-status').textContent=e.message;}
}
function drawSourceCanvas(result){
  const canvas=$('ss-canvas'),p=result.profile;canvas.hidden=!p;$('ss-display').hidden=!!p;if(!p)return;
  canvas.width=p.width;canvas.height=p.height;const ctx=canvas.getContext('2d');ctx.fillStyle=result.background||'#000000';ctx.fillRect(0,0,p.width,p.height);ctx.textBaseline='top';
  for(const draw of result.draws||[]){if(draw.kind==='clear'){ctx.fillStyle=draw.background;ctx.fillRect(0,0,p.width,p.height);}else if(draw.kind==='fill'){ctx.fillStyle=draw.background;ctx.fillRect(draw.x,draw.y,draw.width,draw.height);}else if(draw.kind==='text'){
    ctx.font=draw.font_height+'px Consolas, monospace';for(let i=0;i<draw.text.length;i++){const x=draw.x+i*draw.font_width;ctx.fillStyle=draw.background;ctx.fillRect(x,draw.y,draw.font_width,draw.font_height);ctx.fillStyle=draw.foreground;ctx.fillText(draw.text[i],x,draw.y,draw.font_width);}
  }}
  canvas.setAttribute('aria-label',p.title+'；'+(result.rows||[]).join('\n'));
}
$('ss-load').onclick=()=>loadScreen(true);$('ss-group').onchange=renderSourceGroup;

$('ss-copyall').onclick=()=>{const group=selectedSourceGroup();if(group)copySourceValue(group.variables.join('\n'));};
