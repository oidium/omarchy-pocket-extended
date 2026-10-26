#!/usr/bin/env python3
"""Synthetic actual-Panel Quickshell checks. Never starts a device worker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

HOOK = r'''
  property var regressionCommands: []
  function regressionFind(item, name) {
    if(item.objectName===name)return item
    var children=item.children||[]
    for(var i=0;i<children.length;i++){var found=regressionFind(children[i],name);if(found)return found}
    return null
  }
  function regression(action, arg) {
    var c=smsEditor,button=regressionFind(c,"contactsButton"),query=regressionFind(c,"contactSearch"),rows=regressionFind(c,"contactRepeater")
    if(action==="seed") {
      var cs=[];for(var i=0;i<120;i++)cs.push({name:(i%2?"Beta ":"Alpha ")+i,numbers:[{number:"555"+i,label:"Mobile"}]})
      messagingEvent({event:"contacts",device:"preview",contacts:cs})
      openComposer("")
    }
    if(action==="contacts")button.clicked()
    if(action==="search")query.text=arg
    if(action==="select")rows.itemAt(0).clicked()
    if(action==="close")closeWorkspace()
    if(action==="new")openComposer("")
    if(action==="collapse")root.close()
    if(action==="reopen")root.open()
    if(action==="thread")openThread("9")
    if(action==="reply")regressionFind(historyView,"replyHistory").clicked()
    if(action==="close-reply")c.closeRequested()
    if(action==="text")regressionFind(c,"smsText").insert(0,arg)
    if(action==="refresh")messagingEvent({event:"threads_refreshed",device:"preview"})
    if(action==="send")composerSend()
    if(action==="wrong-result")messagingEvent({event:"sms_result",device:"preview",request_id:"not-ours",accepted:true})
    if(action==="failure")messagingEvent({event:"sms_result",device:"preview",request_id:smsComposer.pending,accepted:false,uncertain:true,error:"Synthetic uncertainty"})
    if(action==="success")messagingEvent({event:"sms_result",device:"preview",request_id:smsComposer.pending,accepted:true})
    if(action==="remote-volume")messagingEvent({event:"media_state",device:"preview",token:"synthetic-player",revision:Number(arg),media:{player:"Preview player",playerList:["Preview player"],volume:Number(arg)}})
    if(action==="snapshot") {
      remoteMedia={};devices=MediaState.normalizeSnapshot([{id:"preview",name:"N".repeat(1000),online:true,
        links:["L".repeat(1000)],can:["kdeconnect_sms","x".repeat(257)],battery:55,charging:true,
        media:{player:"p".repeat(257),playerList:["p".repeat(257)],title:"T".repeat(1000000),volume:45,
          unknownNested:{secret:"x".repeat(1000000)},playerListExtra:[{private:"metadata"}]},
        unknownDeviceMetadata:{secret:"x".repeat(1000000)} }])
    }
    if(action==="panel-send") {
      regressionCommands=[];devices=[{id:"preview",name:"Preview",online:true,can:["kdeconnect_sms"],links:[],media:{}}]
      selectedId="preview";smsDrafts={};smsComposer=ComposerState.create();historyState=HistoryState.create()
      var addresses=arg==="group"?["5550100","5550101"]:["5550100"]
      messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"1",timestamp:1,
        addresses:addresses,addresses_complete:true,body:"Reply",direction:"incoming",state:"received",attachments:[]},
        conversation_token:"preview:1",reply_status:arg==="group"?"group":arg==="incomplete"?"incomplete":arg==="unknown"?"unknown":"individual"})
      if(arg==="uncertainty") {
        messagingEvent({event:"reply_scope_uncertain",device:"preview"})
        messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:"individual"})
      }
      if(arg==="global-uncertainty") {
        messagingEvent({event:"reply_scope_uncertain",all:true})
        messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:"individual"})
      }
      if(arg==="historical-replay" || arg==="fresh-after-replay" || arg==="ordering-group" || arg==="ordering-incomplete") {
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"1",timestamp:200,addresses:["5550199"],addresses_complete:true,body:"B proof",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:2",reply_status:"individual",recipient_scope:["5550199"]})
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"1",timestamp:100,addresses:["5550100"],addresses_complete:true,body:"historical A",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:3",reply_status:"incomplete",reply_risk:"ordering"})
        if(arg==="fresh-after-replay")messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"1",timestamp:300,addresses:["5550100"],addresses_complete:true,body:"fresh A",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:4",reply_status:"individual",recipient_scope:["5550100"],reply_scope_recovered:true})
      }
      if(arg==="ordering-group" || arg==="ordering-incomplete") {
        messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:arg==="ordering-group"?"group":"incomplete",conversation_token:"preview:4"})
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"3",timestamp:500,addresses:["5550100"],addresses_complete:true,body:"Cannot recover sticky hazard",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:5",reply_status:"individual",recipient_scope:["5550100"],reply_scope_recovered:true})
      }
      if(arg==="evicted-payload")messagingEvent({event:"messages_evicted",device:"preview",thread:"9",ids:["1"]})
      if(arg==="group-event")messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:"group",conversation_token:"preview:2"})
      if(arg==="safety-event")messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:"incomplete",conversation_token:"preview:2"})
      openComposer("9");smsComposer.text="Panel handler regression";saveComposer()
      if(arg==="mismatched-head") {
        smsComposer=ComposerState.create();smsComposer.device="preview";smsComposer.thread="9";smsComposer.text="Stale recipient draft";smsComposer.recipientScope=["5550100"];smsComposer.conversationToken="preview:1"
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"2",timestamp:2,addresses:["5550199"],addresses_complete:true,body:"Changed recipient",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:2",reply_status:"individual"})
        composerSend()
      } else if(arg==="current-scope") {
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"2",timestamp:2,addresses:["5550199"],addresses_complete:true,body:"Current recipient",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:2",reply_status:"individual",recipient_scope:["5550199"]})
        messagingEvent({event:"messages_evicted",device:"preview",thread:"9",ids:["2"]})
        smsComposer=ComposerState.create();smsComposer.device="preview";smsComposer.thread="9";smsComposer.text="Current verified recipient"
        openComposer("9");composerSend()
      } else if(arg==="same-id-rollback") {
        messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:"1",timestamp:0,addresses:["5550199"],addresses_complete:true,body:"Replacement recipient",direction:"incoming",state:"received",attachments:[]},conversation_token:"preview:2",reply_status:"individual",recipient_scope:["5550199"]})
        composerSend()
      } else if(arg==="same-id-rejected-record" || arg==="same-id-rejected-frame") {
        messagingEvent({event:"reply_scope",device:"preview",thread:"9",reply_status:"incomplete",conversation_token:"preview:2"})
        composerSend()
      } else {composerSend();if(arg==="duplicate")composerSend()}
    }
    var first=rows.count?rows.itemAt(0):null
    var browser=regressionFind(c,"contactList")
    var parents=[];for(var p=browser;p&&p!==c;p=p.parent)parents.push({type:String(p),w:p.width,h:p.height,y:p.y,cy:p.contentY,ch:p.contentHeight})
    var editor=regressionFind(c,"smsText"),pt=editor.mapToItem(workspaceScroll,0,0)
    var historyList=regressionFind(historyView,"historyList"),replyButton=regressionFind(historyView,"replyHistory")
    var contactViewport=regressionFind(c,"contactViewport"),instructions=regressionFind(c,"contactInstructions"),recipient=regressionFind(c,"smsRecipient")
    return JSON.stringify({context:workspaceContext,opened:opened,source:c.payload.contacts.length,browse:c.contactsOpen,query:query.text,
      rows:rows.count,first:first?{text:first.text,w:first.width,h:first.height,x:first.mapToItem(workspaceScroll,0,0).x,y:first.mapToItem(workspaceScroll,0,0).y}:null,
      parents:parents,scroll:{y:workspaceScroll.contentY,h:workspaceScroll.height,ch:workspaceScroll.contentHeight},
      editor:{visible:c.visible,y:pt.y,h:editor.height,focus:editor.activeFocus,text:editor.text,recipient:c.payload.recipient,thread:c.payload.thread,token:c.payload.conversationToken,valid:c.contextValid,pending:c.payload.pending},
      composerBox:{y:c.mapToItem(workspaceScroll,0,0).y,h:c.height},
      contactsGeometry:{h:contactViewport.height,w:contactViewport.width,contentHeight:contactViewport.contentHeight,editorY:editor.mapToItem(c,0,0).y,instructionsBottom:instructions.mapToItem(c,0,0).y+instructions.height,recipientY:recipient.mapToItem(c,0,0).y,searchY:query.mapToItem(c,0,0).y},
      volume:volumeControl.shownValue,commands:regressionCommands,
      snapshot:{name:root.phone?root.phone.name:"",media:root.media,can:root.phone?root.phone.can:[],links:root.phone?root.phone.links:[]},
      history:{y:historyView.y,h:historyView.height,implicit:historyView.implicitHeight,listY:historyList.y,listHeight:historyList.height,contentHeight:historyList.contentHeight,replyVisible:replyButton.visible,replyEnabled:replyButton.enabled,loadVisible:regressionFind(historyView,"loadHistory").visible},geometry:JSON.parse(previewInspect("inspect"))})
  }
'''


def run(screen="DP-1"):
    stage = Path(tempfile.mkdtemp(prefix="pocket-runtime-regression-"))
    for name in ("Commons", "Ui"):
        (stage / name).symlink_to(Path("/usr/share/omarchy/shell") / name)
    (stage / "Pocket").mkdir()
    for pattern in ("*.qml", "*.js", "*.py"):
        for src in ROOT.glob(pattern):
            shutil.copy2(src, stage / "Pocket" / src.name)
    panel = stage / "Pocket/Panel.qml"
    code=panel.read_text().replace('  function previewInspect(mode)', HOOK+'\n  function previewInspect(mode)')
    # Capture only in this disposable copy. The production function's callers,
    # reducer, request IDs, draft ownership and rendering stay unchanged.
    for name in ('smsCommand','messagingCommand'):
        code=code.replace('  function '+name+'(command) {','  function '+name+'(command) {\n    if(previewMode){regressionCommands.push(command);return}')
    panel.write_text(code)
    # The panel handler path needs an individual synthetic thread; group
    # blocking is exercised separately by the panel-send cases below.
    preview = (ROOT / "tools/Preview.qml").read_text().replace("@PROJECT@",str(ROOT))
    preview = preview.replace('addresses:["5550100","5550200"]', 'addresses:["5550100"]')
    preview = preview.replace('    function exercise(mode:', '    function regression(action: string, arg: string): string {return pocket.regression(action,arg)}\n    function exercise(mode:')
    preview = preview.replace('  PanelWindow {', '  PanelWindow {\n    screen: Quickshell.screens.find(s=>s.name=='+json.dumps(screen)+')',1)
    preview = preview.replace('position: "top"','position: "bottom"').replace('anchors { top: true; left: true; right: true }','anchors { bottom: true; left: true; right: true }')
    (stage / "shell.qml").write_text(preview)
    log = open(stage / "runtime.log","w")
    env=dict(os.environ,QT_QPA_PLATFORM="wayland",QT_QPA_PLATFORMTHEME="",QT_QUICK_BACKEND="software")
    proc=subprocess.Popen(["quickshell","-p",str(stage)],stdout=log,stderr=log,env=env)
    def call(action,arg=""):
        cmd=["quickshell","ipc","-p",str(stage),"call","pocket-extended-preview","regression",action,arg]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        if r.returncode:raise RuntimeError(r.stderr)
        return json.loads(r.stdout)
    try:
        for i in range(40):
            time.sleep(.1)
            try:call("inspect");break
            except Exception:
                if proc.poll() is not None:raise RuntimeError((stage/"runtime.log").read_text())
        results=[]
        for action,arg in [("seed",""),("contacts",""),("contacts",""),("contacts",""),("search","a"),("search","b"),("search","a"),("search",""),("search","No matching contact"),("search","Beta 119"),("search","b"),("select",""),("search","Alpha"),("contacts",""),("contacts",""),("collapse",""),("reopen",""),("search","Beta"),("close",""),("new",""),("search","Beta"),("thread",""),("reply",""),("text","Synthetic unsent reply"),("close-reply",""),("reply",""),("refresh",""),("send",""),("send",""),("wrong-result",""),("failure",""),("send",""),("success",""),("new",""),("remote-volume","25"),("remote-volume","75"),("snapshot",""),("remote-volume","15"),("panel-send","individual"),("panel-send","group"),("panel-send","incomplete"),("panel-send","unknown"),("panel-send","uncertainty"),("panel-send","global-uncertainty"),("panel-send","group-event"),("panel-send","safety-event"),("panel-send","mismatched-head"),("panel-send","current-scope"),("panel-send","duplicate"),("panel-send","same-id-rollback"),("panel-send","same-id-rejected-record"),("panel-send","same-id-rejected-frame"),("panel-send","historical-replay"),("panel-send","fresh-after-replay"),("panel-send","evicted-payload"),("panel-send","ordering-group"),("panel-send","ordering-incomplete")]:
            call(action,arg);time.sleep(.18);state=call("inspect")
            results.append(dict(action=action,arg=arg,**state))
        (stage/"results.json").write_text(json.dumps(results,indent=2))
        print(stage)
        for s in results:
            if s['context']=='new' and s['opened']:
                cg=s['contactsGeometry'];baseline=results[0]['contactsGeometry']
                assert cg['h']==baseline['h'] and cg['editorY']==baseline['editorY'],s
                assert cg['instructionsBottom']<=cg['recipientY']<cg['searchY'],s
            if s['browse']:
                expected=0 if s['query']=='No matching contact' else 1 if s['query']=='Beta 119' else 60 if s['query'].lower() in ('b','beta','alpha') else 100
                assert s['rows']==expected,s
                if expected:
                    assert s['first']['w']>100 and s['first']['h']>10,s
                    assert 3*s['first']['h']<=s['contactsGeometry']['h']<=4.5*s['first']['h'],s
                if expected>4:assert s['contactsGeometry']['contentHeight']>s['contactsGeometry']['h'],s
                viewport=next(p for p in s['parents'] if 'contactViewport' in p['type'])
                assert viewport['h']>0 and viewport['w']>100,s
            if s['action'] in ('reply','text','refresh'):
                assert s['editor']['focus'] and s['editor']['valid'],s
                assert 0<=s['editor']['y'] and s['editor']['y']+s['editor']['h']<=s['scroll']['h'],s
                assert s['editor']['thread']=='9' and s['editor']['token']=='preview:9',s
                assert not s['history']['replyVisible'] and s['history']['loadVisible'],s
                assert 0 < s['history']['h'] < s['scroll']['h'],s
                assert s['history']['contentHeight'] > s['history']['listHeight'] > 0,s
                assert s['composerBox']['y'] >= 0 and abs(s['composerBox']['y']+s['composerBox']['h']-s['scroll']['h']) < 1,s
                assert s['scroll']['y']==0,s
            if s['action'] in ('thread','close-reply'):
                assert not s['editor']['visible'] and s['history']['replyVisible'],s
                assert s['history']['h']==s['scroll']['h'],s
            if s['action'] in ('close-reply','refresh'):
                assert s['editor']['text']=='Synthetic unsent reply',s
            if s['action'] in ('wrong-result','failure'):
                assert s['editor']['text']=='Synthetic unsent reply',s
            if s['action']=='success':assert s['editor']['text']=='',s
            if s['action']=='remote-volume':assert s['volume']==int(s['arg']),s
            if s['action']=='snapshot':
                snap=s['snapshot'];assert snap['name'].startswith('N') and len(snap['name'])==256,s
                assert snap['media']['player']=='' and snap['media']['playerList']==[],s
                assert len(snap['media']['title'])==512 and 'unknownNested' not in snap['media'],s
                assert snap['can']==[] and len(snap['links'][0])==128,s
            g=s['geometry'];assert g['workspaceHeight']==g['height'] and g['workspaceY']==g['originY'],g
        sends=[c for c in next(s for s in results if s['action']=='success')['commands'] if c['op'].startswith('sms_')]
        assert len(sends)==2 and all(c['op']=='sms_reply' and c['thread']=='9' and c['conversation_token']=='preview:9' for c in sends),sends
        assert next(s for s in results if s['action']=='reopen')['context']=='new'
        panel_sends=[s for s in results if s['action']=='panel-send']
        assert len(panel_sends)==19
        assert [c['op'] for c in panel_sends[0]['commands'] if c['op'].startswith('sms_')]==['sms_reply'],panel_sends[0]
        assert not any(c['op'].startswith('sms_') for s in panel_sends[1:9] for c in s['commands']),panel_sends[1:9]
        current=[c for c in panel_sends[9]['commands'] if c['op']=='sms_reply']
        assert len(current)==1 and current[0]['recipient_scope']==['5550199'],panel_sends[9]
        duplicate=[c for c in panel_sends[10]['commands'] if c['op']=='sms_reply']
        assert len(duplicate)==1,panel_sends[10]
        assert not any(c['op'].startswith('sms_') for s in panel_sends[11:15] for c in s['commands']),panel_sends[11:15]
        assert not any(c['op'].startswith('sms_') for c in panel_sends[14]['commands']) and not panel_sends[14]['editor']['valid'],panel_sends[14]
        fresh=[c for c in panel_sends[15]['commands'] if c['op']=='sms_reply']
        assert len(fresh)==1 and fresh[0]['recipient_scope']==['5550100'] and panel_sends[15]['editor']['valid'],panel_sends[15]
        evicted=[c for c in panel_sends[16]['commands'] if c['op']=='sms_reply']
        assert len(evicted)==1 and evicted[0]['recipient_scope']==['5550100'] and panel_sends[16]['editor']['valid'],panel_sends[16]
        for blocked in panel_sends[17:]:
            assert not blocked['editor']['valid'] and not blocked['history']['replyEnabled'],blocked
            assert not any(c['op']=='sms_reply' for c in blocked['commands']),blocked
        print('PASS: actual Quickshell Contacts geometry/lifecycle, thread editor visibility/focus/correlation, volume event propagation, aligned stationary geometry on '+screen)
    finally:
        if proc.poll() is None:
            subprocess.run(["quickshell","ipc","-p",str(stage),"call","pocket-extended-preview","quit"],capture_output=True)
            proc.wait(timeout=5)
        log.close()

if __name__=="__main__":
    import sys
    run(sys.argv[1] if len(sys.argv)>1 else "DP-1")
