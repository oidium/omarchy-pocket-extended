import QtQuick
import QtTest
import "../.."

TestCase {
  id: suite
  name: "CallEventCard"
  width: 424; height: 600; visible: true
  when: windowShown
  Component { id: factory; CallCard { width: 392 } }
  function test_incoming_label_is_observation() {
    var card = createTemporaryObject(factory, suite, {record: {kind:"incoming_event",name:"Casey Example",number:"+15550100",observed_at:Date.now()}})
    verify(card !== null)
    compare(findChild(card,"callHeading").text,"INCOMING CALL · REPORTED")
    verify(card.implicitHeight < 160)
  }
  function test_missed_is_distinct_and_compact() {
    var card = createTemporaryObject(factory, suite, {record: {kind:"missed_event",name:"Unknown caller",number:"",observed_at:Date.now()}})
    compare(findChild(card,"callHeading").text,"MISSED CALL")
    verify(card.implicitHeight < 140)
  }
  function test_long_name_and_theme_fit() {
    var card = createTemporaryObject(factory, suite, {width:250,ink:"#dddddd",accent:"#88c0d0",record:{kind:"incoming_event",name:"A long caller name that should wrap gracefully",number:"+1 202-555-0149 ext 123456",observed_at:Date.now()}})
    verify(card.implicitHeight > 80)
    verify(card.implicitHeight < 240)
    compare(findChild(card,"callHeading").color,"#88c0d0")
  }
}
