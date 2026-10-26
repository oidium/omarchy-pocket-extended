const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const h={};vm.createContext(h);vm.runInContext(fs.readFileSync('HistoryState.js','utf8'),h);
let count=0;
function test(name,run){run();count++;console.log('ok',name)}
function message(id='1',thread='9',extra={}){return Object.assign({device_id:'phone',thread_id:thread,message_id:id,timestamp:Number(id),addresses:['5550100','5550198'],body:'Hello 👋 世界',direction:'incoming',state:'received',android_read:1,attachments:[]},extra)}
function emit(s,m){h.receive(s,{event:'message',message:m})}
test('thread enumeration, ordering, same IDs isolated by thread/device',()=>{
 const s=h.create();emit(s,message());emit(s,message('1','10',{timestamp:10}));emit(s,message('1','9',{device_id:'other'}));
 assert.equal(h.threads(s,'phone').length,2);assert.equal(h.threads(s,'phone')[0].id,'10');
});
test('rejected record recipient-risk events immediately change reply authorization',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100']}));
 const t=s.threads[h.key('phone','9')];assert.equal(h.summary(t).replyStatus,'individual');
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'group'});
 assert.equal(h.summary(t).replyStatus,'group');assert.ok(h.summary(t).replyBlocked);
 h.receive(s,{event:'reply_scope_uncertain',device:'phone'});
 assert.equal(h.summary(t).replyStatus,'unknown');assert.ok(h.summary(t).replyBlocked);
});
test('device uncertainty stays fail-closed across later scope and message events',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100']}));
 const t=s.threads[h.key('phone','9')];assert.equal(h.summary(t).replyStatus,'individual');
 h.receive(s,{event:'reply_scope_uncertain',device:'phone'});
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'individual'});
 emit(s,message('2','9',{addresses:['5550100']}));
 assert.equal(h.summary(t).replyStatus,'unknown');assert.ok(h.summary(t).replyBlocked);
 assert.equal(s.replyUncertainDevices['$phone'],true);
});
test('independent safety events update status and invalidate stale conversation tokens',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100']}));
 const t=s.threads[h.key('phone','9')],old=t.token;
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'incomplete',conversation_token:'worker:changed'});
 assert.equal(t.replyStatus,'incomplete');assert.equal(t.token,'worker:changed');assert.notEqual(t.token,old);
 assert.ok(h.summary(t).replyBlocked);
});
test('authorization scope events stay distinct from retained message head through eviction',()=>{
 const s=h.create();h.receive(s,{event:'message',message:message('1','9',{addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'worker:1'});
 const t=s.threads[h.key('phone','9')];assert.equal(h.summary(t).replyBlocked,false);
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'individual',recipient_scope:['5550199'],conversation_token:'worker:2'});
 assert.equal(t.replyScope[0],'5550199');assert.equal(t.head.addresses[0],'5550100');assert.equal(h.summary(t).replyBlocked,false);
 h.receive(s,{event:'messages_evicted',device:'phone',thread:'9',ids:['1']});assert.equal(t.head.addresses[0],'5550100');assert.equal(h.summary(t).replyBlocked,false);
 t.head=null;assert.equal(h.summary(t).replyBlocked,false,'authoritative singleton scope survives loss of the display payload');
 h.receive(s,{event:'message',message:message('2','9',{addresses:['5550199']}),reply_status:'individual',recipient_scope:['5550199'],conversation_token:'worker:2'});
 assert.equal(h.summary(t).replyBlocked,false);assert.equal(t.head.addresses[0],'5550199');
});
test('same-ID replacement with earlier timestamp updates recipient scope and token',()=>{
 const s=h.create();h.receive(s,{event:'message',message:message('1','9',{timestamp:100,addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'worker:1'});
 const t=s.threads[h.key('phone','9')];
 h.receive(s,{event:'message',message:message('1','9',{timestamp:50,addresses:['5550199']}),reply_status:'individual',recipient_scope:['5550199'],conversation_token:'worker:2'});
 assert.equal(t.head.addresses[0],'5550199');assert.equal(t.replyScope[0],'5550199');assert.equal(t.token,'worker:2');assert.equal(h.summary(t).replyBlocked,false);
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'incomplete',conversation_token:'worker:3'});
 assert.equal(t.replyScope,null);assert.equal(t.token,'worker:3');assert.ok(h.summary(t).replyBlocked);
});
test('only an explicit newer-proof recovery event can clear ordering incomplete',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100']}));
 const t=s.threads[h.key('phone','9')];
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'incomplete',reply_risk:'ordering',conversation_token:'worker:2'});
 h.receive(s,{event:'message',message:message('1','9',{timestamp:300,addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'worker:3'});
 assert.equal(t.replyStatus,'incomplete','unmarked individual events do not clear sticky risk');
 h.receive(s,{event:'message',message:message('1','9',{timestamp:400,addresses:['5550199']}),reply_status:'individual',recipient_scope:['5550199'],conversation_token:'worker:4',reply_scope_recovered:true});
 assert.equal(t.replyStatus,'individual');assert.deepEqual(Array.from(t.replyScope),['5550199']);assert.equal(t.token,'worker:4');
 h.receive(s,{event:'reply_scope_uncertain',device:'phone'});
 h.receive(s,{event:'message',message:message('1','9',{timestamp:500,addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'worker:5',reply_scope_recovered:true});
 assert.equal(t.replyStatus,'unknown','uncertainty remains stronger than an ordering recovery');
});
test('sticky hazards reject recovery flags on both event paths',()=>{
 for(const hazard of ['group','incomplete'])for(const type of ['message','reply_scope']){
  const s=h.create();h.receive(s,{event:'message',message:message('1','9',{addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'w:1'});
  const t=s.threads[h.key('phone','9')];
  h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'incomplete',reply_risk:'ordering',conversation_token:'w:2'});
  h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:hazard,conversation_token:'w:3'});
  for(const token of ['w:4','w:5'])h.receive(s,{event:type,device:'phone',thread:'9',message:message('2','9',{addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:token,reply_scope_recovered:true});
  assert.equal(t.replyRisk,hazard);assert.equal(t.replyStatus,hazard);assert.equal(t.replyScope,null);assert.ok(h.summary(t).replyBlocked);
  // A later ordering label cannot downgrade a sticky restriction either.
  h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'incomplete',reply_risk:'ordering',conversation_token:'w:6'});
  assert.equal(t.replyRisk,hazard);
 }
});
test('ordering-only recovery is identical for message and safety events',()=>{
 for(const type of ['message','reply_scope']){
  const s=h.create();h.receive(s,{event:'message',message:message('1','9',{addresses:['5550100']}),reply_status:'incomplete',reply_risk:'ordering',conversation_token:'w:2'});
  const t=s.threads[h.key('phone','9')];
  const recovered={event:type,device:'phone',thread:'9',message:message('2','9',{addresses:['5550199']}),reply_status:'individual',recipient_scope:['5550199'],conversation_token:'w:2',reply_scope_recovered:true};
  h.receive(s,recovered);assert.equal(t.replyStatus,'incomplete','same token is not a recovery');
  recovered.conversation_token='w:3';h.receive(s,recovered);
  assert.equal(t.replyRisk,'');assert.equal(t.replyStatus,'individual');assert.equal(t.replyScope[0],'5550199');
 }
});
test('ordinary incomplete is sticky without explicit ordering metadata until worker reset',()=>{
 const s=h.create();h.receive(s,{event:'message',message:message('1','9',{addresses:[]}),reply_status:'incomplete',conversation_token:'w:1'});
 const t=s.threads[h.key('phone','9')];
 h.receive(s,{event:'message',message:message('2','9',{addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'w:2',reply_scope_recovered:true});
 assert.equal(t.replyRisk,'incomplete');assert.ok(h.summary(t).replyBlocked);
 h.receive(s,{event:'worker_stopped'});assert.equal(t.replyRisk,'');
 h.receive(s,{event:'message',message:message('3','9',{addresses:['5550100']}),reply_status:'individual',recipient_scope:['5550100'],conversation_token:'new:1'});
 assert.equal(t.replyStatus,'individual');
});
test('global uncertainty cannot be overridden and only worker reset clears the marker',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100']}));
 h.receive(s,{event:'reply_scope_uncertain',all:true});
 h.receive(s,{event:'reply_scope',device:'phone',thread:'9',reply_status:'individual'});
 emit(s,message('2','9',{addresses:['5550100']}));
 assert.equal(h.summary(s.threads[h.key('phone','9')]).replyStatus,'unknown');
 emit(s,message('1','10',{device_id:'returning',addresses:['5550100']}));
 assert.equal(h.summary(s.threads[h.key('returning','10')]).replyStatus,'unknown');
 h.receive(s,{event:'worker_stopped'});
 assert.equal(s.replyUncertainAll,false);assert.equal(Object.keys(s.replyUncertainDevices).length,0);
 emit(s,message('3','9',{addresses:['5550100']}));
 assert.equal(h.summary(s.threads[h.key('phone','9')]).replyStatus,'individual');
});
test('uncertainty map keys cannot collide with object prototype names',()=>{
 const s=h.create();h.receive(s,{event:'reply_scope_uncertain',device:'__proto__'});
 assert.equal(h.effectiveReplyStatus(s,'__proto__','individual'),'unknown');
 assert.equal(h.effectiveReplyStatus(s,'phone','individual'),'individual');
});
test('opening, overlapping pages, duplicate ids, live during page',()=>{
 const s=h.create();emit(s,message());const t=s.threads[h.key('phone','9')];
 assert.equal(h.load(s,'phone','9','p').op,'history');assert.equal(h.load(s,'phone','9','q'),null);
 emit(s,message());emit(s,message('2'));emit(s,message('3'));emit(s,message('2'));
 h.receive(s,{event:'history_result',device:'phone',thread:'9',request_id:'p',received:3,reason:'partial'});
 assert.equal(h.messages(t).length,3);assert.equal(t.pending,'');assert.ok(!t.status.includes('all'));
 assert.equal(h.load(s,'phone','9','q').thread,'9');
});
test('group participants exact contacts and ambiguous/missing fallback',()=>{
 const s=h.create();h.receive(s,{event:'contacts',device:'phone',contacts:[{name:'Alex Example',numbers:[{number:'555-0100'},{number:'5550101'}]}]});
 assert.equal(h.participants(s,'phone',['5550100','5550198']),'Alex Example\n5550100\n\n5550198');
 assert.equal(h.name(s,'phone','5550101'),'Alex Example');assert.equal(h.name(s,'phone','+15550100'),'+15550100');
 s.contacts.phone.push({name:'Other',numbers:[{number:'5550100'}]});assert.equal(h.name(s,'phone','5550100'),'5550100');
});
test('participant presentation resolves equivalent phone formatting and refreshes',()=>{
 const s=h.create();assert.equal(h.participants(s,'phone',['(202) 555-0147']),'(202) 555-0147');
 h.receive(s,{event:'contacts',device:'phone',contacts:[{name:'Riley Example',numbers:[{number:'+12025550147'}]}]});
 assert.equal(h.participants(s,'phone',['(202) 555-0147']),'Riley Example\n(202) 555-0147');
 assert.equal(h.participants(s,'phone',['+12025550148']),'+12025550148');
});
test('unicode, directions, status and read semantics',()=>{
 const s=h.create();emit(s,message());const t=h.threads(s,'phone')[0];assert.equal(h.messages(t)[0].body,'Hello 👋 世界');
 for(const state of ['received','sent','outbox','failed','queued','draft','unknown']) assert.ok(h.status(message('1','9',{state})).length);
 assert.equal(h.sender(s,message('1','9',{direction:'outgoing'})),'You');assert.equal(h.status(message('1','9',{state:'sent',android_read:1})),'Sent');
 emit(s,message('1','9',{state:'failed'}));assert.equal(h.messages(t).length,1);assert.equal(h.messages(t)[0].state,'failed');
});
test('disconnect and daemon restart discard stale bodies and cursor',()=>{
 const s=h.create();emit(s,message());h.load(s,'phone','9','p');h.receive(s,{event:'device_offline',device:'phone'});
 const t=h.threads(s,'phone')[0];assert.ok(t.stale);assert.equal(h.messages(t).length,0);assert.equal(h.load(s,'phone','9','q'),null);
 emit(s,message());assert.equal(h.messages(t).length,1);assert.ok(!t.stale);
 h.receive(s,{event:'worker_stopped'});assert.ok(t.stale);assert.equal(t.pending,'');
});
test('fresh worker reset clears old classifications and head before new-session evidence',()=>{
 const s=h.create();emit(s,message('1','9',{addresses:['5550100','5550101'],reply_status:'group'}));
 const t=s.threads[h.key('phone','9')];assert.equal(t.replyStatus,'group');
 h.receive(s,{event:'worker_stopped'});assert.equal(t.replyStatus,'unknown');assert.equal(t.token,'');assert.equal(t.head,null);
 h.receive(s,{event:'message',message:message('2','9',{addresses:['5550100']}),reply_status:'individual',conversation_token:'fresh:1'});
 assert.equal(t.replyStatus,'individual');assert.equal(t.token,'fresh:1');assert.ok(t.head);
});
test('empty unavailable and removed threads',()=>{
 const s=h.create();h.receive(s,{event:'threads_refreshed',device:'phone'});assert.ok(s.loaded.phone);assert.equal(h.threads(s,'phone').length,0);
 emit(s,message());h.load(s,'phone','9','p');h.receive(s,{event:'error',request_id:'p',error:'Unavailable'});assert.equal(h.threads(s,'phone')[0].status,'Unavailable');
 h.receive(s,{event:'thread_removed',device:'phone',thread:'9'});assert.equal(h.threads(s,'phone').length,0);
});
test('bounded long history retains newly loaded older messages',()=>{
 const s=h.create();for(let i=1000;i>=1;i--)emit(s,message(String(i)));
 const t=h.threads(s,'phone')[0];assert.equal(h.messages(t).length,h.MAX_MESSAGES);assert.ok(t.messages['1']);assert.equal(t.head.message_id,'1000');assert.ok(t.bounded);
 for(let i=0;i<250;i++)emit(s,message('1',String(i)));assert.equal(h.threads(s,'phone').length,h.MAX_THREADS);
});
test('64-bit identity ordering and descriptors remain distinct',()=>{
 const s=h.create();for(const id of ['9007199254740992','9007199254740993'])emit(s,message(id,'9',{timestamp:1,attachments:[{part_id:'7',mime_type:'image/jpeg',thumbnail_base64:'data',identifier:'mms'}]}));
 const rows=h.messages(h.threads(s,'phone')[0]);assert.equal(rows.length,2);assert.equal(rows[0].message_id,'9007199254740993');assert.equal(rows[0].attachments[0].identifier,'mms');assert.equal(rows[0].icon_path,undefined);
});
console.log(`${count} history reducer tests passed`);
