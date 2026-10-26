pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC

Rectangle {
  id: card
  required property var payload
  property color ink: "white"
  property color accent: "cyan"
  property color fieldBackground: "#222222"
  property string fontFamily: "sans-serif"
  property real bodySize: 14
  property real smallSize: 12
  property real unit: 1
  property real corner: 8
  property bool workerReady: false
  property bool emojiOpen:false
  property bool expanded:false
  property bool showExpandControl:true
  readonly property bool editorFocused: editor.activeFocus
  readonly property bool replyAvailable: payload.active && !!payload.note.reply_id && payload.usedReply !== payload.note.reply_id
  signal editRequested()
  signal draftChanged(string text)
  signal discardRequested()
  signal replyRequested()
  signal dismissRequested()
  signal removeRequested()
  signal editorActivated()
  color: Qt.alpha(ink, 0.035)
  radius: corner
  implicitHeight: contents.implicitHeight + 24 * unit
  onPayloadChanged: {
    // Avoid resetting cursor/selection/focus during ordinary notification updates.
    if (editor.text !== payload.draft) editor.text = payload.draft
  }
  function focusEditor() { editor.forceActiveFocus(); editor.cursorPosition = editor.length }
  Column {
    id: contents
    x: 12 * card.unit; y: x
    width: parent.width - 24 * card.unit
    spacing: 6 * card.unit
    Row {
      width: parent.width; spacing: 8 * card.unit
      Image {
        id: avatar
        objectName: "notificationAvatar"
        width: visible ? 30 * card.unit : 0; height: width
        source: card.payload.note.icon_path && card.payload.note.icon_path[0] === "/"
          ? "file://" + card.payload.note.icon_path.split("/").map(encodeURIComponent).join("/") : ""
        visible: source.toString() !== "" && status !== Image.Error
        fillMode: Image.PreserveAspectFit
        sourceSize.width: 60; sourceSize.height: 60
        asynchronous: true
        cache:false
        // Notification icon/avatar only: no click handler or attachment semantics.
      }
      Column {
        width: parent.width - (avatar.visible ? avatar.width + parent.spacing : 0)
        spacing: 4 * card.unit
        CardText { width: parent.width; text: card.payload.note.app; color: card.accent; font.pixelSize: card.smallSize; elide: Text.ElideRight }
        CardText { id:notificationTitle;width: parent.width; text: card.payload.note.title; visible: text !== ""; font.bold: true; wrapMode: Text.WrapAnywhere; maximumLineCount:card.expanded?2147483647:3;elide:Text.ElideRight }
      }
    }
    CardText {
      id:notificationBody
      width: parent.width; text: card.payload.note.body; visible: text !== ""
      color: Qt.alpha(card.ink, 0.65); font.pixelSize: card.smallSize; wrapMode: Text.WrapAnywhere
      maximumLineCount:card.expanded?2147483647:8;elide:Text.ElideRight
    }
    SmallButton {objectName:"expandButton";text:card.expanded?"Less":"More";visible:card.showExpandControl&&(card.expanded||notificationBody.truncated||notificationTitle.truncated);onClicked:card.expanded=!card.expanded}
    Row {
      spacing: 6 * card.unit
      SmallButton {
        objectName: "replyButton"
        text: "Reply"; visible: card.replyAvailable && !card.payload.editing
        enabled: card.workerReady && !card.payload.pending && !card.payload.sharedPending
        onClicked: { card.editRequested(); Qt.callLater(card.focusEditor) }
      }
      SmallButton {
        objectName: "dismissButton"
        text: "Dismiss"; visible: card.payload.active && card.payload.note.dismissable
        enabled: card.workerReady && !card.payload.pending && !card.payload.sharedPending
        onClicked: card.dismissRequested()
      }
      SmallButton {
        objectName:"removeNotificationButton"
        text:"Remove";visible:!card.payload.active
        enabled:!card.payload.pending&&!card.payload.sharedPending&&!card.payload.localRemovePending
        onClicked:card.removeRequested()
      }
    }
    Column {
      width: parent.width; spacing: 6 * card.unit; visible: card.payload.editing
      CardText {
        width: parent.width; text: "Reply to " + card.payload.draftTitle
        font.pixelSize: card.smallSize; color: Qt.alpha(card.ink, 0.65); elide: Text.ElideRight
      }
      QQC.ScrollView {
        width: parent.width
        height: Math.min(120 * card.unit, Math.max(66 * card.unit, editor.implicitHeight))
        clip: true
        QQC.TextArea {
          id: editor
          objectName: "replyEditor"
          width: parent.width
          text: card.payload.draft
          textFormat: TextEdit.PlainText
          wrapMode: TextEdit.Wrap
          placeholderText: "Write a reply…"
          placeholderTextColor: Qt.alpha(card.ink, 0.45)
          color: card.ink; selectionColor: card.accent; selectedTextColor: card.fieldBackground
          font.family: card.fontFamily; font.pixelSize: card.bodySize
          padding: 8 * card.unit
          readOnly: !!card.payload.pending || !!card.payload.sharedPending
          selectByMouse: true
          background: Rectangle {
            color: card.fieldBackground; radius: card.corner
            border.width: 1; border.color: editor.activeFocus ? card.accent : Qt.alpha(card.ink, 0.2)
          }
          onTextChanged: if (text !== card.payload.draft) card.draftChanged(text)
          onActiveFocusChanged: if (activeFocus) card.editorActivated()
        }
      }
      Row {
        spacing: 6 * card.unit
        SmallButton {
          objectName: "sendReplyButton"
          text: (card.payload.pending || card.payload.sharedPending) ? "Sending…" : "Send"
          enabled: card.workerReady && !card.payload.pending && !card.payload.sharedPending && !card.payload.unavailable && card.replyAvailable && editor.text.trim().length > 0 && editor.text.length <= 16384
          onClicked: card.replyRequested()
        }
        SmallButton {
          objectName: "discardDraftButton"
          text: "Discard draft"; enabled: !card.payload.pending && !card.payload.sharedPending
          onClicked: card.discardRequested()
        }
        SmallButton {objectName:"replyEmojiButton";text:"Emoji";focusPolicy:Qt.NoFocus;enabled:!card.payload.pending&&!card.payload.sharedPending;onClicked:card.emojiOpen=!card.emojiOpen}
      }
      EmojiPicker {objectName:"replyEmojiPicker";width:parent.width;visible:card.emojiOpen;targetEditor:editor;ink:card.ink;accent:card.accent;unit:card.unit;enabled:!card.payload.pending&&!card.payload.sharedPending}
    }
    CardText {
      objectName: "notificationStatus"
      width: parent.width; visible: text !== ""; text: card.payload.status
      font.pixelSize: card.smallSize; color: Qt.alpha(card.ink, 0.7); wrapMode: Text.WordWrap
    }
  }
  component CardText: Text {
    textFormat: Text.PlainText; color: card.ink
    font.family: card.fontFamily; font.pixelSize: card.bodySize
  }
  component SmallButton: QQC.Button {
    id: control
    font.family: card.fontFamily; font.pixelSize: card.smallSize
    padding: 6 * card.unit
    opacity: enabled ? 1 : 0.45
    contentItem: Text {
      text: control.text; font: control.font; color: card.ink
      horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
      radius: card.corner; color: control.hovered ? Qt.alpha(card.accent, 0.15) : "transparent"
      border.width: 1; border.color: control.activeFocus ? card.accent : Qt.alpha(card.ink, 0.18)
    }
  }
}
