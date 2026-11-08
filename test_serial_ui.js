// Minimal DOM contract test: STM32 connection UI is available without a panel.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('dist/index.html','utf8');
class Node {
  constructor(tag='div'){this.tag=tag;this.className='';this.children=[];this.value='';this.disabled=false;this.hidden=false;this.dataset={};this.style={};this.classes=new Set();this.classList={add:(...v)=>v.forEach(x=>this.classes.add(x)),contains:x=>this.classes.has(x),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};}
  set textContent(v){this.text=String(v);this.children=[];}
  get textContent(){return this.text||'';}
  append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value&&nodes.length)this.value=nodes[0].value;}
  get options(){return this.children;}
  setAttribute(){} addEventListener(){} showModal(){} close(){} scrollIntoView(){}
  querySelector(){return this.bridgeOption||(this.bridgeOption=new Node('option'));}
  getContext(){if(!this.ctx){if(!this.width)this.width=1100;if(!this.height)this.height=220;this.ctx={moves:[],texts:[],clearRect(){},fillRect(){},fillText(text,x,y){this.texts.push({text,x,y,color:this.fillStyle});},beginPath(){},lineTo(){},stroke(){},arc(){},fill(){},setLineDash(){},moveTo(x,y){this.moves.push([x,y]);}};}return this.ctx;}
}
const nodes=new Map();
for(const m of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)){assert(!nodes.has(m[2]),'duplicate ID '+m[2]);nodes.set(m[2],new Node(m[1]));}
nodes.get('serial-mode').value='raw';nodes.get('serial-baud').value='115200';nodes.get('serial-view').value='text';
const initial={scan:{platform:'stm32',root:'TEST_STM32',fields:[],project_info:{},inventory:{endpoints:[]}},ports:[{name:'COM_TEST',description:'mock port'}],connected:false,manifest:null};
const context=vm.createContext({document:{body:new Node('body'),getElementById:id=>{assert(nodes.has(id),'missing ID '+id);return nodes.get(id);},createElement:tag=>new Node(tag)},window:{addEventListener(){}},navigator:{sendBeacon(){}},fetch:async()=>({ok:true,json:async()=>initial}),setTimeout(){},setInterval(){},clearInterval(){},Date,Map,Set,AbortController});
vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/tuning.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/showcase.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/template-panel.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/screen-help.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/source-screen.js','utf8'),context);
setImmediate(async()=>{
  try{
    vm.runInContext("showWorkspace('serial')",context);
    assert(nodes.get('serial').classes.has('view-active'));
    assert(!nodes.get('pid-section').classes.has('view-active'));
    assert.strictEqual(nodes.get('serial').hidden,false);
    assert.strictEqual(nodes.get('panel').hidden,true);
    assert.strictEqual(nodes.get('connect').disabled,false);
    assert.strictEqual(nodes.get('serial-send').disabled,true);
    vm.runInContext("state.connected=true;state.serial_mode='raw';state.serial_port='COM_TEST';state.serial_baudrate=9600;state.bridge_connected=false;renderSerialConnection();",context);
    assert.strictEqual(nodes.get('serial-send').disabled,false);
    assert.strictEqual(nodes.get('connect').disabled,true);
    assert.strictEqual(nodes.get('serial-baud').value,9600);
    vm.runInContext("renderSerialData({session:1,events:[{id:1,time:1,direction:'RX',bytes:4,text:'PING',hex:'50 49 4E 47'}],rx_bytes:4,tx_bytes:0});",context);
    assert(nodes.get('serial-log').textContent.includes('PING'));
    nodes.get('serial-view').value='hex';vm.runInContext('drawSerialEvents()',context);
    assert(nodes.get('serial-log').textContent.includes('50 49 4E 47'));
    vm.runInContext("state.scan.pid={loops:[{id:'pid-test',symbol:'balance',type:'PID',calls:[],kernels:[],evidence:[],gains:{kp:{value:15,field:'kp',sources:[{path:'pid.c',line:1,literal:'15',value:15}]}}}],edges:[],draft:{loops:[{id:'pid-test',gains:{kp:{value:14.25,source_index:null}}}]}};renderPid();",context);
    assert.strictEqual(vm.runInContext("pidEditors.get('pid-test').gains.kp.source.value",context),'','unbound diagnostic trial must stay unbound');
    vm.runInContext("renderTuningReport({record_id:'simulation',source:'simulation',metrics:{tail_rms_error:1,frequency_hz:1,saturation_fraction:0,settling_seconds:null},findings:[],warnings:[],notice:'synthetic',series:[{t:0,angle:1,target:0,gyro:2,output:3},{t:1,angle:4,target:0,gyro:5,output:6}],data_sha256:'test',report_path:'test.json'});",context);
    assert.strictEqual(nodes.get('tuning-replay').hidden,false);
    nodes.get('tuning-cursor').value='1000';nodes.get('tuning-cursor').oninput();
    assert(nodes.get('tuning-time').textContent.includes('角度 4'));
    assert(nodes.get('tuning-time').textContent.includes('角速度 5'));
    assert(nodes.get('tuning-time').textContent.includes('输出 6'));
    const cursors=['angle','gyro','output'].map(key=>nodes.get('tuning-'+key+'-plot').ctx.moves.at(-1)[0]);
    assert(cursors.every(x=>x===cursors[0]&&Number.isFinite(x)),'all replay cursors must share the time axis');
    const records=['oscillating','damped','noise','windup'].map((key,i)=>({id:'r'+i,source:'simulation',samples:600,state:'complete',channels:['angle_deg','target_deg','gyro_dps','control_out','i_out','d_out'],info:{experiment_id:'same-fixture',tuning_scenario:key,snapshot:{pid:{kp:15,ki:0,kd:.75},unit:'deg',sample_dt:.02,lower:-1000,upper:1000}}}));
    const requests=[];
    context.demoTestAPI=async(path,data)=>{requests.push(path);if(path==='records')return {records};if(path==='tuning-diagnose'){const key=records.find(r=>r.id===data.id).info.tuning_scenario;return {record_id:data.id,source:'simulation',report_path:'fixture.json',record_snapshot:{pid:{kp:15}},data_sha256:'fixture',metrics:{samples:600,frequency_hz:1.19,amplitude:8.68,d_output_correlation:.984,saturation_fraction:key==='windup'?1:0,integral_change:143.6,settling_seconds:key==='damped'?3:null,tail_rms_error:6.21},findings:[{title:'fixture evidence',evidence:['measured'],possible_causes:[],checks:[],direction:'check first'}],warnings:[],notice:'fixture',proposal:key==='oscillating'?{before:15,after:14.25}:null,series:[{t:0,angle:10,target:0,gyro:0,output:0},{t:12,angle:key==='damped'?0:8,target:0,gyro:1,output:2}]};}if(path==='tuning-compare')return {before:{tail_rms_error:6.2145},after:{tail_rms_error:.00903,settling_seconds:3}};throw Error('unexpected endpoint '+path);};
    vm.runInContext("api=demoTestAPI;workspaceNavigated=true;showWorkspace('demo');",context);
    await vm.runInContext('prepareShowcase()',context);
    assert.strictEqual(vm.runInContext('demoState.loaded',context),true);
    assert.strictEqual(nodes.get('demo-next').disabled,false);
    nodes.get('demo-next').onclick();assert.strictEqual(vm.runInContext('demoState.stage',context),1);
    assert(nodes.get('demo-metric-a').textContent.includes('1.19'));
    nodes.get('demo-next').onclick();assert(nodes.get('demo-metric-b').textContent.includes('14.25'));
    nodes.get('demo-next').onclick();assert.strictEqual(nodes.get('demo-after-legend').hidden,false);
    assert(nodes.get('demo-metric-b').textContent.includes('0.009'));
    nodes.get('demo-present').onclick();assert.strictEqual(vm.runInContext("document.body.classList.contains('demo-presentation')",context),true);
    vm.runInContext("showWorkspace('serial')",context);assert.strictEqual(vm.runInContext("document.body.classList.contains('demo-presentation')",context),false);vm.runInContext("showWorkspace('demo')",context);
    nodes.get('demo-scenario-noise').onclick();vm.runInContext('setDemoStage(2)',context);
    assert.strictEqual(nodes.get('demo-metric-b').textContent,'暂不生成');
    vm.runInContext('setDemoStage(3)',context);assert.strictEqual(nodes.get('demo-after-legend').hidden,true);
    assert.strictEqual(nodes.get('demo-final-step').textContent,'诊断小结');
    await nodes.get('demo-details').onclick();
    assert.strictEqual(vm.runInContext('workspaceView',context),'records');
    assert.strictEqual(nodes.get('tuning-loop').value,'','synthetic demo must not bind itself to a real project loop');
    assert.strictEqual(nodes.get('tuning-confirmed').checked,true);
    assert.strictEqual(nodes.get('tuning-angle').value,'angle_deg');
    assert(!requests.some(path=>['write','pid-config','scan','serial-send','analyze-usage'].includes(path)),'showcase must not write hardware/source or call cloud AI');
    context.demoTestAPI=async()=>{throw Error('offline test');};vm.runInContext("api=demoTestAPI;showWorkspace('demo');",context);await vm.runInContext('prepareShowcase()',context);
    assert(nodes.get('demo-status').textContent.includes('载入失败'));assert.strictEqual(nodes.get('demo-start').disabled,false);
    const project='p'.repeat(64),root='TEST_STM32';let savedPanel=null;const templateCalls=[];
    const candidates=[{id:'device:left',source_id:'left',name:'左电机',instance:'L',suggested:'motor',evidence:[],origin:'fixture'},{id:'device:right',source_id:'right',name:'右电机',instance:'R',suggested:'motor',evidence:[],origin:'fixture'}];
    context.templateTestAPI=async(path,data)=>{templateCalls.push(path.split('?')[0]);
      if(path==='template-panel'&&!data)return {project_hash:project,root,candidates,templates:[{id:'motor',label:'电机模板'}],panel:savedPanel};
      if(path==='template-panel'){savedPanel={id:'panel-test',root,project_hash:project,mode:'simulation',values:{},items:data.selections.map(s=>({...candidates.find(c=>c.id===s.id),name:s.name,template:s.template,template_label:'模拟电机',fields:[{id:s.id+'::output',label:'输出设定',type:'number',access:'rw',min:-100,max:100,initial:0,unit:'%'}]}))};return savedPanel;}
      if(path==='template-panel-set'){savedPanel.values[data.field]=data.value;return {value:data.value,hardware_written:false,notice:'本机回显'};}
      if(path.startsWith('template-panel-data?'))return {project_hash:project,panel_id:savedPanel.id,mode:'simulation',values:Object.fromEntries(savedPanel.items.flatMap(i=>i.fields.map(f=>[f.id,savedPanel.values[f.id]??f.initial])))};
      throw Error('unexpected template endpoint '+path);
    };
    vm.runInContext("api=templateTestAPI;state.scan={root:'TEST_STM32',project_hash:'p'.repeat(64),platform:'stm32',fields:[],pid:{loops:[],edges:[]},inventory:{endpoints:[]},project_info:{}};renderFields();workspaceNavigated=true;showWorkspace('panel');",context);
    await vm.runInContext('refreshTemplatePanel(true)',context);
    assert.strictEqual(vm.runInContext('workspaceView',context),'panel');assert.strictEqual(nodes.get('nav-panel').hidden,false);assert.strictEqual(nodes.get('template-section').hidden,false);
    vm.runInContext('for(const c of tplChoices.values())c.checked=true;tplSelectionCount();',context);await nodes.get('tpl-generate').onclick();
    assert.strictEqual(nodes.get('tpl-controls').children.length,2);
    const firstEdit=nodes.get('tpl-controls').children[0].children[2].children[2];firstEdit.children[0].value='25';await firstEdit.children[1].onclick();
    assert.strictEqual(savedPanel.values['device:left::output'],25);assert.strictEqual(savedPanel.values['device:right::output'],undefined);
    await vm.runInContext('refreshTemplatePanel(true)',context);assert.strictEqual(nodes.get('tpl-controls').children[0].children[2].children[2].children[0].value,'25');
    vm.runInContext("state.scan.root='OTHER_ROOT'",context);await vm.runInContext('refreshTemplatePanel(true)',context);assert.strictEqual(nodes.get('tpl-preview').hidden,true);
    assert(!templateCalls.some(path=>['write','serial-send','pid-config','analyze-usage','generate'].includes(path)),'STM32 template controls must use isolated simulation endpoints');
    vm.runInContext("showWorkspace('screen');",context);assert.strictEqual(vm.runInContext('workspaceView',context),'screen');
    nodes.get('screen-down').onclick();nodes.get('screen-ok').onclick();assert.strictEqual(vm.runInContext('screenState.page',context),'text');
    nodes.get('screen-back').onclick();nodes.get('screen-down').onclick();nodes.get('screen-ok').onclick();assert.strictEqual(vm.runInContext('screenState.page',context),'settings');
    const oldBrightness=vm.runInContext('screenState.brightness',context);nodes.get('screen-down').onclick();assert.strictEqual(vm.runInContext('screenState.brightness',context),oldBrightness-5);
    nodes.get('screen-power').onclick();assert.strictEqual(vm.runInContext('screenState.on',context),false);
    context.helpTestAPI=async(path,data)=>path==='question-targets'?{targets:[{id:'screen',name:'模拟屏幕'}]}:path==='question-preview'?{target:{name:'模拟屏幕'},snippets:[]}: {source:'local',answer:'本地说明',context:{target:{name:'模拟屏幕'}}};
    vm.runInContext('api=helpTestAPI',context);await vm.runInContext("openQuestion('screen')",context);nodes.get('question-text').value='为什么这样显示？';await nodes.get('question-preview').onclick();assert(nodes.get('question-status').textContent.includes('尚未调用模型'));await nodes.get('question-send').onclick();assert.strictEqual(nodes.get('question-answer').textContent,'本地说明');assert.strictEqual(nodes.get('question-send').disabled,false);
    let copied='';context.navigator.clipboard={writeText:async value=>{copied=value;}};
    const sourceGroup={id:'g',name:'draw',path:'main.c',line:1,variables:['speed'],buttons:[],calls:[{id:'c',source:'OLED_ShowNum(1,1,speed,3)',path:'main.c',line:2,api:'OLED_ShowNum',guards:[]}]};
    context.sourceTestAPI=async(path,data)=>path==='source-screen'?{root:'OTHER_ROOT',project_hash:'p'.repeat(64),groups:[sourceGroup],unsupported:[],notice:'static'}:{rows:['Speed '+(data.values.speed??'?')],warnings:[],notice:'static'};
    vm.runInContext('api=sourceTestAPI',context);await vm.runInContext('loadScreen(true)',context);assert.strictEqual(nodes.get('ss-variables').children.length,1);
    vm.runInContext("ssWidgets.get('speed').value='17'",context);await vm.runInContext('previewSourceScreen()',context);assert(nodes.get('ss-display').textContent.includes('17'));await nodes.get('ss-copyall').onclick();await Promise.resolve();assert.strictEqual(copied,'speed');
    sourceGroup.defaults={speed:{value:8,path:'main.c',line:1}};sourceGroup.profile={title:'LCD 320×240',transport:'GPIO 总线'};
    sourceGroup.calls[0].guards=[{name:'speed',op:'==',value:8}];sourceGroup.calls.push({...sourceGroup.calls[0],id:'c2',guards:[{name:'speed',op:'!=',value:8}]});
    context.sourceTestAPI=async(path,data)=>path==='source-screen'?{root:'OTHER_ROOT',project_hash:'p'.repeat(64),groups:[sourceGroup],unsupported:[],notice:'static'}:{rows:['VOLT:7.2V'],warnings:[],notice:'static',background:'#000000',profile:{width:320,height:240,title:'LCD'},draws:[{kind:'text',text:'VOLT:7.2V',x:0,y:72,font_width:16,font_height:24,foreground:'#ffffff',background:'#000000'}]};
    vm.runInContext('api=sourceTestAPI',context);await vm.runInContext('loadScreen(true)',context);await vm.runInContext('previewSourceScreen()',context);
    assert.strictEqual(vm.runInContext("ssWidgets.get('speed').value",context),'8');assert.strictEqual(nodes.get('ss-canvas').hidden,false);assert.strictEqual(nodes.get('ss-canvas').width,320);
    assert(nodes.get('ss-canvas').ctx.texts.some(c=>c.text==='V'&&c.y===72&&c.color==='#ffffff'));assert.strictEqual(nodes.get('ss-display').hidden,true);
    vm.runInContext("openQuestion=async target=>{globalThis.nativeAsked=target};state.scan.fields=[{id:'temp',label:'温度',module:'chip',symbol:'temperature',kind:'temperature',type:'float',access:'ro',data_source:'test',status:'test',evidence:[],selectable:false}];renderFields();",context);
    await nodes.get('fields').children[0].children[1].children.find(n=>n.tag==='button').onclick();assert.strictEqual(context.nativeAsked,'native-field:temp');
    console.log('PASS previous flows, source preview/copying, native field question binding; mocked DOM.');
  }catch(error){console.error(error);process.exitCode=1;}
});
