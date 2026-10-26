pragma ComponentBehavior: Bound
import QtQuick

Rectangle {
  id: card
  required property var record
  property color ink: "white"
  property color accent: "cyan"
  property string fontFamily: "sans-serif"
  property real fontSize: 13
  property real unit: 1
  property real corner: 8
  implicitHeight: details.implicitHeight + 24 * unit
  radius: corner; color: Qt.alpha(ink, 0.035)
  Text {
    x: 12 * card.unit; y: 12 * card.unit; width: 30 * card.unit
    text: "☎︎"; color: card.accent; font.family:card.fontFamily;font.pixelSize: 25 * card.unit
    horizontalAlignment: Text.AlignHCenter
  }
  Column {
    id: details
    x: 50 * card.unit; y: 12 * card.unit
    width: parent.width - x - 12 * card.unit; spacing: 4 * card.unit
    Line {
      objectName: "callHeading"
      text: card.record.kind === "missed_event" ? "MISSED CALL" : "INCOMING CALL · REPORTED"
      color: card.accent; font.pixelSize: card.fontSize - 1
    }
    Line { text: card.record.name; font.bold: true }
    Line { text: card.record.number; visible: text !== "" && text !== card.record.name; color: Qt.alpha(card.ink, 0.65) }
    Line {
      text: "Observed " + Qt.formatDateTime(new Date(card.record.observed_at), "hh:mm:ss")
      font.pixelSize: card.fontSize - 1; color: Qt.alpha(card.ink, 0.65)
    }
  }
  component Line: Text {
    width: details.width; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
    font.family: card.fontFamily; font.pixelSize: card.fontSize; color: card.ink
  }
}
