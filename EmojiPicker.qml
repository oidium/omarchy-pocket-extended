pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC

Flow {
  id: picker
  required property var targetEditor
  property color ink: "white"
  property color accent: "cyan"
  property real unit: 1
  property var emoji: ["😀","😊","😂","🥰","😎","🤔","😢","🙏","👍","👋","👌","💪","❤️","🎉","✨","🔥","✅","💯","☕","🎂","🏠","🚗","📷","🐾"]
  spacing: 3 * unit
  function insertEmoji(value) {
    var p = targetEditor.selectionStart
    if (targetEditor.selectionEnd > p) targetEditor.remove(p, targetEditor.selectionEnd)
    targetEditor.insert(p, value)
    targetEditor.cursorPosition = p + value.length
    targetEditor.forceActiveFocus()
  }
  Repeater {
    model: picker.emoji
    QQC.Button {
      id: choice
      required property string modelData
      objectName: "emojiChoice"
      width: 34 * picker.unit; height: width
      focusPolicy: Qt.NoFocus
      text: modelData
      onClicked: picker.insertEmoji(modelData)
      contentItem: Text { text: choice.text; font.pixelSize: 20 * picker.unit; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
      background: Rectangle { radius: 4 * picker.unit; color: choice.hovered ? Qt.alpha(picker.accent,0.15) : Qt.alpha(picker.ink,0.035) }
    }
  }
}
