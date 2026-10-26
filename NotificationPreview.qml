import QtQuick
Rectangle {
  id:root
  required property var note
  property color ink:"white"
  property color accent:"cyan"
  property string fontFamily:"sans-serif"
  property real smallSize:12
  property real unit:1
  property real corner:8
  signal activated()
  implicitHeight:body.implicitHeight+16*unit
  color:Qt.alpha(ink,0.035);radius:corner
  activeFocusOnTab:visible
  border.width:activeFocus?1:0;border.color:accent
  Accessible.role:Accessible.Button;Accessible.name:note.app+": "+note.title
  Accessible.onPressAction:activated()
  Keys.onReturnPressed:activated()
  Keys.onSpacePressed:activated()
  TapHandler {onTapped:root.activated()}
  Column {
    id:body;x:8*root.unit;y:x;width:parent.width-2*x;spacing:4*root.unit
    Row {
      width:parent.width;spacing:6*root.unit
      Image {width:24*root.unit;height:width;source:root.note.icon_path&&root.note.icon_path[0]==="/"?"file://"+root.note.icon_path.split("/").map(encodeURIComponent).join("/"):"";visible:source.toString()!==""&&status!==Image.Error;fillMode:Image.PreserveAspectFit;asynchronous:true}
      Column {
        width:parent.width-30*root.unit
        Copy {width:parent.width;text:root.note.app;color:root.accent;elide:Text.ElideRight}
        Copy {width:parent.width;text:root.note.title;font.bold:true;elide:Text.ElideRight}
      }
    }
    Copy {width:parent.width;text:root.note.body;wrapMode:Text.WrapAnywhere;maximumLineCount:3;elide:Text.ElideRight}
  }
  component Copy:Text {textFormat:Text.PlainText;color:root.ink;font.family:root.fontFamily;font.pixelSize:root.smallSize}
}
