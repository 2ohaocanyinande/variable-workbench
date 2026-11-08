const screenState={size:'128x64',theme:'green',brightness:90,page:'menu',selected:0,on:true,text:'Hello STM32!\n变量工作台 · 模拟屏幕',binding:'demo'};
let screenProject='',screenEpoch=Date.now(),questionBusy=false,allQuestionTargets=[];
const screenPages=['data','text','settings'];
function screenStorageKey(){return 'screen-preview:'+state.scan?.root+':'+state.scan?.project_hash;}
function screenSettings(){return {size:screenState.size,theme:screenState.theme,brightness:screenState.brightness,page:screenState.page,selected:screenState.selected};}
function loadManualScreen(){
  const key=screenStorageKey();if(key!==screenProject){screenProject=key;Object.assign(screenState,{size:'128x64',theme:'green',brightness:90,page:'menu',selected:0,on:true,text:'Hello STM32!\n变量工作台 · 模拟屏幕',binding:'demo'});
    try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved){if(['128x64','240x240','320x240'].includes(saved.size))screenState.size=saved.size;if(['green','white','amber'].includes(saved.theme))screenState.theme=saved.theme;if(Number.isFinite(saved.brightness))screenState.brightness=Math.max(20,Math.min(100,saved.brightness));if(typeof saved.text==='string')screenState.text=saved.text.slice(0,160);}}catch(_){}
  }
  for(const key of ['size','theme','brightness','page','text'])$('screen-'+key).value=screenState[key];
  $('screen-binding').textContent='';const option=element('option','内置模拟信号');option.value='demo';$('screen-binding').append(option);
  if(typeof tplPanel!=='undefined'&&tplPanel?.root===state.scan?.root&&tplPanel?.project_hash===state.scan?.project_hash)for(const item of tplPanel.items)for(const f of item.fields){const option=element('option',item.name+' / '+f.label+'（模拟）');option.value=f.id;$('screen-binding').append(option);}
  if([...$('screen-binding').options].some(o=>o.value===screenState.binding))$('screen-binding').value=screenState.binding;else screenState.binding='demo';renderScreen();
}
function renderScreen(){
  const s=screenState,screen=$('sim-screen');screen.className='sim-screen '+(s.size==='128x64'?'oled':s.size==='240x240'?'square':'landscape')+' '+s.theme;screen.style.opacity=String(s.brightness/100);$('screen-body').textContent='';$('screen-power').textContent=s.on?'熄屏':'亮屏';$('screen-page').value=s.page;
  $('screen-bar').textContent=s.on?'VARIABLE LAB  /  模拟':'';$('screen-bottom').textContent=s.on?'↑ ↓ 选择   OK 确认   ← 返回':'';
  if(!s.on){$('screen-status').textContent='预览已熄屏；点击亮屏恢复。';return;}
  if(s.page==='menu'){for(const [i,name] of ['运行数据','自定义文字','显示设置'].entries())$('screen-body').append(element('div',(i===s.selected?'› ':'  ')+name,i===s.selected?'screen-selected':''));}
  else if(s.page==='data'){
    const t=(Date.now()-screenEpoch)/1000;let content='俯仰角  '+(8*Math.sin(t)).toFixed(1)+'°\n编码器  '+Math.floor(t*120)+' count\n来源：内置模拟信号';
    if(s.binding!=='demo'&&typeof tplPanel!=='undefined'&&tplPanel?.root===state.scan?.root&&tplPanel?.project_hash===state.scan?.project_hash){const field=tplPanel.items.flatMap(i=>i.fields).find(f=>f.id===s.binding),widget=tplWidgets.get(s.binding);content=field?field.label+'\n'+(widget?.value.textContent??tplPanel.values[field.id]??field.initial)+' '+(field.unit||'')+'\n来源：面板模拟值':'绑定已变化，请重新选择';}
    $('screen-body').append(element('div',content,'screen-lines'));
  }else if(s.page==='text')$('screen-body').append(element('div',s.text,'screen-lines'));
  else $('screen-body').append(element('div','尺寸  '+s.size+'\n亮度  '+s.brightness+'%\n上下键调亮度','screen-lines'));
  $('screen-status').textContent=s.page==='settings'?'上下键调整预览亮度，返回回到菜单。':'本机屏幕预览 · 按键不会发送到设备。';
}
function screenKey(key){if(!screenState.on)return;if(key==='back')screenState.page='menu';else if(key==='ok'){if(screenState.page==='menu')screenState.page=screenPages[screenState.selected];}else if(screenState.page==='menu')screenState.selected=(screenState.selected+(key==='up'?2:1))%3;else if(screenState.page==='settings'){screenState.brightness=Math.max(20,Math.min(100,screenState.brightness+(key==='up'?5:-5)));$('screen-brightness').value=screenState.brightness;}renderScreen();}
for(const key of ['up','down','ok','back'])$('screen-'+key).onclick=()=>screenKey(key);
for(const key of ['size','theme','brightness','page','text','binding'])$('screen-'+key).oninput=()=>{screenState[key]=key==='brightness'?Number($('screen-'+key).value):$('screen-'+key).value;renderScreen();};
$('screen-power').onclick=()=>{screenState.on=!screenState.on;renderScreen();};
$('screen-save').onclick=()=>{try{localStorage.setItem(screenStorageKey(),JSON.stringify({...screenSettings(),text:screenState.text}));$('screen-status').textContent='尺寸、配色、亮度和文字已保存在这台电脑。';}catch(e){$('screen-status').textContent='保存失败：'+e.message;}};
setInterval(()=>{if(workspaceView==='screen'&&screenState.on&&screenState.page==='data')renderScreen();},250);
async function openQuestion(target='project'){
  if(questionBusy)return;$('question-dialog').showModal();$('question-status').textContent='正在整理可提问对象…';$('question-answer').textContent='';$('question-context').textContent='';
  const hash=state.scan?.project_hash;
  try{const result=await api('question-targets');if(state.scan?.project_hash!==hash)throw Error('工程已切换，请重试');allQuestionTargets=result.targets;$('question-filter').value='';filterQuestionTargets(target);$('question-status').textContent='选择对象后填写问题，可先预览发送内容。';}catch(e){$('question-status').textContent=e.message;}
}
async function sendQuestion(preview=false){
  if(questionBusy)return;questionBusy=true;$('question-send').disabled=true;$('question-preview').disabled=true;$('question-target').disabled=true;$('question-text').disabled=true;const project=state.scan?.project_hash,root=state.scan?.root,started=Date.now();$('question-status').className='hint busy';$('question-status').textContent='正在处理…';
  const timer=setInterval(()=>{$('question-status').textContent=(preview?'正在整理上下文':'正在等待回答')+' · '+Math.floor((Date.now()-started)/1000)+' 秒';},1000);
  try{const data={project_hash:project,target:$('question-target').value,question:$('question-text').value,screen:screenSettings()},result=await api(preview?'question-preview':'question-ask',data);if(state.scan?.project_hash!==project||state.scan?.root!==root)throw Error('工程已切换，请重新提问');
    $('question-context').textContent=JSON.stringify(preview?result:result.context,null,2);if(!preview)$('question-answer').textContent=result.answer;$('question-status').textContent=preview?'这是将发送的上下文，尚未调用模型。':result.source==='model'?'模型回答 · '+result.model+' · 请结合源码核对。':'本地说明 · 未调用模型';
  }catch(e){$('question-status').textContent=e.message;}finally{clearInterval(timer);questionBusy=false;$('question-send').disabled=false;$('question-preview').disabled=false;$('question-target').disabled=false;$('question-text').disabled=false;$('question-status').className='hint';}
}
$('question-target').onchange=()=>{if(!questionBusy){$('question-answer').textContent='';$('question-context').textContent='';}};
$('question-open').onclick=()=>openQuestion(workspaceView==='screen'?'screen':'module:'+workspaceView);$('screen-ask').onclick=()=>openQuestion('screen');$('question-close').onclick=()=>{if(!questionBusy)$('question-dialog').close();};$('question-send').onclick=()=>sendQuestion();$('question-preview').onclick=()=>sendQuestion(true);

function filterQuestionTargets(selected='project'){const query=$('question-filter').value.toLowerCase();$('question-target').textContent='';const matches=allQuestionTargets.filter(t=>t.name.toLowerCase().includes(query)||t.id===selected).slice(0,200);const pinned=allQuestionTargets.find(t=>t.id===selected);if(pinned&&!matches.some(t=>t.id===selected))matches.unshift(pinned);for(const t of matches){const option=element('option',t.name);option.value=t.id;$('question-target').append(option);}if(matches.some(t=>t.id===selected))$('question-target').value=selected;}
$('question-filter').oninput=()=>filterQuestionTargets('');

$('module-question').onclick=()=>openQuestion('module:'+workspaceView);
