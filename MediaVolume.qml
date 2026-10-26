pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC

// Device/player state is root-owned. Only the local gesture/one outstanding
// request lives here; no polling, persistent state, or alternate transport.
Item {
  id:root
  property string endpoint: ""
  property real remoteVolume: 0
  property int remoteRevision: 0
  property color accent: "cyan"
  property color trackColor: "#444"
  property real unit: 1
  property string pending: ""
  property int sequence: 0
  property var requestIdFactory: null
  property real wanted: -1
  property real sent: -1
  property real volumeBeforeSend: 0
  property bool settling: false
  readonly property bool dragging: slider.pressed
  readonly property real shownValue: slider.value
  signal requested(string request, int value)
  signal failed(string error)
  implicitHeight: 28*unit

  function cancel() {
    throttle.stop();reconcile.stop();pending="";wanted=-1;sent=-1;settling=false
    slider.value=remoteVolume
  }
  onEndpointChanged:cancel()
  onEnabledChanged:if(!enabled)cancel()
  function syncRemote() {
    if(slider.pressed || pending || wanted>=0)return
    if(settling && remoteVolume===volumeBeforeSend && remoteVolume!==sent)return
    settling=false;reconcile.stop();slider.value=remoteVolume
  }
  onRemoteVolumeChanged:syncRemote()
  onRemoteRevisionChanged:syncRemote()
  function flush() {
    if(!enabled || !endpoint || pending || wanted<0)return
    var next=wanted;wanted=-1
    if(next===sent)return
    volumeBeforeSend=remoteVolume;sent=next;settling=true
    pending=typeof requestIdFactory==="function"?requestIdFactory():"volume-"+(++sequence)
    requested(pending,Math.round(next))
  }
  function result(request,accepted,error) {
    if(request!==pending)return
    pending=""
    if(!accepted){wanted=-1;settling=false;reconcile.stop();if(!slider.pressed)slider.value=remoteVolume;failed(error);return}
    if(wanted>=0 && wanted!==sent){throttle.restart();return}
    wanted=-1
    if(!slider.pressed){reconcile.restart();syncRemote()}
  }
  Timer {id:throttle;interval:100;onTriggered:root.flush()}
  // Bounded echo wait: Android may quantize volume or omit a callback. Never
  // retry a write; eventually return to the last authoritative KDE value.
  Timer {id:reconcile;interval:1500;onTriggered:{root.settling=false;if(!slider.pressed&&!root.pending)slider.value=root.remoteVolume}}
  QQC.Slider {
    id:slider;objectName:"mediaVolumeSlider";anchors.fill:parent
    from:0;to:100;stepSize:1;live:true
    onMoved:{root.wanted=Math.round(value);if(!throttle.running)throttle.start()}
    onPressedChanged: {
      if(pressed){root.sent=-1;reconcile.stop()}
      else {throttle.stop();root.flush();if(!root.pending){reconcile.restart();root.syncRemote()}}
    }
    background:Rectangle {
      x:slider.leftPadding;y:slider.topPadding+slider.availableHeight/2-height/2
      width:slider.availableWidth;height:4*root.unit;radius:height/2;color:root.trackColor
      Rectangle {width:slider.visualPosition*parent.width;height:parent.height;radius:parent.radius;color:root.accent}
    }
    handle:Rectangle {
      x:slider.leftPadding+slider.visualPosition*(slider.availableWidth-width)
      y:slider.topPadding+(slider.availableHeight-height)/2
      width:12*root.unit;height:width;radius:width/2;color:root.accent
    }
  }
}
