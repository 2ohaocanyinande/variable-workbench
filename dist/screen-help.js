let questionBusy=false,allQuestionTargets=[];
async function openQuestion(target='project'){
  if(questionBusy)return;$('question-dialog').showModal();$('question-status').textContent='正在整理可提问对象…';$('question-answer').textContent='';$('question-context').textContent='';
  const hash=state.scan?.project_hash;
  try{const result=await api('question-targets');if(state.scan?.project_hash!==hash)throw Error('工程已切换，请重试');allQuestionTargets=result.targets;$('question-filter').value='';filterQuestionTargets(target);$('question-status').textContent='选择对象后填写问题，可先预览发送内容。';}catch(e){$('question-status').textContent=e.message;}
}
async function sendQuestion(preview=false){
  if(questionBusy)return;questionBusy=true;$('question-send').disabled=true;$('question-preview').disabled=true;$('question-target').disabled=true;$('question-text').disabled=true;const project=state.scan?.project_hash,root=state.scan?.root,started=Date.now();$('question-status').className='hint busy';$('question-status').textContent='正在处理…';
  const timer=setInterval(()=>{$('question-status').textContent=(preview?'正在整理上下文':'正在等待回答')+' · '+Math.floor((Date.now()-started)/1000)+' 秒';},1000);
  try{const data={project_hash:project,target:$('question-target').value,question:$('question-text').value},result=await api(preview?'question-preview':'question-ask',data);if(state.scan?.project_hash!==project||state.scan?.root!==root)throw Error('工程已切换，请重新提问');
    $('question-context').textContent=JSON.stringify(preview?result:result.context,null,2);if(!preview)$('question-answer').textContent=result.answer;$('question-status').textContent=preview?'这是将发送的上下文，尚未调用模型。':result.source==='model'?'模型回答 · '+result.model+' · 请结合源码核对。':'本地说明 · 未调用模型';
  }catch(e){$('question-status').textContent=e.message;}finally{clearInterval(timer);questionBusy=false;$('question-send').disabled=false;$('question-preview').disabled=false;$('question-target').disabled=false;$('question-text').disabled=false;$('question-status').className='hint';}
}
$('question-target').onchange=()=>{if(!questionBusy){$('question-answer').textContent='';$('question-context').textContent='';}};
$('question-open').onclick=()=>openQuestion(workspaceView==='screen'?'screen':'module:'+workspaceView);$('screen-ask').onclick=()=>openQuestion('screen');$('question-close').onclick=()=>{if(!questionBusy)$('question-dialog').close();};$('question-send').onclick=()=>sendQuestion();$('question-preview').onclick=()=>sendQuestion(true);

function filterQuestionTargets(selected='project'){const query=$('question-filter').value.toLowerCase();$('question-target').textContent='';const matches=allQuestionTargets.filter(t=>t.name.toLowerCase().includes(query)||t.id===selected).slice(0,200);const pinned=allQuestionTargets.find(t=>t.id===selected);if(pinned&&!matches.some(t=>t.id===selected))matches.unshift(pinned);for(const t of matches){const option=element('option',t.name);option.value=t.id;$('question-target').append(option);}if(matches.some(t=>t.id===selected))$('question-target').value=selected;}
$('question-filter').oninput=()=>filterQuestionTargets('');

$('module-question').onclick=()=>openQuestion('module:'+workspaceView);
