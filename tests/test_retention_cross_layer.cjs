const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const vm = require('node:vm');

const python = String.raw`
import json
from messaging import Message, Store

events = []
store = Store(events.append)
def wire(uid, body):
    return (1, body, [('5550100',)], 100, 1, 0, 9, uid, -1, [])

first = Message.decode('phone', wire(1, 'old'))
second = Message.decode('phone', wire(2, 'new'))
replacement = Message.decode('phone', wire(1, 'replacement' * 30))
store.MAX_RETAINED_BYTES = replacement.serialized_size() + second.serialized_size() - 1
store.ingest('phone', wire(1, 'old'))
store.ingest('phone', wire(2, 'new'))
initial = list(events)
events.clear()
store.ingest('phone', wire(1, 'replacement' * 30))
events.clear()
store2 = Store(events.append)
store2.ingest('phone', wire(1, 'old'))
store2.ingest('phone', (1, 'f' * 1000, [('5550100',)], 100, 1, 0, 10, 1, -1, []))
group = (1, 'g' * 800, [('5550100',), ('5550199',)], 100, 1, 0, 9, 1, -1, [])
group_size = Message.decode('phone', group).serialized_size()
filler_size = store2.threads[('phone', '10')].messages['1'].serialized_size()
store2.MAX_RETAINED_BYTES = group_size + filler_size - 1
events.clear()
store2.ingest('phone', group)
print(json.dumps({'initial': initial, 'update': events,
                  'retained': sorted(store.conversation('phone', '9').messages),
                  'self_eviction': events,
                  'individual': initial}))
`;

const run = spawnSync('python3', ['-c', python], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
assert.equal(run.status, 0, run.stderr);
const result = JSON.parse(run.stdout);
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync('HistoryState.js', 'utf8'), context);
const state = context.create();
for (const event of result.initial) context.receive(state, event);
for (const event of result.update) context.receive(state, event);
const thread = state.threads[context.key('phone', '9')];
assert.deepEqual(Object.keys(thread.messages).sort(), result.retained);
assert.equal(thread.messages['1'], undefined, 'worker-evicted replacement must not return to QML');
console.log('ok worker replacement self-eviction stays synchronized with actual HistoryState reducer');
const safety = context.create();
for (const event of result.initial.filter(event => event.event === 'message')) context.receive(safety, event);
for (const event of result.self_eviction) context.receive(safety, event);
const selfEvicted = safety.threads[context.key('phone', '9')];
assert.equal(selfEvicted.replyStatus, 'group', 'group self-eviction must update retained UI safety state');
assert.ok(context.summary(selfEvicted).replyBlocked);
console.log('ok group self-eviction safety event reaches HistoryState without a retained message');

// Exercise backend-generated recovery/hazard events through both the reducer
// and the exact production Panel Send handler, including complete-event rejection.
const riskRun = spawnSync('python3', ['-c', String.raw`
import json
from messaging import Store, Message, json_line_size
def wire(uid=1, ts=100, addresses=('5550100',)):
    return [1,'Synthetic',[(a,) for a in addresses],ts,1,0,9,uid,-1,[]]
cases={}
for hazard, addresses in [('group',('5550100','5550199')),('incomplete',())]:
    for path in ['accepted','record','event']:
        events=[];s=Store(events.append)
        for r in [wire(),wire(ts=200,addresses=('5550199',)),wire()]:s.ingest('phone',r)
        r=wire(2,300,addresses)
        if path=='record':r[1]=None
        if path=='event':
            r[1]='';r[9]=[(i,'\x01'*256,'A'*(196608 if i<2 else 110000 if i==2 else 0),'\x01'*512) for i in range(16)]
            def frame():return dict(event='message',message=Message.decode('phone',r).json(),conversation_token=s.session+':'+str(s.sequence+1),source='summary',reply_status=hazard,delivery_confirmed=None,read_receipt=None)
            delta=614401-json_line_size(frame());r[1]='\x01'*(delta//6)+'x'*(delta%6)
            assert json_line_size(frame())==614401 and Message.decode('phone',r).serialized_size()<=614400
        try:s.ingest('phone',r);assert path=='accepted'
        except ValueError:assert path!='accepted'
        for ts in [400,500,50]:s.ingest('phone',wire(ts=ts))
        assert s.reply_status('phone','9')==hazard
        cases[hazard+'-'+path]=dict(events=events,status=hazard,commands=0)
events=[];s=Store(events.append)
for r in [wire(),wire(ts=200,addresses=('5550199',)),wire(),wire(ts=400)]:s.ingest('phone',r)
cases['ordering-only']=dict(events=events,status='individual',commands=1)
print(json.dumps(cases))
`], { encoding:'utf8', env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'} });
assert.equal(riskRun.status,0,riskRun.stderr);
const composer={};vm.createContext(composer);vm.runInContext(fs.readFileSync('ComposerState.js','utf8'),composer);
const panel=fs.readFileSync('Panel.qml','utf8');
const handler=panel.slice(panel.indexOf('  function composerSend()'),panel.indexOf('  function composerAttach()'));
for(const [name,fixture] of Object.entries(JSON.parse(riskRun.stdout))){
 const state=context.create();fixture.events.forEach(e=>context.receive(state,e));
 const t=state.threads[context.key('phone','9')];assert.equal(t.replyStatus,fixture.status,name);
 const draft=composer.create();Object.assign(draft,{device:'phone',thread:'9',text:'Synthetic',conversationToken:t.token,recipientScope:Array.from(t.replyScope||[])});
 const sent=[],ctx={HistoryState:context,ComposerState:composer,historyState:state,phone:{id:'phone'},smsComposer:draft,smsSequence:0,newRequestId(prefix){return prefix+'-1'},saveComposer(){},smsCommand(c){sent.push(c)}};
 vm.createContext(ctx);vm.runInContext(handler,ctx);ctx.composerSend();ctx.composerSend();
 assert.equal(sent.length,fixture.commands,name);
}
console.log('ok generated ordering/hazard transitions reach actual reducer and production Panel Send');
