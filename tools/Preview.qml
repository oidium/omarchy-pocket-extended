import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "Pocket" as Pocket

ShellRoot {
  property var fixtureDevices:[]
  QtObject {
    id: previewBar
    property string position: "top"
    property bool vertical: false
    property int barSize: 40
    property string fontFamily: Style.font.family
    property color barForeground: Color.foreground
    property color urgent: Color.urgent
    property color foreground: Color.foreground
    property color background: Color.background
    property bool foregroundAnimationEnabled: false
    property var activePopout: null
    property var clickTargets: []
    function showTooltip(item, text) {}
    function hideTooltip(item) {}
    function requestPopout(item) { activePopout = item }
    function releasePopout(item) { if (activePopout === item) activePopout = null }
  }
  PanelWindow {
    anchors { top: true; left: true; right: true }
    implicitHeight: 40
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.namespace: "pocket-extended-preview-bar"
    mask: Region { item: launcher }
    Rectangle {
      id: launcher
      anchors.right: parent.right
      width: 260; height: 40
      color: Color.background
      Text { anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "Extended · LOCAL PREVIEW"; color: Color.foreground; font.pixelSize: 12 }
      Pocket.Panel {
        id: pocket
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        previewMode: true; manageIpc: false; bar: previewBar
        Component.onCompleted: {
          dependencies = {"kdeconnect":true,"python-gobject":true,"sshfs":true,"kio-fuse":true,"nautilus":true,"omarchy-file-select":true}
          devices = [{id:"preview",name:"Demo Pixel",online:true,battery:86,charging:false,links:["LAN"],can:["kdeconnect_notifications","kdeconnect_sms","kdeconnect_sftp","kdeconnect_share","kdeconnect_findmyphone","kdeconnect_clipboard"],media:{player:"Preview player",playerList:["Preview player"],title:"A little music",artist:"Synthetic preview",volume:55,isPlaying:true}}]
          loaded = true; messagingReady = true
          fixtureDevices=JSON.parse(JSON.stringify(devices))
          messagingEvent({event:"contacts",device:"preview",contacts:[{name:"Avery Example",numbers:[{number:"5550100",label:"Mobile"}]}]})
          for(var i=1;i<=8;i++)messagingEvent({event:"message",message:{device_id:"preview",thread_id:"9",message_id:String(i),timestamp:Date.now()-(9-i)*60000,addresses:["5550100"],addresses_complete:true,body:i%2?"See you this afternoon 👋":"Sounds good — see you there!",direction:i%2?"incoming":"outgoing",state:i%2?"received":"sent",android_read:1,attachments:[]},conversation_token:"preview:9",reply_status:"individual",recipient_scope:["5550100"]})
          for(var j=1;j<=2;j++)messagingEvent({event:"message",message:{device_id:"preview",thread_id:"7",message_id:"a"+j,timestamp:Date.now()-(3-j)*120000,addresses:["5550120"],addresses_complete:true,body:j===1?"Are we still on for lunch?":"Table is booked for 12:30.",direction:j===1?"incoming":"outgoing",state:j===1?"received":"sent",attachments:[]},conversation_token:"preview:7",reply_status:"individual",recipient_scope:["5550120"]})
          for(var k=1;k<=2;k++)messagingEvent({event:"message",message:{device_id:"preview",thread_id:"11",message_id:"b"+k,timestamp:Date.now()-(3-k)*180000,addresses:["5550140"],addresses_complete:true,body:k===1?"The blue notebook arrived.":"Great, I will bring it tomorrow.",direction:k===1?"incoming":"outgoing",state:k===1?"received":"sent",attachments:[]},conversation_token:"preview:11",reply_status:"individual",recipient_scope:["5550140"]})
          messagingEvent({event:"threads_refreshed",device:"preview"})
          historyState.threads['["preview","9"]'].token="preview:9"
          historyState=Object.assign({},historyState)
          messagingEvent({event:"notification",notification:{device:"preview",id:"demo",internal_id:"demo",app:"Messenger · Preview",title:"Coffee plans",body:"Avery: See you at the gallery at 3. I will bring the blue notebook.",reply_id:"preview-only",dismissable:true,icon_path:"@PROJECT@/tests/fixtures/avatar #1.svg"}})
          messagingEvent({event:"notification",notification:{device:"preview",id:"demo-calendar",internal_id:"demo-calendar",app:"Calendar",title:"Studio visit",body:"Avery: Our appointment starts at 3:30 PM.",reply_id:"preview-calendar",dismissable:true,icon_path:""}})
          messagingEvent({event:"notification",notification:{device:"preview",id:"demo-parcel",internal_id:"demo-parcel",app:"Delivery",title:"Package update",body:"Your sketchbook order is ready for pickup.",reply_id:"",dismissable:true,icon_path:""}})
          Qt.callLater(open)
        }
      }
    }
  }
  IpcHandler {
    target: "pocket-extended-preview"
    function open(): void { pocket.open() }
    function close(): void { pocket.close() }
    function inspect(mode: string): string { return pocket.previewInspect(mode) }
    function scenario(mode: string): string {
      if(mode==="combined") {
        pocket.devices=JSON.parse(JSON.stringify(fixtureDevices));pocket.historyOpen=true
        pocket.messagingEvent({event:"call_events",calls:[{id:"incoming",device:"preview",kind:"incoming_event",name:"Long synthetic caller name for layout verification",number:"5550300",observed_at:Date.now(),presentation:"dedicated"},{id:"missed",device:"preview",kind:"missed_event",name:"Unknown caller",number:"",observed_at:Date.now()-60000,presentation:"dedicated"}]})
        pocket.openComposer("");pocket.smsField("recipient","5550100");pocket.smsField("text","SMS draft stays here 👋 世界")
        pocket.smsField("files",[{path:"/synthetic/report.pdf",name:"Synthetic attachment.pdf",size:2048}])
        pocket.previewInspect("reply")
      } else if(mode==="offline") {
        var offline=JSON.parse(JSON.stringify(fixtureDevices));offline[0].online=false;pocket.devices=offline
        pocket.messagingEvent({event:"device_offline",device:"preview"})
      } else if(mode==="long") {
        pocket.messagingEvent({event:"notification",notification:{device:"preview",id:"long",internal_id:"long",reply_id:"synthetic",dismissable:true,title:"LongContactName".repeat(30),app:"Synthetic notifications",body:"A long notification body with Unicode 👋 世界. ".repeat(100),icon_path:""}})
      } else if(mode==="empty") {
        pocket.devices=[];pocket.messagingEvent({event:"worker_stopped"});pocket.notificationCards={};pocket.syncNotificationCards()
      } else if(mode==="setup") {
        pocket.dependencies={kdeconnect:true,"python-gobject":true,sshfs:false,"kio-fuse":false,nautilus:false,"omarchy-file-select":false}
      } else if(mode==="draftcheck") {
        pocket.openComposer("");pocket.smsField("text","Kept across navigation 👋");pocket.openComposer("9");pocket.smsField("text","Separate thread draft");pocket.openComposer("")
        return JSON.stringify({manualDraft:pocket.smsComposer.text,threadDraft:pocket.smsDrafts['["preview","9"]'].text,notificationDraft:pocket.notificationCards['["preview","demo"]'].draft})
      }
      return pocket.previewInspect("top")
    }
    function exercise(mode: string): string {
      if(mode==="history")pocket.showHistory()
      else if(mode==="thread")pocket.openThread("9")
      else if(mode==="new")pocket.openComposer("")
      else if(mode==="close")pocket.closeWorkspace()
      else if(mode==="selected")pocket.showNotifications('["preview","demo"]')
      else if(mode==="all")pocket.showNotifications("")
      else if(mode==="pending") {
        pocket.openComposer("");pocket.smsField("recipient","5550100");pocket.smsField("text","Synthetic unsent 👋")
        pocket.smsComposer.pending="synthetic-request";pocket.saveComposer()
        pocket.manualSendView={request:"synthetic-request",visit:pocket.workspaceVisit}
      } else if(mode==="accepted")pocket.messagingEvent({event:"sms_result",request_id:"synthetic-request",device:"preview",accepted:true,uncertain:false})
      else if(mode==="failed")pocket.messagingEvent({event:"sms_result",request_id:"synthetic-request",device:"preview",accepted:false,error:"Synthetic failure"})
      else if(mode==="churn") {
        for(var i=0;i<100;i++)pocket.messagingEvent({event:"notification",notification:{device:"preview",id:"n"+i,internal_id:"n"+i,app:"Synthetic",title:"Notification "+i,body:"Long 👋 ".repeat(30),reply_id:"",dismissable:true,icon_path:""}})
      } else if(mode==="remove") {
        pocket.notificationEdit('["preview","demo"]',"begin","")
        pocket.notificationEdit('["preview","demo"]',"draft","Retained draft")
        Object.keys(pocket.notificationCards).forEach(function(k){pocket.messagingEvent({event:"notification_removed",device:"preview",id:pocket.notificationCards[k].note.id})})
      }
      var result=JSON.parse(pocket.previewInspect("inspect"))
      result.activeCount=pocket.activeNoteCount;result.retained=pocket.noteCount
      result.selected=pocket.selectedNotification;result.manualDraft=pocket.smsDrafts['["preview",""]']||null
      result.workerRestarts=pocket.messagingRestarts
      return JSON.stringify(result)
    }
    function quit(): void { Qt.quit() }
  }
}
