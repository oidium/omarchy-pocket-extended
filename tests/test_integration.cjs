const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
function moduleFile(file){const x={};vm.createContext(x);vm.runInContext(fs.readFileSync(file,'utf8'),x);return x}
const c=moduleFile('ComposerState.js'),n=moduleFile('NotificationState.js'),h=moduleFile('HistoryState.js');
let count=0;function test(name,fn){fn();count++;console.log('ok',name)}
test('draft limit preserves unsent content and only reclaims empty slots',()=>{
 assert.equal(c.limitText('a🙂',2),'a');assert.equal(c.limitText('a🙂',3),'a🙂');
 const d={};for(let i=0;i<32;i++){d[i]=c.create();d[i].text='Keep '+i}
 assert.equal(c.reserve(d,'new'),false);assert.equal(Object.keys(d).length,32);assert.equal(d[0].text,'Keep 0');
 d[0].text='';assert.equal(c.reserve(d,'new'),true);assert.equal(d[0],undefined);
});
test('notification churn caps cards but keeps open draft',()=>{
 const cards={};function event(id){return {event:'notification',notification:{device:'d',id:String(id),reply_id:'token',internal_id:'internal',title:'Name'}}}
 n.receive(cards,event(0));const first=cards[n.key('d','0')];n.begin(first);first.draft='Keep';
 for(let i=1;i<1000;i++)n.receive(cards,event(i));assert.equal(Object.keys(cards).length,128);assert.equal(first.draft,'Keep');assert.equal(cards[n.key('d','0')],first);
});
test('contacts search and cache maps remain bounded',()=>{
 const contacts=Array.from({length:1000},(_,i)=>({name:'Person'+i,numbers:[{number:String(i),label:'Mobile'}]}));
 assert.equal(c.contactChoices(contacts,'').length,100);assert.equal(c.contactChoices(contacts,'Person999').length,1);
 const state=h.create();for(let i=0;i<100;i++)h.receive(state,{event:'contacts',device:String(i),contacts});assert.equal(Object.keys(state.contacts).length,16);
});
test('composer commands carry thread token and never notification reply',()=>{
 const draft=c.create();draft.thread='9';draft.conversationToken='worker:1';draft.recipientScope=['5550100'];draft.text='Keep 👋';
 const cmd=c.send(draft,'d','r','individual');assert.equal(cmd.conversation_token,'worker:1');assert.equal(cmd.op,'sms_reply');
 c.receive(draft,{event:'worker_stopped'});assert.equal(draft.text,'Keep 👋');assert.equal(draft.conversationToken,'worker:1');
});
console.log(`${count} integration reducer tests passed`);
