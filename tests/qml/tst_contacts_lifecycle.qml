import QtQuick
import QtTest
import "../.."
import "../../ComposerState.js" as Composer

TestCase {
  id:suite;name:"ContactsLifecycle";width:460;height:800;visible:true;when:windowShown
  Component {
    id:factory
    Item {
      id:host;width:440;height:740
      property var draft:Composer.create()
      property alias editor:editor
      Flickable {
        id:outer;anchors.fill:parent;clip:true;contentHeight:column.implicitHeight
        Column {
          id:column;width:parent.width
          SmsComposer {
            id:editor;width:parent.width;workspaceMode:true;payload:host.draft
            onFieldEdited:function(field,value) {
              host.draft[field]=value
              host.draft=Object.assign({},host.draft)
            }
          }
        }
      }
    }
  }
  function test_actual_feedback_and_scroll_geometry() {
    var p=Composer.create();p.open=true;p.text="Keep unsent draft 👋"
    for(var i=0;i<120;i++)p.contacts.push({name:(i%2?"Beta ":"Alpha ")+i,numbers:[{number:"555"+i,label:"Mobile"}]})
    var host=createTemporaryObject(factory,suite,{draft:p}),c=host.editor
    var button=findChild(c,"contactsButton"),search=findChild(c,"contactSearch"),rows=findChild(c,"contactRepeater")
    wait(50)
    var viewport=findChild(c,"contactViewport"),editor=findChild(c,"smsText"),recipient=findChild(c,"smsRecipient")
    var y=editor.mapToItem(c,0,0).y,height=viewport.height
    var instructions=findChild(c,"contactInstructions"),hint=findChild(c,"contactBrowseHint"),limit=findChild(c,"contactLimitHint")
    compare(hint.parent,limit.parent);compare(hint.parent,instructions)
    verify(instructions.y+instructions.height<=recipient.parent.y)
    verify(recipient.mapToItem(c,0,0).y<search.mapToItem(c,0,0).y)
    mouseClick(button);wait(50);compare(rows.count,100)
    var rowHeight=rows.itemAt(0).height
    verify(height>=3*rowHeight);verify(height<=4.5*rowHeight)
    verify(viewport.contentHeight>viewport.height)
    viewport.contentItem.contentY=80;compare(viewport.contentItem.contentY,80)
    for(var q of ["a","b","a","","nothing-matches","Beta 119","b"]) {
      search.text=q;wait(50)
      compare(rows.count,q==="nothing-matches"?0:q==="Beta 119"?1:q==="b"?60:100)
      if(rows.count){var row=rows.itemAt(0);verify(row.width>100);verify(row.height>10)}
      compare(viewport.height,height);compare(editor.mapToItem(c,0,0).y,y)
    }
    mouseClick(rows.itemAt(0));wait(50)
    compare(host.draft.recipient,"5551");verify(!c.contactsOpen)
    compare(host.draft.text,"Keep unsent draft 👋")
    compare(editor.mapToItem(c,0,0).y,y)
    recipient.forceActiveFocus();keyClick(Qt.Key_2);verify(host.draft.recipient.indexOf('2')>=0)
    mouseClick(button);wait(50);verify(rows.count>0)
    for(var i=0;i<3;i++) {
      mouseClick(button);wait(30);compare(rows.count,0)
      mouseClick(button);wait(30);compare(rows.count,100)
      verify(rows.itemAt(0).width>100);verify(findChild(c,"contactViewport").height>0)
      compare(editor.mapToItem(c,0,0).y,y);compare(viewport.height,height)
    }
    search.text="Alpha";wait(50);verify(rows.count>0)
    c.resetContactView();search.text="Beta";wait(50);compare(rows.count,60)
    compare(editor.mapToItem(c,0,0).y,y);compare(host.draft.text,"Keep unsent draft 👋")
    host.draft=Object.assign({},host.draft,{contacts:[]});wait(30)
    compare(editor.mapToItem(c,0,0).y,y);compare(viewport.height,height)
  }
}
