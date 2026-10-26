"""Synthetic Quickshell integration tests for the production V6 components.

The fixture copies the production QML/JS into a temporary plugin tree, adds
observation-only methods to the copied Panel, and substitutes a recording
worker and bridge. It never connects to KDE Connect or sends a phone action.
"""

import json
import signal
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OMARCHY = Path("/usr/share/omarchy/shell")
R1_PRODUCTION_TESTS = frozenset({
    "test_r1_reused_capabilities_keep_original_proof_across_panel_recreation",
    "test_r1_worker_epoch_and_absent_panel_reuse_cannot_rebind_drafts",
    "test_r1_same_occurrence_restoration_stays_sendable_and_dispatches_once",
})


SHELL_QML = r'''import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Pocket" as Pocket
ShellRoot {
 id: fixture
 property var owner: null
 property var commandEvents: []
 property var readyPids: []
 property var oldNote: null
 property string oldRemoveRequest: ""
 property string oldRemoveEpoch: ""
 property string capacityObserved: ""
 property var stateErrorObserved: []
 property var lastDeviceEvent: ({})
 property int churnCompleted: 0
 property string churnError: ""
 property bool startService: true
 Component { id: serviceComponent; Pocket.Service {} }
 Timer { id: serviceRecreate; interval:50; repeat:false; onTriggered:fixture.owner=serviceComponent.createObject(fixture) }
 Component.onCompleted: if(fixture.startService) owner=serviceComponent.createObject(fixture)
 QtObject { id: api; property bool connected:true; function serviceFor(id){return connected?fixture.owner:null} }
 QtObject {
   id: mockBar
   property var shell:api
   property string position:"top"
   property bool vertical:false
   property int barSize:40
   property string fontFamily:Style.font.family
   property color barForeground:Color.foreground
   property color urgent:Color.urgent
   property color foreground:Color.foreground
   property color background:Color.background
   property bool foregroundAnimationEnabled:false
   property var activePopout:null
   function showTooltip(i,t){} function hideTooltip(i){}
   function requestPopout(i){activePopout=i}
   function releasePopout(i){if(activePopout===i)activePopout=null}
 }
 Component {id: panelComponent;Pocket.Panel{bar:mockBar}}
 Item { Loader{id:left;active:true;sourceComponent:panelComponent;onLoaded:item.panelDraftSlotOverride="fixture-left"}
        Loader{id:right;active:true;sourceComponent:panelComponent;onLoaded:item.panelDraftSlotOverride="fixture-right"} }
 Connections { target:fixture.owner
   function onEventReceived(e){
     if(e.event==="audit_command")fixture.commandEvents=fixture.commandEvents.concat([e.command])
     if(e.event==="device")fixture.lastDeviceEvent=e.device
     if(e.event==="ready")fixture.readyPids=fixture.readyPids.concat([e.audit_pid])
   }
 }
 function state(){return {sameService:!!left.item&&!!right.item&&left.item.service===right.item.service,
   serviceOccurrences:owner?Object.assign({},owner.notificationOccurrences):{},serviceRemovals:owner?Object.assign({},owner.localNotificationRemovals):{},
   churnCompleted:churnCompleted,churnError:churnError,lastDeviceEvent:lastDeviceEvent,
   left:left.item?left.item.auditState():null,right:right.item?right.item.auditState():null,
   deviceCount:owner?owner.devices.length:0,loaded:owner?owner.loaded:false,occurrenceCount:owner?Object.keys(owner.notificationOccurrences).length:0,revisionWatermark:owner?owner.notificationRevisionWatermark:0,stateError:owner?owner.notificationStateError:"",capacityObserved:capacityObserved,stateErrorObserved:stateErrorObserved,localRequests:owner?Object.keys(owner.localRemovalRequests):[],
   commands:commandEvents,readyPids:readyPids,serviceReady:owner?owner.messagingReady:false,
   epoch:owner?owner.serviceEpoch:"",workerEpoch:owner?owner.notificationWorkerEpoch:""}}
 function execute(action){
   var key='["fake","n"]'
   if(action.indexOf("eval:")===0){eval(action.slice(5));return state()}
   if(action==="deviceOversize")owner.messagingEvent({event:"device",device:{id:"fake",name:"N".repeat(1048576),name_valid:false,online:true,plugins:["kdeconnect_sms","x".repeat(1048576)],unknown:{secret:"S".repeat(1048576)}}})
   if(action==="seed")owner.messagingCommand({op:"audit_seed",device:"fake",id:"n",internal_id:"n1",reply_id:"reply1",title:"Synthetic contact",app:"Synthetic app",body:"Synthetic note",dismissable:true})
   if(action==="seedEmptyIdentity")owner.messagingCommand({op:"audit_seed",device:"fake",id:"empty",internal_id:"",reply_id:"",title:"Read only",app:"Synthetic",body:"No action capability",dismissable:false})
   if(action==="seedChanged")owner.messagingCommand({op:"audit_seed",device:"fake",id:"n",internal_id:"n2",reply_id:"reply2",title:"Synthetic contact",app:"Synthetic app",body:"Updated note",dismissable:true})
   if(action==="seed2")owner.messagingCommand({op:"audit_seed",device:"fake",id:"n2",internal_id:"n3",reply_id:"reply3",title:"Synthetic contact 2",app:"Synthetic app",body:"Second note",dismissable:true})
   if(action==="removeFromPhone")owner.messagingCommand({op:"audit_close",device:"fake",id:"n"})
   if(action==="clearAll")left.item.auditClearAll()
   if(action==="clearAllRight")right.item.auditClearAll()
   if(action==="removeInactive")left.item.auditRemoveInactive()
   if(action==="confirmRemoval"){left.item.auditConfirmRemoval();oldRemoveRequest=Object.keys(owner.localRemovalRequests)[0]||"";oldRemoveEpoch=owner.notificationWorkerEpoch}
   if(action==="confirmRemovalRight")right.item.auditConfirmRemoval()
   if(action==="injectOldRemoval")owner.messagingEvent({event:"notification_local_remove",request_id:oldRemoveRequest,notification_epoch:oldRemoveEpoch,entries:[{device:"fake",id:"n",occurrence_id:owner.notificationOccurrences[key]}]})
   if(action==="replayOld")owner.messagingEvent({event:"notification",notification_epoch:owner.notificationWorkerEpoch,notification:{device:"fake",id:"n",revision:1,occurrence_id:owner.notificationOccurrences[key],internal_id:"n1",reply_id:"reply1",title:"Synthetic contact",app:"Synthetic app",body:"Synthetic note",dismissable:true}})
   if(action==="replaySameOccurrence")owner.messagingCommand({op:"audit_seed",device:"fake",id:"n",internal_id:"n1",reply_id:"reply1",title:"Synthetic contact",app:"Synthetic app",body:"Synthetic note",dismissable:true})
   if(action==="closedChurn") {churnCompleted=0;runClosedChurn(0,300)}
   if(action==="stateErrorActive") {
     var rows=Object.keys(owner.notificationOccurrences).map(function(k){var pair=JSON.parse(k),occ=owner.notificationOccurrences[k];return {device:pair[0],id:pair[1],occurrence_id:occ,removed:owner.localNotificationRemovals[k]===occ}})
     owner.messagingEvent({event:"ready",notification_epoch:owner.notificationWorkerEpoch,notification_revision:owner.notificationRevisionWatermark,notification_occurrences:rows,notification_removals:[],notification_state_error:"Local notification state unavailable: fixture"})
     stateErrorObserved=[left.item.auditWarning().text,right.item.auditWarning().text]
     owner.messagingEvent({event:"device",device:{id:"fake",online:true}})
     owner.messagingEvent({event:"ready",notification_epoch:owner.notificationWorkerEpoch,notification_revision:owner.notificationRevisionWatermark,notification_occurrences:rows,notification_removals:[]})
     stateErrorObserved.push(left.item.auditWarning().text,right.item.auditWarning().text)
   }
   if(action==="stateErrorRecovered") {
     var rows=Object.keys(owner.notificationOccurrences).map(function(k){var pair=JSON.parse(k),occ=owner.notificationOccurrences[k];return {device:pair[0],id:pair[1],occurrence_id:occ,removed:owner.localNotificationRemovals[k]===occ}})
     owner.messagingEvent({event:"ready",notification_epoch:owner.notificationWorkerEpoch,notification_revision:owner.notificationRevisionWatermark,notification_occurrences:rows,notification_removals:[],notification_state_error:""})
   }
   if(action==="contactsFailure")left.item.auditContactEvent({event:"contacts",device:"fake",request_id:left.item.smsComposer.contactsRequest,error:"Synthetic contact read failed",available:false,contacts:[]})
   if(action==="startContactRequests"){left.item.auditStartContacts("contacts-left");right.item.auditStartContacts("contacts-right")}
   if(action==="contactsError")owner.messagingEvent({event:"error",device:"fake",request_id:"contacts-left",error:"Synthetic contact read failed"})
   if(action==="contactsSuccess")owner.messagingEvent({event:"contacts",device:"fake",request_id:"contacts-left",contacts:[{name:"Alex",numbers:[{number:"5550100",label:"Mobile"}]}],error:"",skipped:0})
   if(action.indexOf("inject:")===0)owner.messagingEvent(JSON.parse(action.slice(7)))
   if(action==="capacityChurn") {
     owner.messagingEvent({event:"ready",notification_epoch:"capacity-worker-a",notification_revision:0,notification_occurrences:[],notification_removals:[]})
     for(var i=0;i<owner.maxNotificationOccurrences;i++)owner.messagingEvent({event:"notification",notification_epoch:"capacity-worker-a",notification:{device:"fake",id:"n"+i,revision:i+1,occurrence_id:"occurrence-"+i,internal_id:"",reply_id:"",title:"n",app:"test",body:"",dismissable:false}})
     owner.messagingEvent({event:"notification",notification_epoch:"capacity-worker-a",notification:{device:"fake",id:"overflow",revision:owner.maxNotificationOccurrences+1,occurrence_id:"overflow",internal_id:"",reply_id:"",title:"overflow",app:"test",body:"",dismissable:false}})
     capacityObserved=owner.messagingError
     owner.messagingEvent({event:"notification_removed",notification_epoch:"capacity-worker-a",device:"fake",id:"n0",occurrence_id:"occurrence-0",authoritative:true,revision:owner.maxNotificationOccurrences+1})
     owner.messagingEvent({event:"notification",notification_epoch:"capacity-worker-a",notification:{device:"fake",id:"after",revision:owner.maxNotificationOccurrences+2,occurrence_id:"after",internal_id:"",reply_id:"",title:"after",app:"test",body:"",dismissable:false}})
     owner.messagingEvent({event:"notification",notification_epoch:"capacity-worker-a",notification:{device:"fake",id:"stale",revision:999,occurrence_id:"stale",internal_id:"",reply_id:"",title:"stale",app:"test",body:"",dismissable:false}})
     owner.messagingEvent({event:"worker_stopped"})
     owner.messagingEvent({event:"ready",notification_epoch:"capacity-worker-b",notification_revision:0,notification_occurrences:[],notification_removals:[]})
     owner.messagingEvent({event:"notification",notification_epoch:"capacity-worker-b",notification:{device:"fake",id:"fresh",revision:1,occurrence_id:"fresh",internal_id:"",reply_id:"",title:"fresh",app:"test",body:"",dismissable:false}})
   }
   if(action==="stateErrorSequence") {
     owner.messagingEvent({event:"ready",notification_epoch:"state-error-a",notification_revision:0,notification_state_error:"Local notification state unavailable: fixture"})
     stateErrorObserved=[left.item.auditState().error]
     owner.messagingEvent({event:"device",device:{id:"fake",online:true}})
     owner.messagingEvent({event:"ready",notification_epoch:"state-error-a",notification_revision:0})
     stateErrorObserved.push(left.item.auditState().error)
     owner.messagingEvent({event:"ready",notification_epoch:"state-error-b",notification_revision:0,notification_state_error:""})
     stateErrorObserved.push(left.item.auditState().error)
   }
   if(action==="changeDraftReturn"){left.item.notificationEdit(key,"draft","Changed reviewed draft");left.item.notificationEdit(key,"draft","Draft A shown on left")}
   if(action==="createService")owner=serviceComponent.createObject(fixture)
   if(action==="recreateRight"){right.active=false;right.active=true}
   if(action==="destroyRight"){right.active=false}
   if(action==="restoreRight"){right.active=true}
   if(action==="destroyLeft"){left.active=false}
   if(action==="restoreLeft"){left.active=true}
   if(action==="editA"){left.item.notificationEdit(key,"begin","");left.item.notificationEdit(key,"draft","Draft A shown on left")}
   if(action==="editB"){right.item.notificationEdit(key,"begin","");right.item.notificationEdit(key,"draft","Draft B written on right")}
   if(action==="editHold"){left.item.notificationEdit(key,"begin","");left.item.notificationEdit(key,"draft","HOLD: original reviewed draft")}
   if(action==="sendA")left.item.auditSendNotification()
   if(action==="sendB")right.item.auditSendNotification()
   if(action==="replySuccess"){var c=left.item.notificationCards[key];owner.messagingEvent({event:"notification_action_result",request_id:c.pending,device:"fake",id:"n",action:"notification_reply",accepted:true})}
   if(action==="replyFailure"){var c=left.item.notificationCards[key];owner.messagingEvent({event:"notification_action_result",request_id:c.pending,device:"fake",id:"n",action:"notification_reply",accepted:false,error:"Synthetic temporary failure"})}
   if(action==="reviewB"){right.item.notificationEdit(key,"discard","");right.item.notificationEdit(key,"begin","");right.item.notificationEdit(key,"draft","Draft B reviewed on right")}
   if(action==="emojiB")right.item.auditEmoji()
   if(action==="pickerLeft")left.item.auditPicker()
   if(action==="smsLeft")left.item.auditSms("SMS left")
   if(action==="smsRight")right.item.auditSms("SMS right")
   if(action==="resolveRight")owner.messagingEvent({event:"sms_result",device:"fake",request_id:right.item.smsComposer.pending,accepted:true})
   if(action==="deviceB"){owner.devices=owner.devices.concat([{id:"other",name:"Other synthetic",online:true,can:["kdeconnect_sms","kdeconnect_notifications"]}]);left.item.selectedId="other"}
   if(action==="deviceA")left.item.selectedId="fake"
   if(action==="detach")api.connected=false
   if(action==="refreshBoth"){left.item.auditRefresh();right.item.auditRefresh()}
   if(action==="reattach")api.connected=true
   if(action==="crash")owner.messagingCommand({op:"audit_crash",request_id:owner.nextRequestId("audit")})
   if(action==="destroyService"){var old=owner;owner=null;old.destroy();serviceRecreate.start()}
   if(action==="destroyServiceDirect"){owner.destroy();serviceRecreate.start()}
   if(action==="refreshLeft")left.item.auditRefresh()
   if(action==="refreshRight")right.item.auditRefresh()
   return state()
 }
 function runClosedChurn(index,total){
   if(index>=total){churnCompleted=index;return}
   var id="closed-"+index,occ="closed-occurrence-"+index,revision=owner.notificationRevisionWatermark+1
   var note={device:"fake",id:id,revision:revision,occurrence_id:occ,internal_id:"",reply_id:"",title:"Closed churn",app:"fixture",body:"",dismissable:false}
   owner.messagingEvent({event:"notification",notification_epoch:owner.notificationWorkerEpoch,notification:note})
   var k=JSON.stringify(["fake",id])
   left.item.notificationEdit(k,"begin","");left.item.notificationEdit(k,"draft","left draft "+index)
   right.item.notificationEdit(k,"begin","");right.item.notificationEdit(k,"draft","right draft "+index)
   owner.messagingEvent({event:"notification_removed",notification_epoch:owner.notificationWorkerEpoch,device:"fake",id:id,occurrence_id:occ,authoritative:true,revision:revision+1})
   left.item.auditClearAll()
   Qt.callLater(function(){left.item.auditConfirmRemoval();Qt.callLater(function(){
     if(right.item.auditDraftFor(k)!=="right draft "+index)churnError="left cleanup discarded right draft at "+index
     right.item.auditClearAll();Qt.callLater(function(){right.item.auditConfirmRemoval();Qt.callLater(function(){
       if(right.item.auditDraftFor(k))churnError="right confirmation did not discard draft at "+index
       runClosedChurn(index+1,total)
     })})
   })})
 }
 IpcHandler {target:"v6-remediation-fixture"
   function step(action:string):string{return JSON.stringify(fixture.execute(action))}
   function quit():void{Qt.quit()}
 }
}'''


PANEL_HOOKS = r'''
  function auditFind(o,name){if(!o)return null;if(o.objectName===name)return o;var kids=(o.children||[]).slice();if(o.contentChildren)kids=kids.concat(o.contentChildren);if(o.contentItem&&kids.indexOf(o.contentItem)<0)kids.push(o.contentItem);for(var i=0;i<kids.length;i++){var hit=auditFind(kids[i],name);if(hit)return hit}return null}
  function auditState(){var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;
    var e=c?auditFind(c,"replyEditor"):null;var b=c?auditFind(c,"sendReplyButton"):null;
    var reply=c?auditFind(c,"replyButton"):null;
    var emoji=c?auditFind(c,"replyEmojiButton"):null;var picker=c?auditFind(c,"replyEmojiPicker"):null;
    if(!emoji && c)emoji=auditFindText(c,"Emoji");
    return {hasService:!!service,client:clientId,serviceEpoch:attachedServiceEpoch,ready:messagingReady,models:notificationModel.count,
      replyVisible:reply?reply.visible:false,
      emojiFound:!!emoji,emojiEnabled:emoji?emoji.enabled:false,pickerEnabled:picker?picker.enabled:false,
      notification:notificationModel.count?JSON.parse(JSON.stringify(notificationModel.get(0).payload)):null,
      editor:e?e.text:null,sendEnabled:b?b.enabled:false,sms:JSON.parse(JSON.stringify(smsComposer)),error:messagingError,
      notificationCount:notificationModel.count,notificationStatus:c?c.payload.status:"",confirmation:localRemovalConfirmation?(localRemovalConfirmation.keys===null?"clear-all":"remove:"+localRemovalConfirmation.keys.join(",")):"",
      message:message,selected:selectedId,phone:phone?phone.id:"",deviceCount:devices.length,cardKeys:Object.keys(notificationCards),draftSlot:draftSlotIdentity,serviceDraftSlots:service?Object.keys(service.panelDraftSnapshots):[],removalKeys:service?Object.keys(service.localNotificationRemovals):[],warning:auditWarning()}}
  function auditWarning(){return {exists:true,visible:!!notificationStateWarning.visible,text:String(notificationStateWarning.text)}}
  function auditDraftFor(key){var c=notificationCards[key];return c?String(c.draft||""):""}
  function auditReplyControls(){var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;var b=c?auditFind(c,"sendReplyButton"):null;return {count:notificationRepeater.count,selected:selectedNotification,context:workspaceContext,ready:messagingReady,online:online,card:c?c.payload:null,sendExists:!!b,sendVisible:b?b.visible:false,sendEnabled:b?b.enabled:false}}
  function auditSendNotification(){var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;
    var b=c?auditFind(c,"sendReplyButton"):null;if(b&&b.enabled)b.clicked()}
  function auditDraftState(text){for(var i=0;i<notificationRepeater.count;i++){var c=notificationRepeater.itemAt(i);
    if(c&&c.payload&&c.payload.draft===text){var b=auditFind(c,"sendReplyButton");return {found:true,enabled:b?b.enabled:false,
      text:c.payload.draft,occurrence:c.payload.draftOccurrence,epoch:c.payload.draftNotificationEpoch,
      noteOccurrence:c.payload.note.occurrence_id,noteEpoch:c.payload.note.notification_epoch,
      unavailable:c.payload.unavailable,status:c.payload.status}}}return {found:false}}
  function auditSendDraft(text){for(var i=0;i<notificationRepeater.count;i++){var c=notificationRepeater.itemAt(i);
    if(c&&c.payload&&c.payload.draft===text){var b=auditFind(c,"sendReplyButton");if(b&&b.enabled)b.clicked();return}}
  }
  function auditDismissNotification(){var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;
    var b=c?auditFind(c,"dismissButton"):null;if(b&&b.enabled)b.clicked()}
  function auditFindText(o,text){if(o.text===text)return o;for(var i=0;i<(o.children||[]).length;i++){var hit=auditFindText(o.children[i],text);if(hit)return hit}return null}
  function auditRefresh(){refreshButton.clicked()}
  function auditGeometry(){popup.screen=Quickshell.screens.find(s=>s.name==="DP-1");popup.centerOnBar=true}
  function auditClearAll(){auditGeometry();showNotifications("");var b=auditFind(workspaceContent,"clearLocalNotifications");if(b&&b.enabled)b.clicked()}
  function auditConfirmRemoval(){var b=auditFind(workspaceContent,"confirmLocalNotificationRemoval");if(b&&b.enabled)b.clicked()}
  function auditRemoveInactive(){auditGeometry();showNotifications("");var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;
    var b=c?auditFind(c,"removeNotificationButton"):null;if(b&&b.enabled)b.clicked()}
  function auditContactEvent(event){ComposerState.receive(smsComposer,event);saveComposer()}
  function auditStartContacts(request){smsComposer=ComposerState.create();smsComposer.device="fake";smsComposer.recipient="5550100";
    smsComposer.text="Contact draft";smsComposer.contactsLoading=true;smsComposer.contactsRequest=request;saveComposer()}
  function auditEmoji(){var c=notificationRepeater.count?notificationRepeater.itemAt(0):null;
    var b=c?auditFind(c,"replyEmojiButton"):null;if(!b&&c)b=auditFindText(c,"Emoji");if(b&&b.enabled)b.clicked();
    var p=c?auditFind(c,"replyEmojiPicker"):null;var choice=p?auditFind(p,"emojiChoice"):null;
    if(p&&p.enabled&&choice&&choice.enabled)choice.clicked()}
  function auditSms(text){smsComposer=ComposerState.create();smsComposer.device="fake";smsComposer.recipient="5550100";
    smsComposer.text=text;smsComposer.open=true;saveComposer();composerSend()}
  function auditDraftSms(text){smsComposer=ComposerState.create();smsComposer.device="fake";smsComposer.recipient="5550100";smsComposer.text=text;smsComposer.open=true;workspaceContext="new";saveComposer()}
  function auditPendingSms(text){smsComposer=ComposerState.create();smsComposer.device="fake";smsComposer.recipient="5550100";smsComposer.text=text;smsComposer.open=true;workspaceContext="new";saveComposer();composerSend()}
  function auditPicker(){smsComposer.pickerRequest=newRequestId("files");saveComposer();
    smsCommand({op:"pick_files",request_id:smsComposer.pickerRequest,device:smsComposer.device})}
  function previewInspect(mode)'''


WORKER = r'''import json,os,signal,sys,time,uuid
from pathlib import Path
from notification_removal_store import NotificationRemovalStore, notification_fingerprint
log=Path(__file__).parents[1]/"worker.jsonl"
state=NotificationRemovalStore()
epoch=uuid.uuid4().hex
revision=0
def record(kind,**kw):
 with log.open("a") as f:f.write(json.dumps(dict(kind=kind,pid=os.getpid(),time=time.time(),**kw))+"\n")
def emit(value):print(json.dumps(value),flush=True)
def stop(*args):record("stop");sys.exit(0)
signal.signal(signal.SIGTERM,stop)
record("start");emit({"event":"ready","audit_pid":os.getpid(),"notification_epoch":epoch,"notification_revision":revision,"notification_state_error":state.error,"notification_occurrences":state.snapshot()})
for line in sys.stdin:
 command=json.loads(line);record("command",command=command);op=command.get("op")
 if op=="audit_crash":record("crash");sys.exit(42)
 if op=="audit_seed":
  revision+=1
  note={k:command.get(k,"") for k in ("device","id","internal_id","reply_id","title","app","body","dismissable")}
  note["revision"]=revision
  occurrence=state.occurrence(note["device"],note["id"],notification_fingerprint(note))
  note["occurrence_id"]=occurrence
  emit({"event":"notification","notification":note,"notification_epoch":epoch})
 elif op=="audit_close":
  key=NotificationRemovalStore.key(command["device"],command["id"]);old=next((x for x in state.entries.values() if NotificationRemovalStore.key(x["device"],x["id"])==key),None)
  if old:state.retire(old["device"],old["id"],old["occurrence_id"])
  revision+=1;emit({"event":"notification_removed","device":command["device"],"id":command["id"],"occurrence_id":old["occurrence_id"] if old else "","authoritative":True,"revision":revision,"notification_epoch":epoch})
 elif op=="notification_local_remove":
  if (Path(__file__).parents[1]/"hold-local-remove").exists():
   record("held_local_remove",request_id=command.get("request_id"));continue
  result=state.mark_removed(command.get("entries",[]))
  if result["removed"]:emit({"event":"notification_local_remove","request_id":command.get("request_id"),"entries":result["removed"],"notification_epoch":epoch})
  else:emit({"event":"notification_local_remove_failed","request_id":command.get("request_id"),"error":result["error"] or "No entries","notification_epoch":epoch})
 else:emit({"event":"audit_command","command":command})
'''


class ProductionMultiMonitorRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quickshell = shutil.which("quickshell")
        cls.can_run = bool(cls.quickshell and os.environ.get("WAYLAND_DISPLAY") and OMARCHY.is_dir())

    def setUp(self):
        if not self.can_run:
            self.skipTest("requires Quickshell, Omarchy QML modules, and a Wayland test session")
        self.temp = tempfile.TemporaryDirectory(prefix="pocket-v6-qml-")
        self.stage = Path(self.temp.name)
        for name in ("Commons", "Ui"):
            (self.stage / name).symlink_to(OMARCHY / name)
        pocket = self.stage / "Pocket"
        pocket.mkdir()
        for path in ROOT.iterdir():
            if path.is_file() and path.suffix in (".qml", ".js", ".py"):
                shutil.copy2(path, pocket / path.name)
        if self._testMethodName == "test_f6_occurrence_metadata_is_bounded_and_restarts_by_epoch":
            service_file=pocket/"Service.qml"
            service_file.write_text(service_file.read_text().replace("readonly property int maxNotificationOccurrences: 4096","readonly property int maxNotificationOccurrences: 4"))
        panel = pocket / "Panel.qml"
        source = panel.read_text()
        panel_hooks=PANEL_HOOKS
        if "id: notificationStateWarning" not in source:
            panel_hooks=panel_hooks.replace(
                'function auditWarning(){return {exists:true,visible:!!notificationStateWarning.visible,text:String(notificationStateWarning.text)}}',
                'function auditWarning(){return {exists:false,visible:false,text:""}}')
        source = source.replace("  function previewInspect(mode)", panel_hooks)
        panel.write_text(source)
        if self._testMethodName == "test_f2_initially_missing_scoped_service_stays_unavailable":
            shell_source = SHELL_QML.replace(
                "Component.onCompleted: if(fixture.startService) owner=serviceComponent.createObject(fixture)",
                "Component.onCompleted: {}")
        else:
            shell_source = SHELL_QML
        bridge_id = "fixture_phone" if (self._testMethodName in ("test_f1_real_production_main_frames_start_restart_hydrate_and_remove",
                                                                  "test_s4_real_production_startup_hydration_warning",
                                                                  "test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch") or
                                          self._testMethodName in R1_PRODUCTION_TESTS) else "fake"
        (pocket / "bridge.py").write_text(
            'import json\nprint(json.dumps({"ok":True,"dependencies":{},"devices":[{"id":"'+bridge_id+'","name":"Synthetic device","online":True,"can":["kdeconnect_sms","kdeconnect_notifications"],"media":{}}]}))\n'
        )
        (self.stage / "active-notifications.json").write_text('["n"]')
        if self._testMethodName == "test_s4_real_production_startup_hydration_warning":
            private_state=self.stage/"state/omarchy-pocket-extended"
            private_state.mkdir(parents=True,exist_ok=True)
            (private_state/"notification-removals-v1.json").write_text("{corrupt")
        if (self._testMethodName in ("test_f1_real_production_main_frames_start_restart_hydrate_and_remove",
                                    "test_s4_real_production_startup_hydration_warning",
                                    "test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch") or
                self._testMethodName in R1_PRODUCTION_TESTS):
            shutil.copy2(ROOT / "messaging_service.py", pocket / "messaging_service_production.py")
            shutil.copy2(ROOT / "tests/fixtures/production_worker_wrapper.py", pocket / "messaging_service.py")
        else:
            (pocket / "messaging_service.py").write_text(WORKER)
        (self.stage / "shell.qml").write_text(shell_source)
        self.env = dict(os.environ, QT_QPA_PLATFORM="wayland", QT_QPA_PLATFORMTHEME="basic",
                        QT_QUICK_CONTROLS_STYLE="Basic", QT_QUICK_BACKEND="software",
                        PYTHONDONTWRITEBYTECODE="1", XDG_CONFIG_HOME=str(self.stage / "config"),
                        XDG_STATE_HOME=str(self.stage / "state"),
                        POCKET_FIXTURE_ACTIVE_FILE=str(self.stage / "active-notifications.json"),
                        POCKET_FIXTURE_PID_FILE=str(self.stage / "production-worker.pid"),
                        POCKET_FIXTURE_FRAME_LOG=str(self.stage / "production-worker.frames"),
                        POCKET_FIXTURE_CALL_LOG=str(self.stage / "production-worker.calls"),
                        POCKET_FIXTURE_COMMAND_LOG=str(self.stage / "production-worker.commands"),
                        POCKET_FIXTURE_CONTROL_FILE=str(self.stage / "production-worker.control"))
        self.log = (self.stage / "quickshell.log").open("w")
        self.proc = subprocess.Popen([self.quickshell, "-p", str(self.stage)], env=self.env,
                                     stdout=self.log, stderr=self.log)
        self.call("inspect")
        if self._testMethodName != "test_f2_initially_missing_scoped_service_stays_unavailable":
            self.wait_ready()

    def tearDown(self):
        if getattr(self, "proc", None) and self.proc.poll() is None:
            subprocess.run([self.quickshell, "ipc", "-p", str(self.stage), "call",
                            "v6-remediation-fixture", "quit"], env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        if getattr(self, "log", None):
            self.log.close()
        evidence=os.environ.get("POCKET_TEST_EVIDENCE_DIR")
        if evidence and (getattr(self,"_testMethodName","") in ("test_f1_real_production_main_frames_start_restart_hydrate_and_remove",
                                                                  "test_s4_real_production_startup_hydration_warning",
                                                                  "test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch") or
                         getattr(self,"_testMethodName","") in R1_PRODUCTION_TESTS):
            target=Path(evidence);target.mkdir(parents=True,exist_ok=True)
            for name in ("production-worker.frames","production-worker.calls","production-worker.commands","quickshell.log"):
                source=self.stage/name
                if source.exists():shutil.copy2(source,target/name)
        if getattr(self, "temp", None):
            self.temp.cleanup()

    def call(self, action):
        deadline = time.monotonic() + 5
        while True:
            result = subprocess.run([self.quickshell, "ipc", "-p", str(self.stage), "call",
                                     "v6-remediation-fixture", "step", action], env=self.env,
                                    capture_output=True, text=True, timeout=6)
            if result.returncode == 0:
                try:return json.loads(result.stdout)
                except json.JSONDecodeError:self.fail(f"fixture call {action} returned invalid JSON: {result.stdout!r} {result.stderr!r}\n{(self.stage/'quickshell.log').read_text()}")
            if time.monotonic() >= deadline:
                self.fail(f"fixture call {action} failed: {result.stderr}\n{(self.stage/'quickshell.log').read_text()}")
            time.sleep(0.1)

    def wait_state(self, predicate, timeout=5):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            state=self.call("inspect")
            if predicate(state):return state
            time.sleep(0.05)
        detail="production component state did not converge: "+repr(state)
        if (getattr(self,"_testMethodName","").startswith("test_f1_real_production") or
                getattr(self,"_testMethodName","")=="test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch" or
                getattr(self,"_testMethodName","") in R1_PRODUCTION_TESTS):
            detail+="\n---quickshell---\n"+(self.stage/"quickshell.log").read_text()
            frames=self.stage/"production-worker.frames"
            if frames.exists():detail+="\n---frames---\n"+frames.read_text()
            calls=self.stage/"production-worker.calls"
            if calls.exists():detail+="\n---calls---\n"+calls.read_text()
            commands=self.stage/"production-worker.commands"
            if commands.exists():detail+="\n---commands---\n"+commands.read_text()
            pid=self.stage/"production-worker.pid"
            if pid.exists():detail+="\npid="+pid.read_text()
        self.fail(detail)

    def wait_ready(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.call("inspect")
            if state["serviceReady"] and state["left"] and state["right"]:
                return state
            time.sleep(0.1)
        detail="production service did not become ready; state="+repr(state)
        if (getattr(self,"_testMethodName","").startswith("test_f1_real_production") or
                getattr(self,"_testMethodName","")=="test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch" or
                getattr(self,"_testMethodName","") in R1_PRODUCTION_TESTS):
            detail+="\n"+(self.stage/"quickshell.log").read_text()
            for name in ("production-worker.frames","production-worker.calls","production-worker.commands","production-worker.pid"):
                path=self.stage/name
                if path.exists():detail+="\n---"+name+"---\n"+path.read_text()
        self.fail(detail)

    def restart_fixture_process(self):
        subprocess.run([self.quickshell, "ipc", "-p", str(self.stage), "call",
                        "v6-remediation-fixture", "quit"], env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        self.proc.wait(timeout=8)
        self.proc = subprocess.Popen([self.quickshell, "-p", str(self.stage)], env=self.env,
                                     stdout=self.log, stderr=self.log)
        return self.wait_ready()

    def worker_log(self):
        path = self.stage / "worker.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def wait_for_starts(self, count, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            starts = [entry for entry in self.worker_log() if entry["kind"] == "start"]
            if len(starts) >= count:
                return starts
            time.sleep(0.1)
        self.fail(f"expected {count} worker starts, observed {len(starts)}")


    def _r1_open_draft(self, panel="right", text="R1 original draft"):
        key=json.dumps(["fixture_phone","n"],separators=(",",":"))
        self.call("eval:"+panel+".item.auditGeometry();"+panel+".item.open();"+panel+
                  ".item.showNotifications("+json.dumps(key)+");"+panel+
                  ".item.notificationEdit("+json.dumps(key)+",'begin','');"+panel+
                  ".item.notificationEdit("+json.dumps(key)+",'draft',"+json.dumps(text)+")")
        return key

    def _r1_draft_state(self, panel="right", text="R1 original draft"):
        state=self.call("eval:fixture.capacityObserved=JSON.stringify("+panel+".item.auditDraftState("+json.dumps(text)+"))")
        return json.loads(state["capacityObserved"])

    def _r1_signal(self, member):
        (self.stage/"production-worker.control").write_text(json.dumps({"type":"signal",
            "path":"/modules/kdeconnect/devices/fixture_phone/notifications",
            "interface":"org.kde.kdeconnect.device.notifications","member":member,"args":["n"]}))

    def _r1_reply_commands(self):
        path=self.stage/"production-worker.commands"
        return [json.loads(line) for line in path.read_text().splitlines()
                if json.loads(line).get("op")=="notification_reply"] if path.exists() else []

    def _r1_reply_dispatches(self):
        path=self.stage/"production-worker.calls"
        return sum(line.startswith("sendReply ") for line in path.read_text().splitlines()) if path.exists() else 0

    def test_r1_reused_capabilities_keep_original_proof_across_panel_recreation(self):
        state=self.wait_state(lambda x:x["right"]["models"]==1,timeout=12)
        old=state["right"]["notification"]["note"]
        self._r1_open_draft(text="Old occurrence draft")
        self._r1_signal("notificationRemoved")
        self.wait_state(lambda x:x["right"]["notification"] and x["right"]["notification"]["unavailable"])
        self._r1_signal("notificationPosted")
        self.wait_state(lambda x:x["right"]["notification"] and
                        x["right"]["notification"]["note"]["occurrence_id"]!=old["occurrence_id"])
        before=self._r1_draft_state(text="Old occurrence draft")
        self.assertFalse(before["enabled"])
        self.call("recreateRight")
        self.wait_state(lambda x:x["right"] is not None and x["right"]["models"]>=1)
        after=self._r1_draft_state(text="Old occurrence draft")
        self.assertTrue(after["found"]);self.assertFalse(after["enabled"])
        self.assertTrue(after["unavailable"]);self.assertEqual(after["text"],"Old occurrence draft")
        self.assertEqual(after["occurrence"],old["occurrence_id"])
        self.assertEqual(after["epoch"],old["notification_epoch"])
        self.call("eval:right.item.auditSendDraft('Old occurrence draft')")
        self.assertEqual(self._r1_reply_commands(),[])
        self.assertEqual(self._r1_reply_dispatches(),0)

    def test_r1_worker_epoch_and_absent_panel_reuse_cannot_rebind_drafts(self):
        # Epoch replacement while the editor exists.
        state=self.wait_state(lambda x:x["right"]["models"]==1,timeout=12)
        old=state["right"]["notification"]["note"]
        self._r1_open_draft(text="Old epoch draft")
        os.kill(int((self.stage/"production-worker.pid").read_text()),signal.SIGTERM)
        state=self.wait_state(lambda x:x["right"]["notification"] and
                              x["right"]["notification"]["note"]["notification_epoch"]!=old["notification_epoch"],timeout=15)
        self.assertFalse(self._r1_draft_state(text="Old epoch draft")["enabled"])
        self.call("recreateRight")
        self.wait_state(lambda x:x["right"] is not None and x["right"]["models"]>=1)
        restored=self._r1_draft_state(text="Old epoch draft")
        self.assertFalse(restored["enabled"]);self.assertTrue(restored["unavailable"])
        self.assertEqual(restored["epoch"],old["notification_epoch"])
        self.assertEqual(restored["text"],"Old epoch draft")
        self.call("eval:right.item.auditSendDraft('Old epoch draft')")
        self.assertEqual(self._r1_reply_dispatches(),0)

        # Close and reuse the capability while its editor is absent.
        current=self.call("inspect")["right"]["notification"]["note"]
        self._r1_open_draft(text="Absent panel draft")
        self.call("destroyRight")
        occurrence_key=json.dumps(["fixture_phone","n"],separators=(",",":"))
        self._r1_signal("notificationRemoved")
        self.wait_state(lambda x:occurrence_key not in x["serviceOccurrences"])
        self._r1_signal("notificationPosted")
        self.wait_state(lambda x:occurrence_key in x["serviceOccurrences"] and
                        x["serviceOccurrences"][occurrence_key]!=current["occurrence_id"])
        self.call("restoreRight")
        self.wait_state(lambda x:x["right"] is not None and x["right"]["models"]>=1)
        restored=self._r1_draft_state(text="Absent panel draft")
        self.assertTrue(restored["found"]);self.assertFalse(restored["enabled"])
        self.assertTrue(restored["unavailable"]);self.assertEqual(restored["text"],"Absent panel draft")
        self.assertEqual(restored["occurrence"],current["occurrence_id"])
        self.call("eval:right.item.auditSendDraft('Absent panel draft')")
        self.assertEqual(self._r1_reply_dispatches(),0)

    def test_r1_same_occurrence_restoration_stays_sendable_and_dispatches_once(self):
        state=self.wait_state(lambda x:x["right"]["models"]==1,timeout=12)
        note=state["right"]["notification"]["note"]
        self._r1_open_draft(text="Valid same occurrence")
        self._r1_open_draft(panel="left",text="Other monitor copy")
        self.call("recreateRight")
        self.wait_state(lambda x:x["right"] is not None and x["right"]["models"]==1)
        restored=self._r1_draft_state(text="Valid same occurrence")
        self.assertTrue(restored["enabled"]);self.assertFalse(restored["unavailable"])
        self.assertEqual(restored["occurrence"],note["occurrence_id"])
        self.assertEqual(restored["epoch"],note["notification_epoch"])
        self.call("eval:right.item.auditSendDraft('Valid same occurrence')")
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and not self._r1_reply_commands():time.sleep(.05)
        self.assertEqual(len(self._r1_reply_commands()),1)
        self.assertEqual(self._r1_reply_commands()[0]["text"],"Valid same occurrence")
        self.assertEqual(self._r1_reply_commands()[0]["occurrence_id"],note["occurrence_id"])
        self.assertEqual(self._r1_reply_dispatches(),1)
        # The sibling's copy is invalidated by Service's consumed-token event,
        # survives its own panel recreation, and cannot submit a second reply.
        left_state=self._r1_draft_state(panel="left",text="Other monitor copy")
        self.assertTrue(left_state["found"]);self.assertFalse(left_state["enabled"])
        self.assertEqual(left_state["text"],"Other monitor copy")
        self.call("destroyLeft")
        self.call("restoreLeft")
        self.wait_state(lambda x:x["left"] is not None and x["left"]["models"]==1)
        left_state=self._r1_draft_state(panel="left",text="Other monitor copy")
        self.assertFalse(left_state["enabled"]);self.assertTrue(left_state["unavailable"])
        self.call("eval:left.item.auditSendDraft('Other monitor copy')")
        self.assertEqual(len(self._r1_reply_commands()),1);self.assertEqual(self._r1_reply_dispatches(),1)

    def test_pr1_actual_panel_reply_and_dismiss_bind_occurrence_and_epoch(self):
        state=self.wait_state(lambda x:x["left"]["models"]==1 and x["right"]["models"]==1,timeout=12)
        note=state["left"]["notification"]["note"]
        worker_epoch=state["workerEpoch"]
        self.assertEqual(note["notification_epoch"],worker_epoch)
        expression=("left.item.auditGeometry();left.item.open();var k=JSON.stringify(['fixture_phone','n']);"
                    "left.item.showNotifications(k);left.item.notificationEdit(k,'begin','');"
                    "left.item.notificationEdit(k,'draft','Synthetic current reply');left.item.auditSendNotification()")
        panel=self.call("eval:"+expression)
        controls=self.call("eval:left.item.auditReplyControls()")
        commands_path=self.stage/"production-worker.commands"
        def production_commands():
            return [json.loads(line) for line in commands_path.read_text().splitlines()] if commands_path.exists() else []
        deadline=time.monotonic()+8;replies=[]
        while time.monotonic()<deadline:
            replies=[c for c in production_commands() if c.get("op")=="notification_reply"]
            if replies:break
            time.sleep(.05)
        self.assertEqual(len(replies),1, "no backend reply; controls="+repr(controls)+" panel="+repr(panel))
        self.assertEqual(replies[0]["occurrence_id"],note["occurrence_id"])
        self.assertEqual(replies[0]["notification_epoch"],worker_epoch)
        calls=(self.stage/"production-worker.calls").read_text().splitlines()
        self.assertEqual(sum(line.startswith("sendReply ") for line in calls),1)
        self.call("eval:left.item.auditDismissNotification()")
        deadline=time.monotonic()+8;dismisses=[]
        while time.monotonic()<deadline:
            dismisses=[c for c in production_commands() if c.get("op")=="notification_dismiss"]
            calls=(self.stage/"production-worker.calls").read_text().splitlines()
            if dismisses and any(line.startswith("dismiss ") for line in calls):break
            time.sleep(.05)
        self.assertEqual(len(dismisses),1)
        self.assertEqual(dismisses[0]["occurrence_id"],note["occurrence_id"])
        self.assertEqual(dismisses[0]["notification_epoch"],worker_epoch)
        self.assertEqual(sum(line.startswith("sendReply ") for line in calls),1)
        self.assertEqual(sum(line.startswith("dismiss ") for line in calls),1)

    def test_f1_real_production_main_frames_start_restart_hydrate_and_remove(self):
        # The child executes the unmodified production main and real GLib/stdin
        # parser. Only external D-Bus transport is synthetic; both production
        # Panel instances consume actual serialized worker stdout frames.
        state=self.wait_state(lambda x:x["left"]["models"]==1 and x["right"]["models"]==1 and x["deviceCount"]==1, timeout=10)
        self.assertTrue(state["sameService"])
        self.assertEqual(len(state["serviceOccurrences"]),1,repr(state))
        frames=[json.loads(line) for line in (self.stage/"production-worker.frames").read_text().splitlines()]
        first_ready=next(i for i,e in enumerate(frames) if e.get("event")=="ready")
        first_note=next(i for i,e in enumerate(frames) if e.get("event")=="notification")
        ready=frames[first_ready];note=frames[first_note]
        self.assertLess(first_ready,first_note)
        self.assertEqual(ready["notification_epoch"],note["notification_epoch"])
        self.assertEqual(ready["notification_revision"],0)
        self.assertEqual(note["notification"]["revision"],1)
        self.assertTrue(state["left"]["notification"]["note"]["occurrence_id"])

        before_remove=self.call("inspect")
        self.call("clearAll")
        self.call("confirmRemoval")
        command_path=self.stage/"production-worker.commands"
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            actual=[json.loads(line) for line in command_path.read_text().splitlines()] if command_path.exists() else []
            if any(c.get("op")=="notification_local_remove" for c in actual):break
            time.sleep(.05)
        removals=[c for c in actual if c.get("op")=="notification_local_remove"]
        self.assertEqual(len(removals),1,"actual Panel command must traverse production stdin exactly once: "+repr(actual))
        pending=removals[0]["request_id"]
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)
        command_path=self.stage/"production-worker.commands"
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            actual=[json.loads(line) for line in command_path.read_text().splitlines()] if command_path.exists() else []
            if any(c.get("op")=="notification_local_remove" for c in actual):break
            time.sleep(.05)
        removals=[c for c in actual if c.get("op")=="notification_local_remove"]
        self.assertEqual(len(removals),1,"actual Panel command must traverse production stdin exactly once: "+repr(actual))
        self.assertEqual(removals[0]["request_id"],pending)
        self.assertEqual(removals[0]["entries"],[{"device":"fixture_phone","id":"n",
            "occurrence_id":before_remove["left"]["notification"]["note"]["occurrence_id"],"closed":False}])
        self.assertTrue(state["sameService"],repr(state))
        state_path=self.stage/"state/omarchy-pocket-extended/notification-removals-v1.json"
        saved=json.loads(state_path.read_text())
        command_path=self.stage/"production-worker.commands"
        self.assertTrue(saved["entries"][0]["removed"],repr(saved)+"\nbefore_remove="+repr(before_remove)+"\nstate="+repr(state)+"\nframes="+(self.stage/"production-worker.frames").read_text()+"\ncalls="+(self.stage/"production-worker.calls").read_text()+"\ncommands="+(command_path.read_text() if command_path.exists() else "<none>"))

        first_pid=int((self.stage/"production-worker.pid").read_text())
        os.kill(first_pid,signal.SIGKILL)
        deadline=time.monotonic()+12
        second_pid=first_pid
        while time.monotonic()<deadline:
            pidfile=self.stage/"production-worker.pid"
            if pidfile.exists():
                try:second_pid=int(pidfile.read_text())
                except ValueError:second_pid=first_pid
                if second_pid!=first_pid:break
            time.sleep(0.1)
        self.assertNotEqual(second_pid,first_pid,"production worker did not restart")
        state=self.wait_state(lambda x:x["serviceReady"] and x["left"]["models"]==0 and x["right"]["models"]==0,timeout=12)
        self.assertTrue(state["sameService"])
        frames=[json.loads(line) for line in (self.stage/"production-worker.frames").read_text().splitlines()]
        readies=[e for e in frames if e.get("event")=="ready"]
        notes=[e for e in frames if e.get("event")=="notification"]
        self.assertGreaterEqual(len(readies),2)
        self.assertEqual(readies[-1]["notification_epoch"],notes[-1]["notification_epoch"])
        self.assertEqual(readies[-1]["notification_removals"][0]["occurrence_id"],saved["entries"][0]["occurrence_id"])

        # A genuinely fresh synthetic Quickshell process hydrates the durable
        # removal before its worker's active-notification snapshot is consumed.
        state=self.restart_fixture_process()
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)
        self.assertTrue(state["sameService"])
        active_file=self.stage/"active-notifications.json"
        (self.stage/"production-worker.control").write_text(json.dumps({"type":"signal","path":"/modules/kdeconnect/devices/fixture_phone/notifications","interface":"org.kde.kdeconnect.device.notifications","member":"notificationRemoved","args":["n"]}))
        state=self.wait_state(lambda x:len(x["serviceOccurrences"])==0)
        (self.stage/"production-worker.control").write_text(json.dumps({"type":"signal","path":"/modules/kdeconnect/devices/fixture_phone/notifications","interface":"org.kde.kdeconnect.device.notifications","member":"notificationPosted","args":["n"]}))
        state=self.wait_state(lambda x:x["left"]["models"]==1 and x["right"]["models"]==1,timeout=10)
        new_occurrence=state["left"]["notification"]["note"]["occurrence_id"]
        self.assertNotEqual(new_occurrence,saved["entries"][0]["occurrence_id"])
        self.assertEqual(state["right"]["notification"]["note"]["occurrence_id"],new_occurrence)
        self.assertEqual(len([e for e in self.production_frames() if e.get("event")=="ready"]),3)

    def production_frames(self):
        path=self.stage/"production-worker.frames"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_f1_actual_panels_submit_only_the_initiating_editor_text(self):
        state = self.call("seed")
        self.assertTrue(state["sameService"])
        state = self.call("recreateRight")
        self.assertEqual(state["right"]["models"], 1, "a recreated panel must snapshot shared notifications")
        self.call("editA")
        self.call("editB")
        state = self.call("inspect")
        self.assertEqual(state["left"]["editor"], "Draft A shown on left")
        self.assertEqual(state["right"]["editor"], "Draft B written on right")
        self.assertTrue(state["left"]["sendEnabled"])
        self.call("sendA")
        deadline = time.monotonic() + 5
        commands = []
        while time.monotonic() < deadline:
            commands = [e["command"] for e in self.worker_log() if e["kind"] == "command"]
            if any(c.get("op") == "notification_reply" for c in commands):
                break
            time.sleep(0.05)
        replies = [c for c in commands if c.get("op") == "notification_reply"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["text"], "Draft A shown on left")
        self.assertEqual(replies[0]["occurrence_id"],state["left"]["notification"]["note"]["occurrence_id"])
        self.assertEqual(replies[0]["notification_epoch"],state["workerEpoch"])
        deadline = time.monotonic() + 5
        state = self.call("inspect")
        while time.monotonic() < deadline and not state["right"]["notification"]["unavailable"]:
            time.sleep(0.05)
            state = self.call("inspect")
        self.assertEqual(state["right"]["editor"], "Draft B written on right")
        self.call("replySuccess")
        state=self.call("inspect")
        self.assertTrue(state["right"]["notification"]["unavailable"])

    def test_pr2_worker_device_event_is_sanitized_before_panel_consumption(self):
        state=self.call("deviceOversize")
        self.assertEqual(state["lastDeviceEvent"]["id"],"fake")
        self.assertEqual(state["lastDeviceEvent"]["name"],"Phone")
        self.assertFalse(state["lastDeviceEvent"]["name_valid"])
        self.assertEqual(state["lastDeviceEvent"]["plugins"],[])
        self.assertEqual(state["lastDeviceEvent"]["capabilities"],"unavailable")
        self.assertNotIn("unknown",state["lastDeviceEvent"])
        self.assertLess(len(json.dumps(state["lastDeviceEvent"])),1024)

    def test_pr3_panel_recreation_restores_only_its_own_sms_and_notification_drafts(self):
        self.call("seed")
        self.call("editA");self.call("editB")
        # Invoke production state mutation methods in each live Panel.
        self.call("eval:left.item.auditDraftSms('left SMS draft');right.item.auditDraftSms('right SMS draft')")
        self.call("eval:right.item.auditPicker()")
        before=self.call("inspect")
        old_picker=before["right"]["sms"]["pickerRequest"]
        self.assertTrue(old_picker)
        self.assertNotEqual(before["left"]["draftSlot"],before["right"]["draftSlot"])
        self.assertEqual(sorted(before["left"]["serviceDraftSlots"]),["fixture:fixture-left","fixture:fixture-right"])
        self.call("recreateRight")
        deadline=time.monotonic()+5
        state=self.call("inspect")
        while time.monotonic()<deadline and (state["right"] is None or state["right"]["models"]!=1):
            time.sleep(.05);state=self.call("inspect")
        self.assertEqual(state["left"]["notification"]["draft"],"Draft A shown on left")
        self.assertEqual(state["right"]["notification"]["draft"],"Draft B written on right")
        self.assertEqual(state["left"]["sms"]["text"],"left SMS draft")
        self.assertEqual(state["right"]["sms"]["text"],"right SMS draft")
        self.assertEqual(state["right"]["sms"]["pickerRequest"],"")
        self.assertIn("Check the phone and file selection",state["right"]["sms"]["status"])
        self.call("eval:owner.messagingEvent({event:'files_selected',request_id:"+json.dumps(old_picker)+",files:[{path:'/tmp/late',name:'late'}],cancelled:false})")
        state=self.call("inspect")
        self.assertEqual(state["right"]["sms"]["files"],[])
        # Remove the sibling after its draft snapshot is saved, then consume
        # the capability while it is absent. Restoration must keep Service's
        # authoritative used-token status instead of replaying stale snapshot data.
        self.call("destroyRight")
        self.call("sendA")
        self.call("replySuccess")
        self.call("restoreRight")
        state=self.wait_state(lambda x:x["right"] is not None and x["right"]["notification"] is not None)
        self.assertEqual(state["right"]["notification"]["usedReply"],"reply1")
        self.assertFalse(state["right"]["sendEnabled"])
        # A restored draft remains scoped to its original occurrence after closure.
        self.call("removeFromPhone")
        state=self.wait_state(lambda x:x["right"]["notification"] is not None and x["right"]["notification"]["unavailable"])
        self.assertFalse(state["right"]["sendEnabled"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"]=="command" and e["command"].get("op")=="notification_reply"]),1)
        # A pending SMS submission is retained as uncertain draft text but is never replayed.
        self.call("eval:right.item.auditPendingSms('SMS pending at panel removal')")
        pending_before=self.call("inspect")["right"]["sms"]["pending"]
        sms_count_before=len([e for e in self.worker_log() if e["kind"]=="command" and e["command"].get("op")=="sms_send"])
        self.call("recreateRight")
        state=self.wait_state(lambda x:x["right"] is not None and x["right"]["sms"]["text"]=="SMS pending at panel removal")
        self.assertTrue(pending_before)
        self.assertEqual(state["right"]["sms"]["pending"],"")
        self.assertIn("Check the phone",state["right"]["sms"]["status"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"]=="command" and e["command"].get("op")=="sms_send"]),sms_count_before)

    def test_f2_missing_service_never_starts_panel_workers_and_recovers_shared_state(self):
        self.call("detach")
        state = self.call("refreshBoth")
        self.assertFalse(state["left"]["hasService"])
        self.assertFalse(state["right"]["hasService"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 1)
        state = self.call("reattach")
        self.assertTrue(state["sameService"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 1)
        panel_source = (ROOT / "Panel.qml").read_text()
        self.assertNotIn("messaging_service.py", panel_source)
        self.assertNotRegex(panel_source, r"Process\s*\{[^}]*messaging")

    def test_f2_initially_missing_scoped_service_stays_unavailable(self):
        state = self.call("inspect")
        self.assertFalse(state["left"]["hasService"])
        self.assertFalse(state["right"]["hasService"])
        self.call("refreshBoth")
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 0)
        self.call("createService")
        state = self.wait_ready()
        self.assertTrue(state["sameService"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 1)

    def test_f3_service_replacement_invalidates_old_pending_without_replay(self):
        self.call("smsLeft")
        left_pending = self.call("inspect")["left"]["sms"]["pending"]
        self.assertTrue(left_pending)
        old_epoch = self.call("inspect")["epoch"]
        self.call("destroyService")
        state = self.wait_ready()
        self.assertNotEqual(old_epoch, state["epoch"])
        self.call("smsRight")
        state = self.call("inspect")
        right_pending = state["right"]["sms"]["pending"]
        self.assertTrue(right_pending)
        self.assertNotEqual(left_pending, right_pending)
        self.call("resolveRight")
        state = self.call("inspect")
        self.assertEqual(state["left"]["sms"]["text"], "SMS left")
        self.assertFalse(state["left"]["sms"]["pending"])
        self.assertIn("Check the phone", state["left"]["sms"]["status"])
        self.assertEqual(state["right"]["sms"]["text"], "")
        self.assertNotIn("another handler is registered", (self.stage / "quickshell.log").read_text())
        sent = [e["command"] for e in self.worker_log() if e["kind"] == "command" and e["command"].get("op") == "sms_send"]
        self.assertEqual([c["text"] for c in sent], ["SMS left", "SMS right"])

    def test_n1_same_identity_update_and_success_allow_only_new_token(self):
        self.call("seed")
        self.call("editHold")
        self.call("sendA")
        first = self.call("inspect")
        self.assertTrue(first["left"]["notification"]["pending"])
        self.call("seed")
        self.assertFalse(self.call("inspect")["left"]["notification"]["unavailable"])
        self.call("replySuccess")
        used = self.call("inspect")["right"]["notification"]
        self.assertEqual(used["usedReply"], "reply1")
        self.assertFalse(self.call("inspect")["right"]["replyVisible"])
        self.call("seedChanged")
        self.call("editB")
        self.assertTrue(self.call("inspect")["right"]["sendEnabled"])
        self.call("sendB")
        commands = [e["command"] for e in self.worker_log() if e["kind"] == "command" and e["command"].get("op") == "notification_reply"]
        self.assertEqual([c["text"] for c in commands], ["HOLD: original reviewed draft", "Draft B written on right"])
        self.assertEqual([c["reply_id"] for c in commands], ["reply1", "reply2"])
        self.assertNotEqual(commands[0]["request_id"], commands[1]["request_id"])

    def test_n1_changed_token_before_failed_completion_can_be_reviewed_and_sent(self):
        self.call("seed")
        self.call("editHold")
        self.call("sendA")
        self.call("seedChanged")
        self.call("replyFailure")
        self.assertFalse(self.call("inspect")["left"]["sendEnabled"])
        self.call("reviewB")
        state = self.call("inspect")
        self.assertEqual(state["right"]["editor"], "Draft B reviewed on right")
        self.assertTrue(state["right"]["sendEnabled"])
        self.call("sendB")
        commands = [e["command"] for e in self.worker_log() if e["kind"] == "command" and e["command"].get("op") == "notification_reply"]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[-1]["reply_id"], "reply2")
        self.assertEqual(commands[-1]["text"], "Draft B reviewed on right")

    def test_n2_direct_service_destruction_invalidates_sms_and_picker_without_replay(self):
        self.call("smsLeft")
        self.call("pickerLeft")
        before = self.call("inspect")
        old_sms = before["left"]["sms"]["pending"]
        old_picker = before["left"]["sms"]["pickerRequest"]
        self.assertTrue(old_sms and old_picker)
        self.call("destroyServiceDirect")
        state = self.wait_ready()
        self.assertNotEqual(state["epoch"], before["epoch"])
        self.call("smsRight")
        self.call("resolveRight")
        state = self.call("inspect")
        self.assertEqual(state["left"]["sms"]["text"], "SMS left")
        self.assertEqual(state["left"]["sms"]["pending"], "")
        self.assertEqual(state["left"]["sms"]["pickerRequest"], "")
        self.assertIn("Check the phone", state["left"]["sms"]["status"])
        self.assertEqual(state["right"]["sms"]["text"], "")
        commands = [e["command"] for e in self.worker_log() if e["kind"] == "command"]
        self.assertEqual([c["op"] for c in commands], ["sms_send", "pick_files", "sms_send"])
        self.assertNotEqual(old_sms, state["right"]["sms"]["pending"])
        self.assertNotEqual(old_picker, state["right"]["sms"]["pending"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 2)

    def test_n2_direct_service_destruction_preserves_notification_drafts(self):
        self.call("seed")
        self.call("editHold")
        self.call("editB")
        self.call("sendA")
        self.call("destroyServiceDirect")
        state = self.wait_ready()
        self.assertEqual(state["left"]["editor"], "HOLD: original reviewed draft")
        self.assertEqual(state["right"]["editor"], "Draft B written on right")
        self.assertTrue(state["left"]["notification"]["unavailable"])
        self.assertTrue(state["right"]["notification"]["unavailable"])
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "command" and e["command"].get("op") == "notification_reply"]), 1)

    def test_n3_actual_emoji_choice_is_disabled_for_shared_pending(self):
        self.call("seed")
        self.call("editHold")
        self.call("editB")
        self.call("sendA")
        state = self.call("inspect")
        self.assertEqual(state["right"]["editor"], "Draft B written on right")
        self.assertTrue(state["right"]["emojiFound"])
        self.assertFalse(state["right"]["emojiEnabled"])
        self.assertFalse(state["right"]["pickerEnabled"])
        self.call("emojiB")
        state = self.call("inspect")
        self.assertEqual(state["right"]["editor"], "Draft B written on right")
        self.assertEqual(state["right"]["notification"]["draft"], "Draft B written on right")

    def test_f4_manual_refresh_after_bounded_retries_starts_one_worker(self):
        # Crash each successive worker to exercise the three bounded automatic
        # restarts, then confirm another crash leaves the worker exhausted.
        for expected_starts in (2, 3, 4):
            self.call("crash")
            self.wait_for_starts(expected_starts, timeout=8)
            self.wait_ready(timeout=5)
        self.call("crash")
        time.sleep(2.4)
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 4)
        self.call("refreshLeft")
        self.call("refreshRight")
        starts = self.wait_for_starts(5, timeout=5)
        time.sleep(0.2)
        self.assertEqual(len(starts), 5)
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "start"]), 5)
        self.assertEqual(len([e for e in self.worker_log() if e["kind"] == "command" and e["command"].get("op") == "audit_crash"]), 4)


    def test_a2_non_owner_action_completion_clears_only_stale_in_progress_status(self):
        self.call("seed")
        self.call("editHold")
        self.call("sendA")
        state=self.call("inspect")
        self.assertIn("in progress",state["right"]["notificationStatus"])
        self.call("replySuccess")
        state=self.call("inspect")
        self.assertEqual(state["right"]["notificationStatus"],"")
        self.assertFalse(state["right"]["notification"]["sharedPending"])

    def test_a2_non_owner_failed_action_clears_generic_progress_status(self):
        self.call("seed")
        self.call("editHold")
        self.call("sendA")
        self.assertIn("in progress",self.call("inspect")["right"]["notificationStatus"])
        self.call("replyFailure")
        state=self.call("inspect")
        self.assertEqual(state["right"]["notificationStatus"],"")
        self.assertFalse(state["right"]["notification"]["sharedPending"])

    def test_a2_non_owner_completion_preserves_stronger_used_token_warning(self):
        self.call("seed")
        self.call("editHold")
        self.call("editB")
        self.call("sendA")
        self.call("replySuccess")
        state=self.call("inspect")
        self.assertEqual(state["right"]["notificationStatus"],"Reply token was used on another panel. Draft saved.")
        self.assertNotIn("in progress",state["right"]["notificationStatus"])
        self.assertEqual(state["right"]["editor"],"Draft B written on right")

    def test_d1_shared_contact_success_resolves_both_panel_requests(self):
        self.call("startContactRequests")
        self.call("contactsError")
        state=self.call("inspect")
        self.assertEqual(state["left"]["sms"]["contactsError"],"Synthetic contact read failed")
        self.assertFalse(state["left"]["sms"]["contactsLoading"])
        self.assertTrue(state["right"]["sms"]["contactsLoading"])
        self.call("contactsSuccess")
        state=self.call("inspect")
        for side in ("left","right"):
            self.assertFalse(state[side]["sms"]["contactsLoading"])
            self.assertEqual(state[side]["sms"]["contactsError"],"")
            self.assertEqual(state[side]["sms"]["contacts"][0]["name"],"Alex")
            self.assertEqual(state[side]["sms"]["recipient"],"5550100")
            self.assertEqual(state[side]["sms"]["text"],"Contact draft")

    def test_h3_individual_remove_requires_draft_confirmation_and_syncs(self):
        self.call("seed")
        self.call("editA")
        self.call("removeFromPhone")
        state=self.wait_state(lambda x:x["left"]["notification"] and not x["left"]["notification"]["active"])
        self.assertEqual(state["left"]["notificationCount"],1)
        self.call("removeInactive")
        state=self.call("inspect")
        self.assertIn("remove:",state["left"]["confirmation"])
        self.call("confirmRemoval")
        state=self.wait_state(lambda x:x["left"]["notificationCount"]==0 and x["right"]["notificationCount"]==0)
        commands=[e["command"] for e in self.worker_log() if e["kind"]=="command"]
        self.assertFalse(any(c.get("op")=="notification_dismiss" for c in commands))

    def test_h3_clear_all_is_local_synchronized_and_survives_service_recreation(self):
        self.call("seed")
        self.call("seed2")
        self.call("editA")
        self.call("removeFromPhone")
        state=self.wait_state(lambda x:any(not x["left"]["notification"]["active"] for _ in [0] if x["left"]["notification"]))
        self.assertEqual(state["left"]["notificationCount"],2)
        self.call("clearAll")
        state=self.call("inspect")
        self.assertEqual(state["left"]["confirmation"],"clear-all")
        self.call("confirmRemoval")
        state=self.wait_state(lambda x:x["left"]["notificationCount"]==0 and x["right"]["notificationCount"]==0)
        self.call("replayOld")
        self.assertEqual(self.call("inspect")["left"]["notificationCount"],0)
        commands=[e["command"] for e in self.worker_log() if e["kind"]=="command"]
        self.assertFalse(any(c.get("op")=="notification_dismiss" for c in commands))
        self.call("destroyServiceDirect")
        state=self.wait_ready()
        self.call("replayOld")
        state=self.call("inspect")
        self.assertEqual(state["left"]["notificationCount"],0,repr(state))
        self.assertEqual(state["right"]["notificationCount"],0,repr(state))

    def test_h3_clear_all_skips_pending_cards_and_repeated_clear_is_idempotent(self):
        self.call("seed")
        self.call("seed2")
        self.call("editHold")
        self.call("sendA")
        self.call("clearAll")
        state=self.call("inspect")
        self.assertEqual(state["left"]["notificationCount"],1)
        self.assertEqual(state["right"]["notificationCount"],1)
        self.assertIn("still processing",state["left"]["message"],repr(state))
        self.assertIn("still processing",self.wait_state(lambda x:"still processing" in x["left"]["message"])["left"]["message"])
        self.call("replyFailure")
        self.call("clearAll")
        self.assertEqual(self.call("inspect")["left"]["confirmation"],"clear-all")
        self.call("confirmRemoval")
        state=self.wait_state(lambda x:x["left"]["notificationCount"]==0 and x["right"]["notificationCount"]==0)
        commands=[e["command"] for e in self.worker_log() if e["kind"]=="command"]
        self.assertEqual(sum(c.get("op")=="notification_reply" for c in commands),1)
        self.assertFalse(any(c.get("op")=="notification_dismiss" for c in commands))


    def test_f6_occurrence_metadata_is_bounded_and_restarts_by_epoch(self):
        state=self.call("capacityChurn")
        self.assertEqual(state["capacityObserved"].find("capacity reached")>=0,True)
        self.assertEqual(state["occurrenceCount"],1)
        self.assertEqual(state["revisionWatermark"],1)
        keys=list(state["serviceOccurrences"])
        self.assertFalse(any("stale" in key for key in keys))
        self.assertFalse(any("overflow" in key for key in keys))
        self.assertTrue(any("fresh" in key for key in keys))
        self.assertEqual((ROOT/"Service.qml").read_text().count("maxNotificationOccurrences: 4096"),1)

    def test_f7_hydration_warning_is_visible_and_only_clears_after_successful_hydration(self):
        state=self.call("stateErrorSequence")
        self.assertEqual(state["stateErrorObserved"][0],"Local notification state unavailable: fixture")
        self.assertEqual(state["stateErrorObserved"][1],"Local notification state unavailable: fixture")
        self.assertEqual(state["stateErrorObserved"][2],"")
        state=self.call("inspect")
        self.assertEqual(state["left"]["error"],"")

    def test_f4_orphaned_local_removal_is_uncertain_and_never_replayed(self):
        self.call("seed")
        self.call("editA")
        (self.stage/"hold-local-remove").touch()
        self.call("clearAll")
        self.call("confirmRemoval")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            held=[e for e in self.worker_log() if e["kind"]=="held_local_remove"]
            if held:break
            time.sleep(.05)
        self.assertTrue(held)
        state=self.call("inspect")
        old_request=state["left"]["notification"]["localRemovePending"]
        self.assertTrue(old_request)
        old_epoch=state["epoch"]
        self.call("destroyServiceDirect")
        state=self.wait_ready()
        self.assertNotEqual(old_epoch,state["epoch"])
        self.assertIn("may have completed",state["left"]["message"])
        self.assertFalse(state["left"]["notification"]["localRemovePending"])
        self.assertEqual(state["left"]["notification"]["draft"],"Draft A shown on left")
        self.call("injectOldRemoval")
        state=self.call("inspect")
        self.assertIn("may have completed",state["left"]["message"])
        self.assertFalse(state["left"]["notification"]["localRemovePending"])
        remove_commands=[e for e in self.worker_log() if e["kind"]=="command" and e["command"].get("op")=="notification_local_remove"]
        self.assertEqual(len(remove_commands),1)
        self.assertEqual(remove_commands[0]["command"]["request_id"],old_request)
        self.assertTrue(old_epoch)

    def test_s1_same_occurrence_replay_after_clear_stays_hidden_on_both_panels(self):
        self.call("seed")
        original=self.call("inspect")["left"]["notification"]["note"]["occurrence_id"]
        self.call("clearAll")
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)
        self.call("replaySameOccurrence")
        state=self.wait_state(lambda x:x["revisionWatermark"]>=2)
        self.assertTrue(state["sameService"])
        self.assertEqual(state["left"]["models"],0)
        self.assertEqual(state["right"]["models"],0)
        self.assertEqual(state["serviceRemovals"]['["fake","n"]'],original)

    def test_s1r_overlapping_empty_list_cannot_resurrect_panels(self):
        from messaging_service import Service
        from notification_removal_store import NotificationRemovalStore
        class HeldTransport:
            def __init__(self): self.calls=[]
            def call(self,*args): self.calls.append(args)
            def respond(self,index,value=(),error=None): self.calls[index][-1](value,error)
        self.wait_state(lambda x:x["deviceCount"]==1)
        (self.stage/"hold-local-remove").touch()
        transport=HeldTransport();events=[]
        backend=Service(transport,events.append,lambda:0,notification_state=NotificationRemovalStore(persistent=False))
        backend.devices["fake"]={"online":True,"generation":1,"plugins":["kdeconnect_notifications"]}
        backend.notification_epoch=self.call("inspect")["workerEpoch"]
        backend.read_notification("fake","n")
        property_read=max(i for i,c in enumerate(transport.calls) if c[2]=="GetAll")
        backend.refresh_notifications("fake")
        old_list=max(i for i,c in enumerate(transport.calls) if c[2]=="activeNotifications")
        props={"internalId":"internal-reviewed","replyId":"reply-reviewed","title":"Audit","appName":"Synthetic","text":"Observed", "dismissable":True}
        transport.respond(property_read,value=(props,))
        first=next(e for e in events if e["event"]=="notification")
        state=self.call("inject:"+json.dumps(first))
        self.assertEqual(state["left"]["models"],1)
        self.assertEqual(state["right"]["models"],1)
        old_occurrence=first["notification"]["occurrence_id"]

        # The initiating Panel creates the actual worker command. The fixture
        # holds its response so this production backend is the sole completer.
        self.call("clearAll");self.call("confirmRemoval")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            commands=[e["command"] for e in self.worker_log() if e["kind"]=="command" and e["command"].get("op")=="notification_local_remove"]
            if commands:break
            time.sleep(.05)
        self.assertEqual(len(commands),1)
        backend.command(commands[0])
        completion=events[-1]
        self.assertEqual(completion["event"],"notification_local_remove")
        self.call("inject:"+json.dumps(completion))
        transport.respond(old_list,value=([],))
        self.assertTrue(backend.notification_state.is_removed("fake","n",old_occurrence))
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)

        # Same capability remains suppressed until a newer empty snapshot.
        backend.read_notification("fake","n")
        transport.respond(max(i for i,c in enumerate(transport.calls) if c[2]=="GetAll"),value=(props,))
        self.call("inject:"+json.dumps(events[-1]))
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0);self.assertEqual(state["right"]["models"],0)
        self.assertEqual(events[-1]["notification"]["occurrence_id"],old_occurrence)

        backend.refresh_notifications("fake")
        fresh=max(i for i,c in enumerate(transport.calls) if c[2]=="activeNotifications")
        transport.respond(fresh,value=([],))
        closure=events[-1]
        self.assertEqual(closure["event"],"notification_removed");self.assertTrue(closure["authoritative"])
        self.call("inject:"+json.dumps(closure))
        backend.read_notification("fake","n")
        transport.respond(max(i for i,c in enumerate(transport.calls) if c[2]=="GetAll"),value=(props,))
        self.call("inject:"+json.dumps(events[-1]))
        state=self.wait_state(lambda x:x["left"]["models"]==1 and x["right"]["models"]==1)
        self.assertNotEqual(events[-1]["notification"]["occurrence_id"],old_occurrence)
        self.assertFalse(any(c[2] in ("dismiss","sendReply","sendSms") for c in transport.calls))
        worker_commands=[e["command"] for e in self.worker_log() if e["kind"]=="command"]
        self.assertEqual(sum(c.get("op")=="notification_local_remove" for c in worker_commands),1)

    def test_s4_real_production_startup_hydration_warning(self):
        # Corrupt private state is loaded by production main; real frames pass
        # through production Service into the actual labels in both Panels.
        state=self.wait_state(lambda x:x["left"]["models"]==1 and x["right"]["models"]==1 and bool(x["stateError"]),timeout=12)
        self.call("eval:left.item.auditGeometry();left.item.open();right.item.auditGeometry();right.item.open()")
        state=self.call("inspect")
        for side in ("left","right"):
            self.assertTrue(state[side]["warning"]["visible"],repr(state))
            self.assertIn("state could not be read safely",state[side]["warning"]["text"])
        frames=[json.loads(line) for line in (self.stage/"production-worker.frames").read_text().splitlines()]
        ready=next(e for e in frames if e.get("event")=="ready")
        note=next(e for e in frames if e.get("event")=="notification")
        self.assertTrue(ready["notification_state_error"])
        self.assertEqual(ready["notification_epoch"],note["notification_epoch"])
        self.call("refreshLeft")
        state=self.call("inspect")
        self.assertTrue(all(state[p]["warning"]["visible"] for p in ("left","right")))
        (self.stage/"active-notifications.json").write_text("[]")
        (self.stage/"production-worker.control").write_text(json.dumps({"type":"signal","path":"/modules/kdeconnect/devices/fixture_phone/notifications","interface":"org.kde.kdeconnect.device.notifications","member":"notificationRemoved","args":["n"]}))
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)
        self.assertTrue(all(state[p]["warning"]["visible"] for p in ("left","right")))
        (self.stage/"state/omarchy-pocket-extended/notification-removals-v1.json").write_text('{"schema":1,"entries":[]}')
        (self.stage/"active-notifications.json").write_text('["n"]')
        pid=int((self.stage/"production-worker.pid").read_text());os.kill(pid,signal.SIGKILL)
        state=self.wait_state(lambda x:x["serviceReady"] and not x["stateError"] and x["left"]["models"]==1 and x["right"]["models"]==1,timeout=15)
        self.assertTrue(all(not state[p]["warning"]["visible"] for p in ("left","right")))

    def test_s3_closed_cleanup_metadata_stays_bounded_over_300_real_panel_cycles(self):
        self.call("closedChurn")
        state=self.wait_state(lambda x:x["churnCompleted"]==300,timeout=100)
        self.assertTrue(state["sameService"])
        self.assertEqual(state["churnError"],"")
        self.assertEqual(state["serviceRemovals"],{})
        self.assertEqual(state["left"]["removalKeys"],[])
        self.assertEqual(state["right"]["removalKeys"],[])
        self.assertEqual(state["left"]["notificationCount"],0)
        self.assertEqual(state["right"]["notificationCount"],0)
        def no_phone_dismissal(log):
            return not any(entry.get("command",{}).get("op")=="notification_dismiss"
                           for entry in log if entry.get("kind")=="command")
        actual_log=self.worker_log()
        self.assertTrue(no_phone_dismissal(actual_log))
        synthetic=[{"kind":"command","command":{"op":"notification_dismiss","request_id":"guard"}}]
        self.assertFalse(no_phone_dismissal(synthetic),"positive guard must detect a nested phone dismissal command")

    def test_s4_hydration_warning_renders_with_active_and_zero_notifications(self):
        self.call("seed")
        self.call("stateErrorActive")
        state=self.call("inspect")
        for side in ("left","right"):
            self.assertTrue(state[side]["warning"]["exists"])
            self.assertTrue(state[side]["warning"]["visible"])
            self.assertIn("state unavailable",state[side]["warning"]["text"])
        self.assertEqual(state["stateErrorObserved"],["Local notification state unavailable: fixture"]*4)
        self.call("removeFromPhone")
        state=self.wait_state(lambda x:x["left"]["models"]==0 and x["right"]["models"]==0)
        for side in ("left","right"):
            self.assertTrue(state[side]["warning"]["visible"])
        self.call("stateErrorRecovered")
        state=self.call("inspect")
        for side in ("left","right"):
            self.assertFalse(state[side]["warning"]["visible"])

    def test_r1_fresh_process_keeps_removed_occurrence_hidden_on_both_panels(self):
        self.call("seed")
        self.call("clearAll")
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0)
        self.assertEqual(len(state["serviceRemovals"]),1)
        self.restart_fixture_process()
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0)
        self.assertEqual(state["right"]["models"],0)
        self.call("replayOld")
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0)
        self.assertEqual(state["right"]["models"],0)
        payload=json.loads((self.stage/"state/omarchy-pocket-extended/notification-removals-v1.json").read_text())
        self.assertEqual(payload["schema"],1)
        self.assertEqual(len(payload["entries"]),1)

    def test_r3_empty_internal_token_has_consistent_two_panel_suppression(self):
        self.call("seed")
        self.call("clearAll")
        self.call("replayOld")
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0)
        self.assertEqual(state["right"]["models"],0)
        (self.stage/"worker.jsonl").write_text("")
        # A record with an empty action token is still represented by an occurrence UUID.
        self.call("seedEmptyIdentity")
        state=self.call("inspect")
        self.assertTrue(state["left"]["notification"]["note"]["occurrence_id"])
        self.assertEqual(state["left"]["notification"]["note"]["internal_id"],"")
        self.call("clearAll")
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],0)

    def test_r4_reused_id_new_capability_is_new_occurrence_and_old_revision_is_ignored(self):
        self.call("seed")
        old=self.call("inspect")["left"]["notification"]["note"]["occurrence_id"]
        self.call("clearAll")
        self.call("removeFromPhone")
        self.call("seedChanged")
        state=self.call("inspect")
        self.assertEqual(state["left"]["models"],1)
        new=state["left"]["notification"]["note"]["occurrence_id"]
        self.assertNotEqual(old,new)
        self.call("replayOld")
        state=self.call("inspect")
        self.assertEqual(state["left"]["notification"]["note"]["occurrence_id"],new)
        self.assertEqual(state["right"]["notification"]["note"]["occurrence_id"],new)

    def test_r5_confirmation_cancels_when_selected_device_changes(self):
        self.call("seed")
        self.call("editA")
        self.call("clearAll")
        self.assertEqual(self.call("inspect")["left"]["confirmation"],"clear-all")
        self.call("changeDraftReturn")
        self.call("confirmRemoval")
        self.assertEqual(self.call("inspect")["left"]["confirmation"],"clear-all")
        self.call("deviceB")
        state=self.call("inspect")
        self.assertFalse(state["left"]["confirmation"])
        self.call("confirmRemoval")
        self.assertEqual(len(self.call("inspect")["serviceRemovals"]),0)

    def test_r5_confirmation_is_renewed_when_target_occurrence_set_changes(self):
        self.call("seed")
        self.call("editA")
        self.call("clearAll")
        self.assertEqual(self.call("inspect")["left"]["confirmation"],"clear-all")
        self.call("seed2")
        self.call("confirmRemoval")
        state=self.call("inspect")
        self.assertEqual(state["left"]["confirmation"],"clear-all")
        self.assertEqual(state["left"]["notificationCount"],2)
        self.call("confirmRemoval")
        state=self.wait_state(lambda x:x["left"]["notificationCount"]==0 and x["right"]["notificationCount"]==0)
        def no_phone_dismissal(log):
            return not any(entry.get("command",{}).get("op")=="notification_dismiss"
                           for entry in log if entry.get("kind")=="command")
        actual_log=self.worker_log()
        self.assertTrue(no_phone_dismissal(actual_log))
        synthetic=[{"kind":"command","command":{"op":"notification_dismiss","request_id":"guard"}}]
        self.assertFalse(no_phone_dismissal(synthetic),"positive guard must detect a nested phone dismissal command")

    def test_r6_complete_contact_recovery_clears_only_partial_warning(self):
        self.call("startContactRequests")
        self.call("inject:{\"event\":\"contacts\",\"device\":\"fake\",\"contacts\":[{\"name\":\"Alex\",\"numbers\":[{\"number\":\"5550100\",\"label\":\"Mobile\"}]}],\"skipped\":1}")
        state=self.call("inspect")
        self.assertTrue(state["left"]["sms"]["contactsWarning"])
        self.call("inject:{\"event\":\"contacts\",\"device\":\"fake\",\"contacts\":[{\"name\":\"Alex\",\"numbers\":[{\"number\":\"5550100\",\"label\":\"Mobile\"}]}],\"skipped\":0}")
        state=self.call("inspect")
        self.assertEqual(state["left"]["sms"]["contactsWarning"],"")
        self.assertEqual(state["left"]["sms"]["recipient"],"5550100")
        self.assertEqual(state["left"]["sms"]["text"],"Contact draft")

if __name__ == "__main__":
    unittest.main()
