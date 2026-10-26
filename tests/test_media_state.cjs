const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const m={};vm.createContext(m);vm.runInContext(fs.readFileSync('MediaState.js','utf8'),m);
const message={device_id:'d',thread_id:'9',message_id:'1'},a={part_id:'7',identifier:'photo',mime_type:'image/jpeg'};
let count=0;function test(name,run){run();count++;console.log('ok',name)}
test('thumbnail accepts raster base64 only and bounds input',()=>{
 assert.ok(m.thumbnail({thumbnail_base64:'iVBORw0KGgo='}).startsWith('data:image/png;'));
 for(const bad of ['', '<svg/>','https://x', 'AAAA', 'A'.repeat(524292)])assert.equal(m.thumbnail({thumbnail_base64:bad}),'');
});
test('completion full identity and duplicate protection',()=>{
 const s={};m.command(s,message,a,'r',false);
 const e={event:'attachment_ready',request_id:'r',device:'d',thread:'9',message_id:'WRONG',part_id:'7',identifier:'photo',kind:'mms_download'};
 m.receive(s,e);assert.equal(s[m.key(message,a)].status,'loading');e.message_id='1';m.receive(s,e);assert.equal(s[m.key(message,a)].status,'downloaded');
 m.receive(s,{event:'error',request_id:'r',error:'late'});assert.equal(s[m.key(message,a)].status,'downloaded');
 assert.equal(m.command(s,message,a,'open',true).op,'attachment_open');
});
test('no thumbnail audio, malformed and open before download',()=>{
 const s={};assert.equal(m.thumbnail(a),'');assert.equal(m.command(s,message,a,'o',true),null);
 assert.equal(m.command(s,message,{part_id:'7',identifier:'../x'},'r',false),null);
});
test('multiple messages/threads and reconnect cleanup',()=>{
 const s={};m.command(s,message,a,'a',false);m.command(s,{...message,thread_id:'10'},a,'b',false);
 assert.equal(Object.keys(s).length,2);m.receive(s,{event:'device_offline',device:'d'});assert.equal(Object.keys(s).length,0);
 m.command(s,message,a,'c',false);m.receive(s,{event:'worker_stopped'});assert.equal(Object.keys(s).length,0);
});
test('errors permit retry and history pruning bounds media state',()=>{
 const s={};m.command(s,message,a,'r',false);m.receive(s,{event:'error',request_id:'r',error:'Timeout'});
 assert.equal(s[m.key(message,a)].error,'Timeout');assert.ok(m.command(s,message,a,'r2',false));
 m.prune(s,{threads:{}});assert.equal(Object.keys(s).length,0);
 for(let i=0;i<500;i++)m.command(s,{...message,message_id:String(i)},a,String(i),false);
 assert.equal(Object.keys(s).length,300);
});
test('snapshot normalization strips nested metadata and disables inexact media actions',()=>{
 const d=m.normalizeSnapshot([{id:'phone',name:'N'.repeat(1000),online:true,links:['L'.repeat(1000)],
   can:['kdeconnect_sms','x'.repeat(129)],battery:55,charging:true,
   media:{player:'p'.repeat(257),playerList:['p'.repeat(257)],title:'T'.repeat(2000),volume:45,unknown:{secret:'x'.repeat(1000000)},length:'long'},
   notifications:[{secret:'private'}],unknown:{secret:'private'}}])[0];
 assert.equal(d.name.length,256);assert.equal(d.links[0].length,128);assert.deepEqual(Array.from(d.can),[]);
 assert.equal(d.media.player,'');assert.deepEqual(Array.from(d.media.playerList),[]);assert.equal(d.media.title.length,512);
 assert.equal(d.media.volume,45);assert.equal(d.media.unknown,undefined);assert.equal(d.unknown,undefined);assert.deepEqual(Array.from(d.notifications),[]);
 assert.ok(JSON.stringify(d).length<3000);
});
console.log(`${count} media reducer tests passed`);
