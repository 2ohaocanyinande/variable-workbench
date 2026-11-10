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
const context=vm.createContext({document:{body:new Node('body'),getElementById:id=>{assert(nodes.has(id),'missing ID '+id);return nodes.get(id);},createElement:tag=>new Node(tag),createElementNS:(_,tag)=>new Node(tag)},window:{addEventListener(){}},navigator:{sendBeacon(){}},fetch:async()=>({ok:true,json:async()=>initial}),setTimeout(){},setInterval(){},clearInterval(){},Date,Map,Set,AbortController});
vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
vm.runInContext(fs.readFileSync('dist/tuning.js','utf8'),context);
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
    const guide=nodes.get('guide-dialog'),picker=nodes.get('project-picker');
    guide.showModal=()=>{guide.open=true;};
    guide.close=()=>{guide.open=false;};
    picker.showModal=()=>{picker.open=true;};
    nodes.get('guide-open').onclick();
    assert.strictEqual(guide.open,true);
    nodes.get('guide-close').onclick();
    assert.strictEqual(guide.open,false);
    const apiModal=nodes.get('api-modal');
    apiModal.showModal=()=>{apiModal.open=true;};
    nodes.get('guide-open').onclick();
    nodes.get('guide-api').onclick();
    assert.strictEqual(guide.open,false);
    assert.strictEqual(apiModal.open,true);
    nodes.get('guide-open').onclick();
    nodes.get('guide-start').onclick();
    assert.strictEqual(guide.open,false);
    assert.strictEqual(picker.open,true);
    assert(nodes.get('devices').classes.has('view-active'));
    vm.runInContext("showWorkspace('serial')",context);
    vm.runInContext("state.connected=true;state.serial_mode='raw';state.serial_port='COM_TEST';state.serial_baudrate=9600;state.bridge_connected=false;renderSerialConnection();",context);
    assert.strictEqual(nodes.get('serial-send').disabled,false);
    assert.strictEqual(nodes.get('connect').disabled,true);
    assert.strictEqual(nodes.get('serial-baud').value,9600);
    vm.runInContext("renderSerialData({session:1,events:[{id:1,time:1,direction:'RX',bytes:4,text:'PING',hex:'50 49 4E 47'}],rx_bytes:4,tx_bytes:0});",context);
    assert(nodes.get('serial-log').textContent.includes('PING'));
    assert.strictEqual(nodes.get('serial-count').children[0].children[2].textContent,'4');
    nodes.get('serial-view').value='hex';vm.runInContext('drawSerialEvents()',context);
    assert(nodes.get('serial-log').textContent.includes('50 49 4E 47'));
    vm.runInContext("state.scan.pid={loops:[{id:'pid-test',symbol:'balance',type:'PID',calls:[],kernels:[],evidence:[],gains:{kp:{value:15,field:'kp',sources:[{path:'pid.c',line:1,literal:'15',value:15}]}}}],edges:[],draft:{loops:[{id:'pid-test',gains:{kp:{value:14.25,source_index:null}}}]}};renderPid();",context);
    assert.strictEqual(vm.runInContext("pidEditors.get('pid-test').gains.kp.source.value",context),'','unbound diagnostic trial must stay unbound');
    vm.runInContext("state.scan.pid.loops.push({...state.scan.pid.loops[0],id:'pid-inner',symbol:'rate'});state.scan.pid.edges=[{from:'pid-test',to:'pid-inner',kind:'串级候选',signal:'target_rate',argument:'target_rate',evidence:[]}];renderPid();",context);
    nodes.get('pid-edges').children[0].children[1].children[2].onclick();
    assert.strictEqual(vm.runInContext("pidEditors.get('pid-inner').card.open",context),true);
    vm.runInContext("renderTuningReport({record_id:'simulation',source:'simulation',metrics:{tail_rms_error:1,frequency_hz:1,saturation_fraction:0,settling_seconds:null},findings:[],warnings:[],notice:'synthetic',series:[{t:0,angle:1,target:0,gyro:2,output:3},{t:1,angle:4,target:0,gyro:5,output:6}],data_sha256:'test',report_path:'test.json'});",context);
    assert.strictEqual(nodes.get('tuning-replay').hidden,false);
    nodes.get('tuning-cursor').value='1000';nodes.get('tuning-cursor').oninput();
    assert(nodes.get('tuning-time').textContent.includes('角度 4'));
    assert(nodes.get('tuning-time').textContent.includes('角速度 5'));
    assert(nodes.get('tuning-time').textContent.includes('输出 6'));
    const cursors=['angle','gyro','output'].map(key=>nodes.get('tuning-'+key+'-plot').ctx.moves.at(-1)[0]);
    assert(cursors.every(x=>x===cursors[0]&&Number.isFinite(x)),'all replay cursors must share the time axis');
    assert.strictEqual(nodes.get('nav-panel').hidden,true);
    vm.runInContext("showWorkspace('panel');",context);
    assert.strictEqual(vm.runInContext('workspaceView',context),'devices');
    assert(!nodes.has('nav-demo')&&!nodes.has('screen-manual')&&!nodes.has('template-section'));
    vm.runInContext("state.scan.rtos={status:'FreeRTOS 线索已发现',tasks:[{kind:'任务',name:'worker',entry:'Worker',priority:'2',stack:'128',stack_unit:'StackType_t 元素',evidence:[{role:'xTaskCreate',path:'main.c',line:3}]}],objects:[],scheduler:[],evidence:[]};renderFields();showWorkspace('rtos');",context);
    assert(nodes.get('rtos-section').classes.has('view-active'));
    const rtosResults=nodes.get('rtos-results');
    assert.strictEqual(rtosResults.children[0].children[0].children[1].children[0].textContent,'1');
    const rtosTask=rtosResults.children[1].children[2].children[1];
    assert.strictEqual(rtosTask.children[2].children[1].children[0].textContent,'128 StackType_t 元素');
    assert(rtosTask.children[3].children[1].textContent.includes('main.c:3'));
    assert.strictEqual(vm.runInContext("rtosStackValue('512 * 4')",context),2048);
    assert.strictEqual(vm.runInContext("rtosStackValue('sizeof(stack)')",context),null);
    vm.runInContext("state.scan.rtos.tasks=Array.from({length:9},(_,i)=>({...state.scan.rtos.tasks[0],name:'task-'+i}));renderRtos(state.scan.rtos);",context);
    const manyTasks=rtosResults.children[1],taskFilter=manyTasks.children[2],taskList=manyTasks.children[3];
    assert.strictEqual(taskList.children.filter(n=>n.className==='rtos-task').length,9);
    taskFilter.value='task-8';taskFilter.oninput();
    assert.strictEqual(taskList.children.filter(n=>n.className==='rtos-task'&&!n.hidden).length,1);
    taskFilter.value='unknown';taskFilter.oninput();
    assert.strictEqual(taskList.children.at(-1).hidden,false);
    let reviewRequest;
    context.reviewTestAPI=async(path,body)=>{
      assert.strictEqual(path,'device-review');reviewRequest=body;
      return {files_checked:2,scope:'静态源码复核',conflicts:[],components:[],interfaces:[]};
    };
    vm.runInContext("api=reviewTestAPI;state.scan.project_hash='r';state.scan.inventory.endpoints=[{id:'adc1',family:'ADC',handle:'hadc1',channel:'',path:'adc.c',calls:[]}];renderDevices();",context);
    assert.strictEqual(nodes.get('device-graphic').children[1].children[0].children[2].textContent,'1');
    const deviceRow=nodes.get('device-list').children.at(-1).children[1];
    const reviewButton=deviceRow.children[3].children.find(n=>n.textContent==='细检测');
    await reviewButton.onclick();
    assert.strictEqual(reviewRequest.id,'adc1');
    assert.strictEqual(reviewRequest.scope,'interface');
    assert.strictEqual(reviewRequest.project_hash,'r');
    assert.strictEqual(reviewButton.disabled,false);
    vm.runInContext(`state.scan.device_report={devices:[{
      id:'imu',name:'IMU',instance:'MPU6050',endpoint_ids:['imu1'],interfaces:[],features:[],evidence:[],status:'AI'
    }]};renderDevices();`,context);
    assert(nodes.get('device-count').textContent.includes('另保留 1 项'));
    const uncoveredRow=nodes.get('device-list').children.at(-1).children[2];
    await uncoveredRow.children[3].children.find(n=>n.textContent==='细检测').onclick();
    assert.strictEqual(reviewRequest.id,'adc1');
    assert.strictEqual(reviewRequest.scope,'interface');
    vm.runInContext(`
      const pwmEvidence=[{path:'pwm.c',line:77,role:'底层寄存器访问'}];
      const pwmEndpoint=(id,path,channel)=>({id,family:'PWM',handle:'TIM_2',channel,path,
        calls:[{line:6,api:'pwm_init'}],register_evidence:pwmEvidence});
      const motorPwm=pwmEndpoint('motor-pwm','motor.c','TIM2_CH1');
      state.scan.inventory.endpoints=[motorPwm,pwmEndpoint('main-pwm','main.c','TIM2_CH1'),
        pwmEndpoint('other-pwm','motor.c','TIM2_CH2')];
      state.scan.device_report={devices:[{id:'motor',name:'左电机A',instance:'motorA_duty',
        endpoint_ids:[motorPwm.id],interfaces:[motorPwm],features:['PWM TIM2_CH1'],evidence:[],status:'AI',numeric_review_required:true}]};
      renderDevices();
    `,context);
    const pwmRows=nodes.get('device-list').children.at(-1).children;
    assert.strictEqual(pwmRows.length,3);
    const numericWarning=pwmRows[1].children[1].children.find(n=>n.className==='validation-warning');
    assert(numericWarning&&!numericWarning.hidden);
    const reviewPwm=pwmRows[1].children[3].children.find(n=>n.textContent==='细检测');
    let numericStatus='verified';
    context.numericTestAPI=async()=>({files_checked:2,scope:'静态源码复核',conflicts:[],components:[],interfaces:[],
      numeric_claims:[{feature:'PWM TIM2_CH1',status:numericStatus,reason:'通道证据',evidence:[]}],
      unit_claims:[{feature:'读取转速',reason:'可另查比例'}]});
    vm.runInContext('api=numericTestAPI',context);
    await reviewPwm.onclick();
    assert.strictEqual(numericWarning.hidden,true);
    const reviewOutput=pwmRows[1].children[3].children.at(-1);
    const units=reviewOutput.children.find(n=>n.children[0]?.textContent==='物理单位与换算（可选）');
    assert(units&&!units.open);
    numericStatus='pending';
    await reviewPwm.onclick();
    assert.strictEqual(numericWarning.hidden,false);
    assert(numericWarning.textContent.includes('还有 1 项'));
    const extraCalls=pwmRows[1].children[3].children.find(n=>n.children[0]?.textContent==='同一 PWM 通道的其他源码位置');
    assert(extraCalls.children.some(n=>n.textContent==='main.c:6'));
    assert(pwmRows[2].children[2].children[0].textContent.includes('TIM2_CH2'));
    const reviewAll=nodes.get('device-review-all');
    const checkedRows=[];
    context.batchReviewAPI=async(path,body)=>{
      assert.strictEqual(path,'device-review');
      assert(reviewAll.disabled);
      checkedRows.push([body.scope,body.id]);
      if(body.scope==='interface')throw new Error('测试单行失败');
      return {files_checked:2,scope:'本地复核',conflicts:[],components:[],interfaces:[],
        numeric_claims:[{feature:'PWM TIM2_CH1',status:'verified',reason:'通道证据',evidence:[]}]};
    };
    vm.runInContext('api=batchReviewAPI',context);
    assert.strictEqual(reviewAll.disabled,false);
    await reviewAll.onclick();
    assert.deepStrictEqual(checkedRows,[['device','motor'],['interface','other-pwm']]);
    assert(nodes.get('device-review-progress').textContent.includes('1 项已复核，0 项待核对，1 项执行失败'));
    assert(!reviewOutput.children[0].open);
    assert.strictEqual(numericWarning.hidden,true);
    assert.strictEqual(reviewAll.disabled,false);
    vm.runInContext('state.scan.device_report=null;renderDevices();',context);
    const localPwmRows=nodes.get('device-list').children.at(-1).children;
    assert.strictEqual(localPwmRows.length,3);
    assert(localPwmRows[1].children[3].children.some(n=>n.children.some(link=>link.textContent==='main.c:6')));
    vm.runInContext("state.scan.root='OTHER_ROOT';state.scan.project_hash='p'.repeat(64);showWorkspace('screen');",context);
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
