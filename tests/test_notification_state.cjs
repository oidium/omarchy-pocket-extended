const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const state = vm.createContext({}); vm.runInContext(fs.readFileSync('NotificationState.js', 'utf8'), state);
function note(extra={}) { return {device:'phone',id:'1',occurrence_id:'occ-1',notification_epoch:'worker-1',internal_id:'android',reply_id:'token',title:'Example',app:'Chat',body:'Hello',dismissable:true,...extra}; }
let passed=0;
function test(name, fn) { fn(); passed++; console.log('PASS '+name); }
function opened() { const cards={}; state.receive(cards,{event:'notification',notification:note()}); const c=cards[state.key('phone','1')];state.begin(c);c.draft='Hi 👋';return {cards,c}; }
test('ordinary refresh preserves draft and reply target',()=>{const {cards,c}=opened();state.receive(cards,{event:'notification',notification:note({body:'Updated'})});assert.equal(c.draft,'Hi 👋');assert.equal(c.draftReply,'token');assert.equal(c.unavailable,false);});
test('replacement blocks old draft instead of redirecting',()=>{const {cards,c}=opened();state.receive(cards,{event:'notification',notification:note({reply_id:'new',occurrence_id:'occ-2'})});assert.equal(c.draft,'Hi 👋');assert.equal(c.status,'Reply no longer available');assert.equal(state.replyCommand(c,'x'),null);});
test('removed editor survives',()=>{const {cards,c}=opened();state.receive(cards,{event:'notification_removed',device:'phone',id:'1'});assert.equal(c.active,false);assert.equal(c.draft,'Hi 👋');assert.equal(state.replyCommand(c,'x'),null);assert.ok(cards[c.key]);});
test('removed card without draft/editor can disappear',()=>{let cards={};state.receive(cards,{event:'notification',notification:note()});state.receive(cards,{event:'notification_removed',device:'phone',id:'1'});assert.equal(Object.keys(cards).length,0);});
test('worker loss preserves draft',()=>{const {cards,c}=opened();state.replyCommand(c,'x');state.receive(cards,{event:'worker_stopped'});assert.equal(c.draft,'Hi 👋');assert.equal(c.pending,'');assert.equal(state.replyCommand(c,'y'),null);});
test('same id on another device never receives draft',()=>{const {cards,c}=opened();state.receive(cards,{event:'notification',notification:note({device:'other'})});assert.equal(cards[state.key('other','1')].draft,'');assert.equal(c.draft,'Hi 👋');});
test('service capability updates do not infer stale state from absent editor drafts',()=>{
 const cards={};state.receive(cards,{event:'notification',notification:note()},'',true);
 const c=cards[state.key('phone','1')];c.pending='service-request';
 state.receive(cards,{event:'notification',notification:note({body:'Repeated update'})},'',true);
 assert.equal(c.unavailable,false);assert.equal(c.pending,'service-request');
 state.receive(cards,{event:'notification',notification:note({internal_id:'new-android',reply_id:'new-token',occurrence_id:'occ-2'})},'',true);
 assert.equal(c.unavailable,false);assert.equal(c.note.reply_id,'new-token');
 const local={};state.receive(local,{event:'notification',notification:note()});
 const draft=local[state.key('phone','1')];state.begin(draft);draft.draft='Review this';
 state.receive(local,{event:'notification',notification:note({reply_id:'new-token',occurrence_id:'occ-2'})});
 assert.equal(draft.unavailable,true);assert.equal(draft.draft,'Review this');
});
test('accepted reply clears only matching request draft and reports KDE Connect submission',()=>{const {cards,c}=opened();const cmd=state.replyCommand(c,'x');assert.equal(cmd.op,'notification_reply');assert.equal(cmd.occurrence_id,'occ-1');assert.equal(cmd.notification_epoch,'worker-1');const pending={event:'notification_action_pending',device:'phone',id:'1',internal_id:'android',request_id:'x',owner_id:'left'};state.receive(cards,pending,'left');state.receive(cards,{event:'notification_action_result',request_id:'wrong',accepted:true,action:'notification_reply',owner_id:'left'},'left');assert.equal(c.draft,'Hi 👋');state.receive(cards,{event:'notification_action_result',request_id:'x',accepted:true,action:'notification_reply',owner_id:'left',reply_id:'token'},'left');assert.equal(c.draft,'');assert.equal(c.status,'Submitted to KDE Connect');assert.equal(state.canReply(c),false);});
test('failure keeps draft and releases pending',()=>{const {cards,c}=opened();state.replyCommand(c,'x');state.receive(cards,{event:'notification_action_pending',device:'phone',id:'1',internal_id:'android',request_id:'x',owner_id:'left'},'left');state.receive(cards,{event:'notification_action_result',request_id:'x',accepted:false,error:'Reply no longer available',owner_id:'left'},'left');assert.equal(c.draft,'Hi 👋');assert.equal(c.pending,'');assert.equal(c.unavailable,true);});
test('dismiss does not discard reply draft',()=>{const {cards,c}=opened();state.dismissCommand(c,'x');state.receive(cards,{event:'notification_action_pending',device:'phone',id:'1',internal_id:'android',request_id:'x',owner_id:'left'},'left');state.receive(cards,{event:'notification_removed',device:'phone',id:'1'});state.receive(cards,{event:'notification_action_result',request_id:'x',accepted:true,action:'notification_dismiss',owner_id:'left'},'left');assert.equal(c.draft,'Hi 👋');assert.equal(c.active,false);assert.match(c.status,/Connection changed|Reply no longer available/);});
test('capability gates and empty editor',()=>{const {c}=opened();c.note.dismissable=false;assert.equal(state.dismissCommand(c,'x'),null);c.draft=' ';assert.equal(state.replyCommand(c,'x'),null);c.note.reply_id='';assert.equal(state.canReply(c),false);});
test('normalized same-identity conversation update retains editor draft',()=>{
 const {cards,c}=opened();c.draft='Unsent 👋';
 const note=Object.assign({},c.note,{body:'Project update\nCasey Example\nSee you soon'});
 state.receive(cards,{event:'notification',notification:note});
 assert.equal(c.draft,'Unsent 👋');assert.equal(c.editing,true);assert.equal(c.note.body,'Project update\nCasey Example\nSee you soon');
});
console.log(`${passed} reducer tests passed`);
