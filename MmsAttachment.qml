pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC
import "MediaState.js" as Media

Column {
  id:card
  required property var descriptor
  property var mediaState: ({})
  property bool online:false
  property color ink:"white"
  property color accent:"cyan"
  property string fontFamily:"sans-serif"
  property real smallSize:12
  property real unit:1
  property real corner:8
  signal downloadRequested()
  signal openRequested()
  readonly property string previewSource:Media.thumbnail(descriptor)
  readonly property string kind:(descriptor.mime_type||"").split("/")[0]
  readonly property bool valid:Media.usable(descriptor)
  spacing:5*unit
  Image {
    id:preview;objectName:"mmsThumbnail"
    source:card.previewSource;sourceSize.width:160;sourceSize.height:110
    width:Math.min(parent.width,160*card.unit);height:status===Image.Ready?110*card.unit:0
    visible:status===Image.Ready;fillMode:Image.PreserveAspectFit;asynchronous:true;cache:false
  }
  Text {
    objectName:"mmsLabel";width:parent.width;textFormat:Text.PlainText;wrapMode:Text.Wrap
    font.family:card.fontFamily;font.pixelSize:card.smallSize;color:card.ink
    text:"MMS · "+(card.kind==="audio"?"Audio":card.kind==="video"?"Video":card.kind==="image"?"Image":"File")+(preview.visible?" preview":"")+"\n"+(card.descriptor.mime_type||"Unknown type")
  }
  Text {
    width:parent.width;text:card.descriptor.identifier||"";textFormat:Text.PlainText;elide:Text.ElideMiddle
    font.family:card.fontFamily;font.pixelSize:card.smallSize;color:Qt.alpha(card.ink,0.65)
  }
  Text {
    objectName:"mmsStatus";width:parent.width;textFormat:Text.PlainText;wrapMode:Text.Wrap
    font.family:card.fontFamily;font.pixelSize:card.smallSize;color:Qt.alpha(card.ink,0.65)
    text:!card.valid?"Attachment unavailable":card.mediaState.error||({loading:"Retrieving stored MMS attachment…",opening:"Opening…",downloaded:"Downloaded · stored MMS file"})[card.mediaState.status]||(!card.online?"Phone offline":"Available to request · full file not downloaded")
  }
  QQC.Button {
    id:action;objectName:"mmsAction"
    text:card.mediaState.status==="downloaded"?"Open file":card.mediaState.status==="error"?"Retry download":"Download file"
    enabled:card.valid&&card.online&&!card.mediaState.pending
    padding:6*card.unit;font.family:card.fontFamily;font.pixelSize:card.smallSize;opacity:enabled?1:0.45
    contentItem:Text{text:action.text;font:action.font;color:card.ink;textFormat:Text.PlainText}
    background:Rectangle{radius:card.corner;color:action.hovered?Qt.alpha(card.accent,0.15):"transparent";border.width:1;border.color:action.activeFocus?card.accent:Qt.alpha(card.ink,0.18)}
    onClicked:card.mediaState.status==="downloaded"?card.openRequested():card.downloadRequested()
  }
}
