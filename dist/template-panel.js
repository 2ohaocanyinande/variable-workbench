let tplProject='',tplRoot='',tplSignature='',tplCandidates=[],tplTemplates=[],tplPanel=null,tplLoading=false,tplPaused=false,tplTime=0,tplStarted=Date.now(),tplPolling=false,tplFetchToken=0;
const tplChoices=new Map(),tplWidgets=new Map();
function updateTemplateVisibility(){const stm=state.scan?.platform==='stm32';$('template-section').hidden=!stm;$('device-to-panel').hidden=!stm;$('device-to-panel').disabled=!stm||!chosenDevices.size;}
function tplSelectionCount(){const count=[...tplChoices.values()].filter(c=>c.checked).length;$('tpl-count').textContent='已选择 '+count+' 项（最多 64 项）';$('tpl-generate').disabled=count<1||count>64||tplLoading;}
function tplMatches(candidate){const q=$('tpl-filter').value.trim().toLowerCase();return !q||[candidate.name,candidate.instance,candidate.origin].join(' ').toLowerCase().includes(q);}
function renderTemplateCandidates(){
  $('tpl-candidates').textContent='';for(const candidate of tplCandidates){if(!tplMatches(candidate))continue;const choice=tplChoices.get(candidate.id),row=element('tr'),cell=element('td'),check=element('input');check.type='checkbox';check.checked=choice.checked;check.setAttribute('aria-label','选择 '+candidate.name);check.onchange=()=>{choice.checked=check.checked;tplSelectionCount();};cell.append(check);row.append(cell);
    const name=element('td'),input=element('input');input.value=choice.name;input.maxLength=100;input.setAttribute('aria-label',candidate.name+' 显示名称');input.oninput=()=>{choice.name=input.value;};name.append(input,element('span',candidate.origin+' · '+candidate.instance,'sub'));row.append(name);
    const type=element('td'),select=element('select');for(const template of tplTemplates){const option=element('option',template.label);option.value=template.id;select.append(option);}select.value=choice.template;select.setAttribute('aria-label',candidate.name+' 面板模板');select.onchange=()=>{choice.template=select.value;};type.append(select);row.append(type);
    const proof=element('td');for(const e of candidate.evidence.slice(0,2)){const button=element('button',e.path+':'+e.line,'source-link');button.onclick=()=>showSource({...e,role:e.role||'面板候选来源',sha256:e.sha256||state.scan.files?.[e.path]||''});proof.append(button,element('br'));}if(!candidate.evidence.length)proof.append(element('span','本次未提取到定位信息','hint'));row.append(proof);$('tpl-candidates').append(row);
  }tplSelectionCount();
}
async function refreshTemplatePanel(force=false){
  if(state.scan?.platform!=='stm32')return;
  const signature=JSON.stringify((state.scan.device_report?.devices||[]).map(d=>[d.id,d.name,d.kind,d.category]));
  if(!force&&tplProject===state.scan.project_hash&&tplRoot===state.scan.root&&tplSignature===signature){if(tplPanel)pollTemplatePanel();return;}
  if(tplProject!==state.scan.project_hash||tplRoot!==state.scan.root){tplPanel=null;tplWidgets.clear();tplChoices.clear();tplCandidates=[];$('tpl-preview').hidden=true;}
  const token=++tplFetchToken,project=state.scan.project_hash,root=state.scan.root;tplLoading=true;tplSelectionCount();$('tpl-status').textContent='正在整理当前工程的设备与控制环…';
  try{const result=await api('template-panel');if(token!==tplFetchToken||state.scan?.project_hash!==project||state.scan?.root!==root)return;if(result.project_hash!==project||result.root!==root)throw Error('服务端工程已变化，请重新打开工程');
    const old=tplProject===project&&tplRoot===root?new Map(tplChoices):new Map();tplProject=project;tplRoot=root;tplSignature=signature;tplCandidates=result.candidates;tplTemplates=result.templates;tplPanel=result.panel;tplChoices.clear();
    const saved=new Map((tplPanel?.items||[]).map(item=>[item.id,item]));for(const candidate of tplCandidates){const prior=old.get(candidate.id),item=saved.get(candidate.id);tplChoices.set(candidate.id,prior||{id:candidate.id,name:item?.name||deviceNames.get(candidate.source_id)||candidate.name,template:item?.template||candidate.suggested,checked:!!item||chosenDevices.has(candidate.source_id)});}
    renderTemplateCandidates();renderTemplateControls();$('tpl-builder').open=!tplPanel;$('tpl-status').textContent=tplPanel?'已恢复这个工程的本机模拟面板。':tplCandidates.length?'请选择设备或控制环，再选模板生成面板。':'本次没有设备／控制环候选。请先扫描工程，或在设备清单中进行识别。';
  }catch(e){$('tpl-status').textContent=e.message;}
  finally{if(token===tplFetchToken){tplLoading=false;tplSelectionCount();}}
}
function renderTemplateControls(){
  tplWidgets.clear();$('tpl-controls').textContent='';$('tpl-preview').hidden=!tplPanel;tplPaused=false;tplTime=0;tplStarted=Date.now();$('tpl-pause').textContent='暂停模拟';
  if(!tplPanel)return;$('tpl-summary').textContent=tplPanel.items.length+' 个项目 · '+tplPanel.items.reduce((n,i)=>n+i.fields.length,0)+' 个模拟字段 · 参数和面板保存在本机';
  for(const item of tplPanel.items){const card=element('article',undefined,'tpl-card'),heading=element('div',undefined,'tpl-card-heading');heading.append(element('h3',item.name),element('span','模拟','source-badge simulation'));const ask=element('button','问这项','outline ask-item');ask.onclick=()=>openQuestion(item.id);heading.append(ask);if(item.template==='display'){const preview=element('button','打开模拟屏幕','outline');preview.onclick=()=>{workspaceNavigated=true;showWorkspace('screen');screenState.text=String(tplPanel.values[item.fields[0].id]??item.fields[0].initial);screenState.page='text';renderScreen();};heading.append(preview);}card.append(heading,element('p',item.template_label+' · '+item.instance,'hint'));
    for(const field of item.fields){const fieldBox=element('div',undefined,'tpl-field'),header=element('div',undefined,'tpl-field-heading'),value=element('strong','—');header.append(element('span',field.label+(field.unit?' / '+field.unit:'')),value);fieldBox.append(header);const caption=element('p',field.access==='rw'?'模拟设定值 · 本机回显':'示例波形 · 非真实采集','tpl-caption');fieldBox.append(caption);let input,ack,button;
      if(field.access==='rw'){const edit=element('div',undefined,'tpl-edit');input=element(field.type==='bool'?'select':'input');
        if(field.type==='bool'){for(const [v,label] of [['false','关闭'],['true','开启']]){const o=element('option',label);o.value=v;input.append(o);}}
        else{input.type=field.type==='text'?'text':'number';if(field.type==='number'){input.min=field.min;input.max=field.max;input.step='any';}else input.maxLength=80;}
        input.value=String(tplPanel.values[field.id]??field.initial);input.setAttribute('aria-label',item.name+' '+field.label+' 模拟值');button=element('button','应用到模拟器');ack=element('p','','tpl-ack');
        button.onclick=async()=>{const active=tplPanel;button.disabled=true;try{const changed=field.type==='bool'?input.value==='true':field.type==='text'?input.value:Number(input.value);if(field.type==='number'&&input.value.trim()==='')throw Error('请填写数值');const result=await api('template-panel-set',{panel_id:active.id,project_hash:active.project_hash,field:field.id,value:changed});if(tplPanel?.id!==active.id)return;tplPanel.values[field.id]=result.value;ack.textContent=result.notice;value.textContent=tplValue(result.value);pollTemplatePanel();}catch(e){ack.textContent=e.message;}finally{button.disabled=false;}};edit.append(input,button);fieldBox.append(edit,ack);
      }
      let canvas;if(field.type==='number'){canvas=element('canvas');canvas.width=650;canvas.height=90;canvas.setAttribute('aria-label',item.name+' '+field.label+' 模拟趋势');fieldBox.append(canvas);}
      if(field.initial_source)fieldBox.append(element('p',field.initial_source,'tpl-caption'));card.append(fieldBox);tplWidgets.set(field.id,{value,canvas,history:[]});
    }
    const proof=element('details');proof.append(element('summary','设备与源码依据'));proof.append(element('p',item.origin+'；模板类型由用户确认。','hint'));for(const e of item.evidence){const b=element('button',e.path+':'+e.line,'source-link');b.onclick=()=>showSource({...e,role:e.role||'设备来源',sha256:e.sha256||state.scan.files?.[e.path]||''});proof.append(b,element('br'));}card.append(proof);$('tpl-controls').append(card);
  }pollTemplatePanel();
}
function tplValue(value){return typeof value==='boolean'?(value?'开启':'关闭'):typeof value==='number'?Number(value.toFixed(3)).toLocaleString():String(value);}
async function pollTemplatePanel(){
  if(tplPolling||tplPaused||!tplPanel||workspaceView!=='panel'||state.scan?.platform!=='stm32'||state.scan.project_hash!==tplProject||state.scan.root!==tplRoot)return;
  const active=tplPanel;tplPolling=true;
  try{tplTime=Math.min(86400,(Date.now()-tplStarted)/1000);const result=await api('template-panel-data?panel_id='+encodeURIComponent(active.id)+'&project_hash='+encodeURIComponent(active.project_hash)+'&t='+tplTime.toFixed(3));if(tplPanel?.id!==result.panel_id||state.scan?.project_hash!==result.project_hash||state.scan?.root!==active.root)return;
    for(const [id,current] of Object.entries(result.values)){const widget=tplWidgets.get(id);if(!widget)continue;widget.value.textContent=tplValue(current);if(widget.canvas){widget.history.push(current);if(widget.history.length>60)widget.history.shift();graph(widget.canvas,widget.history);}}
  }catch(e){if(tplPanel?.id===active.id){tplPaused=true;$('tpl-pause').textContent='继续模拟';$('tpl-status').textContent=e.message+'；可刷新面板后继续。';}}
  finally{tplPolling=false;}
}
$('tpl-filter').oninput=renderTemplateCandidates;$('tpl-all').onclick=()=>{for(const candidate of tplCandidates)if(tplMatches(candidate))tplChoices.get(candidate.id).checked=true;renderTemplateCandidates();};$('tpl-none').onclick=()=>{for(const choice of tplChoices.values())choice.checked=false;renderTemplateCandidates();};
$('tpl-refresh').onclick=()=>refreshTemplatePanel(true);
$('tpl-generate').onclick=async()=>{const project=state.scan?.project_hash,root=state.scan?.root;tplLoading=true;tplSelectionCount();try{const selections=[...tplChoices.values()].filter(c=>c.checked).map(({id,name,template})=>({id,name,template}));const result=await api('template-panel',{project_hash:project,selections});if(state.scan?.project_hash!==project||state.scan?.root!==root)return;tplPanel=result;tplProject=project;tplRoot=root;renderTemplateControls();$('tpl-builder').open=false;$('tpl-status').textContent='面板已生成并保存在本机。可以调整模拟值并查看回显，原工程和硬件未修改。';}catch(e){$('tpl-status').textContent=e.message;}finally{tplLoading=false;tplSelectionCount();}};
$('tpl-pause').onclick=()=>{tplPaused=!tplPaused;$('tpl-pause').textContent=tplPaused?'继续模拟':'暂停模拟';if(!tplPaused){tplStarted=Date.now()-tplTime*1000;pollTemplatePanel();}};
$('tpl-export').onclick=()=>{if(!tplPanel)return;const blob=new Blob([JSON.stringify(tplPanel,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=element('a');link.href=url;link.download='STM32-模拟面板.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('tpl-status').textContent='已导出包含模板、源码依据和本机模拟值的面板方案。';};
$('device-to-panel').onclick=async()=>{workspaceNavigated=true;showWorkspace('panel');await refreshTemplatePanel(true);for(const candidate of tplCandidates){const choice=tplChoices.get(candidate.id);choice.checked=chosenDevices.has(candidate.source_id);choice.name=deviceNames.get(candidate.source_id)||choice.name;}renderTemplateCandidates();$('tpl-builder').open=true;$('tpl-status').textContent='已带入设备清单的选择。核对模板类型后，点击生成面板。';};
setInterval(pollTemplatePanel,500);
