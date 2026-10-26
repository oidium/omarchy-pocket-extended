pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC
import "HistoryState.js" as HistoryState
import "MediaState.js" as MediaState

Column {
  id: view
  required property var historyData
  property string device: ""
  property string thread: ""
  property bool online: false
  property var mediaStates: ({})
  signal mediaRequested(var message, var attachment, bool open)
  property color ink: "white"
  property color accent: "cyan"
  property color fieldBackground: "#222"
  property string fontFamily: "sans-serif"
  property real bodySize: 14
  property real smallSize: 12
  property real unit: 1
  property real corner: 8
  property real heightLimit: 0
  property bool fillViewport: false
  property bool replyComposerVisible: false
  readonly property real minimumViewportHeight: list.y + 64*unit + (threadActions.visible ? threadActions.height+historyFooter.height+spacing*2 : 0)
  readonly property var selected: historyData && historyData.threads[HistoryState.key(device,thread)] ? HistoryState.summary(historyData.threads[HistoryState.key(device,thread)]) : null
  signal openThread(string thread)
  signal backRequested()
  signal loadRequested()
  signal replyRequested()
  spacing: 8*unit
  ListModel { id: rows; dynamicRoles:true }
  function sync() {
    if(!historyData)return
    var current=historyData.threads[HistoryState.key(device,thread)]
    var items=thread ? (current ? HistoryState.messages(current) : []) : HistoryState.threads(historyData,device)
    var ids=items.map(function(v){return view.thread?v.message_id:v.id})
    for(var n=rows.count-1;n>=0;--n) if(ids.indexOf(rows.get(n).rowId)<0) rows.remove(n)
    for(var i=0;i<items.length;++i) {
      var found=-1
      for(var j=i;j<rows.count;++j) if(rows.get(j).rowId===ids[i]){found=j;break}
      var payload=JSON.parse(JSON.stringify(thread?items[i]:HistoryState.summary(items[i])))
      if(found<0) rows.insert(i,{rowId:ids[i],payload:payload})
      else {if(found!==i)rows.move(found,i,1);rows.setProperty(i,"payload",payload)}
    }
  }
  onHistoryDataChanged:sync()
  onThreadChanged:{ rows.clear();sync();list.positionViewAtBeginning() }
  onDeviceChanged:{ rows.clear();sync() }
  Component.onCompleted:sync()
  Row {
    width:parent.width;spacing:6*view.unit
    Action {objectName:"historyBack";visible:!!view.thread;text:"‹ Threads";onClicked:view.backRequested()}
    Copy {text:view.thread?"SMS / MMS HISTORY":"SMS / MMS THREADS";color:view.accent;font.bold:true;anchors.verticalCenter:parent.verticalCenter}
  }
  Copy {
    width:parent.width;visible:!!view.historyData && (!!view.historyData.errors[view.device] || view.historyData.available[view.device]===false)
    text:view.historyData?(view.historyData.errors[view.device] || "SMS/MMS is unavailable in KDE Connect for this device."):""
    color:Qt.alpha(view.ink,0.65);wrapMode:Text.Wrap;font.pixelSize:view.smallSize
  }
  Copy {
    objectName:"recipientScopeNotice"
    width:parent.width;visible:!!view.selected
    text:view.selected&&view.selected.head?HistoryState.participants(view.historyData,view.device,view.selected.head.addresses)+(HistoryState.replyBlockText(view.selected.replyStatus)?"\n"+HistoryState.replyBlockText(view.selected.replyStatus):""):""
    wrapMode:Text.Wrap;font.pixelSize:view.smallSize
  }
  Copy {
    width:parent.width;visible:!view.online || (!!view.selected&&view.selected.stale)
    text:!view.online?"Phone offline — saved previews may be out of date":"Refreshing available history…"
    color:Qt.alpha(view.ink,0.65);wrapMode:Text.Wrap;font.pixelSize:view.smallSize
  }
  ListView {
    id:list;objectName:"historyList"
    width:parent.width
    height:view.fillViewport
      ? Math.max(64*view.unit, view.height-list.y-(threadActions.visible ? threadActions.height+historyFooter.height+view.spacing*2 : 0))
      : (view.heightLimit>0?view.heightLimit:Math.min(300*view.unit,Math.max(64*view.unit,contentHeight)))
    clip:true;spacing:6*view.unit;model:rows;boundsBehavior:Flickable.StopAtBounds
    QQC.ScrollBar.vertical:QQC.ScrollBar {}
    delegate:Rectangle {
      id:row
      required property var payload
      required property string rowId
      required property int index
      activeFocusOnTab:true
      Accessible.role:Accessible.Button
      Accessible.name:row.message?"Message: "+row.record.body:"Conversation: "+HistoryState.participants(view.historyData,view.device,row.record.addresses)
      border.width:activeFocus?1:0;border.color:view.accent
      Keys.onReturnPressed:{if(row.message)row.expanded=!row.expanded;else view.openThread(row.rowId)}
      Keys.onSpacePressed:{if(row.message)row.expanded=!row.expanded;else view.openThread(row.rowId)}
      onActiveFocusChanged:if(activeFocus)list.positionViewAtIndex(index,ListView.Contain)
      property bool expanded:false
      readonly property bool message:!!view.thread
      readonly property var record:message?payload:payload.head
      width:list.width-8*view.unit;height:body.implicitHeight+16*view.unit
      color:Qt.alpha(row.message&&row.record.direction==="outgoing"?view.accent:view.ink,0.06)
      radius:view.corner
      Column {
        id:body;x:8*view.unit;y:x;width:parent.width-16*view.unit;spacing:4*view.unit
        Copy {
          width:parent.width;font.bold:true;font.pixelSize:view.smallSize
          text:row.message?HistoryState.sender(view.historyData,row.record):HistoryState.participants(view.historyData,view.device,row.record.addresses)
          wrapMode:Text.Wrap
        }
        Copy {
          objectName:"historyBody";width:parent.width;text:row.record.body || (row.record.attachments.length?"MMS attachment":"(No text)")
          wrapMode:Text.Wrap;maximumLineCount:row.expanded?2147483647:row.message?12:2;elide:Text.ElideRight
        }
        Repeater {
          model:row.message?row.record.attachments:[]
          MmsAttachment {
            required property var modelData
            width:body.width;descriptor:modelData
            mediaState:view.mediaStates[MediaState.key(row.record,modelData)]||({})
            online:view.online&&!!view.selected&&!view.selected.stale
            ink:view.ink;accent:view.accent;fontFamily:view.fontFamily;smallSize:view.smallSize;unit:view.unit;corner:view.corner
            onDownloadRequested:view.mediaRequested(row.record,modelData,false)
            onOpenRequested:view.mediaRequested(row.record,modelData,true)
          }
        }
        Copy {
          width:parent.width;wrapMode:Text.Wrap;font.pixelSize:view.smallSize;color:Qt.alpha(view.ink,0.6)
          text:HistoryState.timestamp(row.record.timestamp)+" · "+HistoryState.status(row.record)+(!row.message&&row.payload.stale?" · saved preview":"")
        }
      }
      TapHandler {onTapped:{if(row.message)row.expanded=!row.expanded;else view.openThread(row.rowId)}}
    }
    Copy {
      anchors.fill:parent;visible:rows.count===0;wrapMode:Text.Wrap;font.pixelSize:view.smallSize
      text:view.thread?"No history available yet.":view.historyData&&view.historyData.loaded[view.device]?"No SMS/MMS conversations available.":"Waiting for KDE Connect conversations…"
    }
  }
  Row {
    id:threadActions
    spacing:6*view.unit;visible:!!view.thread
    Action {objectName:"loadHistory";text:view.selected&&view.selected.pending?"Loading…":"Load earlier";enabled:view.online&&view.historyData.available[view.device]!==false&&!!view.selected&&!view.selected.stale&&!view.selected.pending;onClicked:view.loadRequested()}
    Action {objectName:"replyHistory";visible:!view.replyComposerVisible;text:"Reply by SMS/MMS";enabled:view.online&&view.historyData.available[view.device]!==false&&!!view.selected&&!view.selected.stale&&view.selected.replyStatus==="individual"&&!view.selected.replyBlocked;onClicked:view.replyRequested()}
  }
  Copy {
    id:historyFooter
    width:parent.width;visible:!!view.thread;wrapMode:Text.Wrap;font.pixelSize:view.smallSize;color:Qt.alpha(view.ink,0.65)
    text:(view.selected&&view.selected.status?view.selected.status+"\n":"")+"Newest first · available history may be incomplete."+(view.selected&&view.selected.bounded?"\nShowing a window of up to 300 messages.":"")
  }
  component Copy:Text {textFormat:Text.PlainText;color:view.ink;font.family:view.fontFamily;font.pixelSize:view.bodySize}
  component Action:QQC.Button {
    id:button;padding:6*view.unit;font.family:view.fontFamily;font.pixelSize:view.smallSize;opacity:enabled?1:0.45
    contentItem:Text{text:button.text;font:button.font;color:view.ink;textFormat:Text.PlainText}
    background:Rectangle{radius:view.corner;color:button.hovered?Qt.alpha(view.accent,0.15):"transparent";border.width:1;border.color:button.activeFocus?view.accent:Qt.alpha(view.ink,0.18)}
  }
}
