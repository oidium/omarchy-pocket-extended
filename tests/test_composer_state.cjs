const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const c = vm.createContext({}); vm.runInContext(fs.readFileSync('ComposerState.js','utf8'), c);
let pass = 0; function test(name, fn) { fn(); pass++; console.log("PASS "+name); }
test("shared contact success resolves every panel request for the same device", () => {
  const x=c.create();x.device="phone";x.contactsRequest="request-right";x.contactsLoading=true;
  c.receive(x,{event:"contacts",device:"phone",request_id:"request-left",contacts:[{name:"Alex",numbers:[]}],error:""});
  assert.equal(x.contactsLoading,false);assert.equal(x.contactsRequest,"");
  assert.equal(x.contacts[0].name,"Alex");
});
test("contacts loading failures are distinct and preserve recipient authorization state", () => {
  const x=c.create();x.device="phone";x.recipient="5550100";x.text="Keep this draft";
  x.contactsRequest="contacts-1";x.contactsLoading=true;
  c.receive(x,{event:"error",device:"phone",request_id:"old",error:"late failure"});
  assert.equal(x.contactsLoading,true);assert.equal(x.contactsError,"");
  c.receive(x,{event:"contacts",device:"phone",request_id:"contacts-1",available:false,contacts:[],error:"Read failed"});
  assert.equal(x.contactsLoading,false);assert.equal(x.contactsError,"Read failed");
  assert.deepEqual(x.contacts,[]);assert.equal(x.recipient,"5550100");assert.equal(x.text,"Keep this draft");
  x.contactsRequest="contacts-2";x.contactsLoading=true;
  c.receive(x,{event:"contacts",device:"phone",request_id:"contacts-2",available:true,contacts:[],error:""});
  assert.equal(x.contactsError,"");assert.equal(x.contactsLoading,false);
});
test('manual recipient and Unicode send stay SMS-only', () => {
  const x=c.create(); x.recipient='+1 555 0100'; x.text='Hello 👋';
  const cmd=c.send(x,'phone','sms-1'); assert.equal(cmd.op,'sms_send'); assert.equal(cmd.recipient,x.recipient); assert.equal(cmd.text,'Hello 👋'); assert.equal(cmd.device,'phone');
});
test('contacts return every matching number', () => {
  const x=c.create(); x.contacts=[{name:'Ana Example',numbers:[{number:'5550100',label:'Cell'},{number:'5550198',label:'Work'}]}];
  assert.equal(c.contactChoices(x.contacts,'ana').length,2); assert.equal(c.contactChoices(x.contacts,'0198')[0].label,'Work');
});
test('name tiers and alphabetical ties ignore source order and case',()=>{
 const contacts=['Jordan Sample','Jack Sample','Jake Sample','Kendall Example','Kay Sample','Adam Kline','Alex King','Zack Sample'].map(name=>({name,numbers:[{number:'5550100',label:'Mobile'}]}));
 const names=q=>Array.from(c.contactChoices(contacts,q),x=>x.name);
 assert.deepEqual(names(' K '),['Kay Sample','Kendall Example','Adam Kline','Alex King','Jack Sample','Jake Sample','Zack Sample']);
 assert.deepEqual(names('k'),names('K'));
 assert.deepEqual(names('Jo'),['Jordan Sample']);
 assert.deepEqual(Array.from(c.contactChoices(contacts.slice().reverse(),'k'),x=>x.name),names('k'));
 assert.deepEqual(names(''),['Adam Kline','Alex King','Jack Sample','Jake Sample','Jordan Sample','Kay Sample','Kendall Example','Zack Sample']);
});
test('name search excludes phone labels and unrelated contact metadata',()=>{
 const contacts=[{name:'Zoë 世界',notes:'Kendall',vcard:'Jordan',numbers:[{number:'5550100',label:'Kendall Work'}]}];
 assert.equal(c.contactChoices(contacts,'kendall').length,0);
 assert.equal(c.contactChoices(contacts,'jordan').length,0);
 assert.equal(c.contactChoices(contacts,'ZOË')[0].name,'Zoë 世界');
 assert.equal(c.contactChoices(contacts,'世界').length,1);
});
test('telephone searches normalize punctuation and NANP equivalence',()=>{
 const contacts=[{name:'Local',numbers:[{number:'(202) 555-0147',label:'Mobile'}]},{name:'International form',numbers:[{number:'+12025550147',label:'Work'}]},{name:'Different NANP area',numbers:[{number:'+1 303-555-0147',label:'Mobile'}]},{name:'Fictional UK mobile',numbers:[{number:'+44 7700 900123',label:'Mobile'}]}];
 for(const q of ['+1 202-555-0147','12025550147','(202) 555-0147','2025550147'])
   assert.deepEqual(Array.from(c.contactChoices(contacts,q).slice(0,2),x=>x.name),['International form','Local']);
 assert.equal(c.contactChoices(contacts,'0147').length,3);
 assert.equal(c.contactChoices(contacts,'+13035550147')[0].name,'Different NANP area');
 assert.deepEqual(Array.from(c.contactChoices(contacts,'+447700900123'),x=>x.name),['Fictional UK mobile']);
});
test('rank before result cap and repeated searches preserve complete source',()=>{
 const contacts=Array.from({length:110},(_,i)=>({name:'Weak '+i,numbers:[{number:'555'+i,label:'Mobile'}]}));
 contacts.push({name:'Kendall Example',numbers:[{number:'123456',label:'Mobile'}]});
 const before=JSON.stringify(contacts);
 for(const q of ['k','weak','k','','k']) {
   const result=c.contactChoices(contacts,q);assert.equal(result.length,100);
   if(q==='k')assert.equal(result[0].name,'Kendall Example');
 }
 assert.equal(JSON.stringify(contacts),before);
});
test('emoji/file actions do not clear text draft', () => {
  const x=c.create(); x.text='draft'; x.files=[{path:'/tmp/p',name:'p',size:1}];
  c.receive(x,{event:'files_selected',request_id:'pick',cancelled:true,files:[]}); assert.equal(x.text,'draft');
  x.pickerRequest='pick'; c.receive(x,{event:'files_selected',request_id:'pick',cancelled:false,files:[{path:'/tmp/a',name:'a',size:2}]}); assert.equal(x.files.length,2); assert.equal(x.text,'draft');
});
test('worker loss clears pending picker ownership and reports uncertainty',()=>{
 const x=c.create();x.device='phone';x.text='Preserved file draft';x.pickerRequest='pick-1';
 c.receive(x,{event:'worker_stopped'});
 assert.equal(x.text,'Preserved file draft');assert.equal(x.pickerRequest,'');
 assert.match(x.status,/Check the phone and file selection/);
});
test('offline/send failure keeps draft', () => {
  const x=c.create(); x.recipient='5550100'; x.text='draft'; c.send(x,'phone','sms-1');
  c.receive(x,{event:'sms_result',request_id:'sms-1',accepted:false,error:'Phone is offline. Your draft is saved.'}); assert.equal(x.text,'draft'); assert.equal(x.status,'Phone is offline. Your draft is saved.');
});
test('conversation reply remains thread targeted after failure', () => {
  const x=c.create();x.thread='9007199254740993';x.text='Individual 👋';
  x.recipientScope=['5550100'];
  const cmd=c.send(x,'phone','r','individual');assert.equal(cmd.op,'sms_reply');assert.equal(cmd.thread,x.thread);assert.deepEqual(cmd.recipient_scope,x.recipientScope);
  c.receive(x,{event:'sms_result',request_id:'r',accepted:false,error:'Unavailable'});
  assert.equal(x.thread,'9007199254740993');assert.equal(x.text,'Individual 👋');assert.equal(c.send(x,'phone','r2','individual').op,'sms_reply');
});
test('group reply is blocked before command creation', () => {
  const x=c.create();x.thread='9';x.text='No group send';x.recipientScope=['5550100','5550101'];
  assert.equal(c.send(x,'phone','group'),null);
  x.recipientScope=[];assert.equal(c.send(x,'phone','incomplete'),null);
});
test('device/thread drafts retain distinct text and response ownership', () => {
  const a=c.create(),b=c.create();a.device='one';a.thread='9';a.recipientScope=['5550100'];a.text='First';b.device='two';b.thread='9';b.recipientScope=['5550101'];b.text='Second';
  c.send(a,'one','a','individual');c.send(b,'two','b','individual');
  const event={event:'sms_result',device:'one',request_id:'a',accepted:true};c.receive(a,event);c.receive(b,event);
  assert.equal(a.text,'');assert.equal(b.text,'Second');assert.equal(b.pending,'b');
  c.receive(b,{event:'contacts',device:'one',contacts:[{name:'Wrong',numbers:[]}]});assert.equal(b.contacts.length,0);
});
test('manual acceptance clears complete draft and transient status',()=>{
 const x=c.create();Object.assign(x,{device:'phone',open:true,recipient:'5550100',text:'Hi',files:[{path:'/tmp/a'}]});c.send(x,'phone','r');
 assert.equal(x.open,true);c.receive(x,{event:'sms_result',device:'phone',request_id:'wrong',accepted:true});assert.equal(x.text,'Hi');
 c.receive(x,{event:'sms_result',device:'phone',request_id:'r',accepted:true});assert.equal(x.open,false);assert.equal(x.recipient,'');assert.equal(x.status,'Submitted to KDE Connect');assert.equal(x.files.length,0);
});
test('uncertain result preserves complete manual draft',()=>{
 const x=c.create();Object.assign(x,{open:true,recipient:'5550100',text:'Keep',files:[{path:'/tmp/a'}]});c.send(x,'phone','r');
 c.receive(x,{event:'sms_result',request_id:'r',accepted:false,uncertain:true,error:'Check phone'});
 assert.equal(x.open,true);assert.equal(x.text,'Keep');assert.equal(x.recipient,'5550100');assert.equal(x.files.length,1);
});
console.log(`${pass} composer tests passed`);
