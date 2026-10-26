import QtQuick
import QtTest
import "../.."
TestCase {
  id:suite;name:"CompactNotificationPreview";width:400;height:400;when:windowShown
  Component {id:factory;NotificationPreview {width:360}}
  SignalSpy {id:spy;signalName:"activated"}
  function test_plain_text_bounded_keyboard_activation() {
    var c=createTemporaryObject(factory,suite,{note:{app:"Chat",title:"Example",body:"<b>literal</b> 👋 ".repeat(200),icon_path:""}})
    verify(c!==null);verify(c.implicitHeight<150)
    spy.target=c;c.forceActiveFocus();keyClick(Qt.Key_Return);compare(spy.count,1)
    keyClick(Qt.Key_Space);compare(spy.count,2)
  }
}
