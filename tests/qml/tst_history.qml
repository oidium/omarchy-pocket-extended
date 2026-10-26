import QtQuick
import QtTest
import "../.."
import "../../HistoryState.js" as History
import "../../ComposerState.js" as Composer

TestCase {
  id:suite;name:"ConversationHistory";width:424;height:900;visible:true;when:windowShown
  Component {id:factory;ConversationView {width:392}}
  Component {id:composerFactory;SmsComposer {width:392}}
  SignalSpy {id:openSpy;signalName:"openThread"}
  SignalSpy {id:fieldSpy;signalName:"fieldEdited"}
  function record(id,kind) {return {device_id:"phone",thread_id:"9",message_id:String(id),timestamp:100000+id,addresses:["5550100","5550200"],body:"Hello 👋 世界",direction:kind===1?"incoming":"outgoing",state:kind===1?"received":"sent",android_read:1,attachments:[]}}
  function state() {var s=History.create();History.receive(s,{event:"message",message:record(1,1)});History.receive(s,{event:"message",message:record(2,2)});return s}
  function test_thread_open_and_incoming_outgoing_render() {
    var s=state(),view=createTemporaryObject(factory,suite,{historyData:s,device:"phone",online:true})
    verify(view!==null);var list=findChild(view,"historyList");compare(list.count,1)
    openSpy.target=view;openSpy.clear();wait(30)
    mouseClick(list,50,30);compare(openSpy.count,1);compare(openSpy.signalArguments[0][0],"9")
    view.thread="9";wait(30);compare(list.count,2)
    compare(list.itemAtIndex(0).record.direction,"outgoing");compare(list.itemAtIndex(1).record.direction,"incoming")
    compare(findChild(list.itemAtIndex(0),"historyBody").text,"Hello 👋 世界")
    verify(!findChild(view,"replyHistory").enabled)
    verify(findChild(view,"recipientScopeNotice").text.indexOf("Group replies are unavailable")>=0)
  }
  function test_live_updates_preserve_delegate_and_bounds() {
    var s=state(),view=createTemporaryObject(factory,suite,{historyData:s,device:"phone",thread:"9",online:true})
    var list=findChild(view,"historyList");wait(30);var old=list.itemAtIndex(0)
    History.receive(s,{event:"message",message:record(2,2)});view.historyData=Object.assign({},s);wait(30)
    compare(list.itemAtIndex(0),old);compare(list.count,2)
    for(var i=3;i<500;i++)History.receive(s,{event:"message",message:record(i,1)})
    view.historyData=Object.assign({},s);wait(30);compare(list.count,300);verify(list.height<=300)
    History.receive(s,{event:"device_offline",device:"phone"});view.historyData=Object.assign({},s)
    compare(list.count,0);verify(!findChild(view,"replyHistory").enabled)
  }
  function test_thread_list_fills_explicit_viewport() {
    var view=createTemporaryObject(factory,suite,{historyData:state(),device:"phone",online:true,height:520,fillViewport:true})
    var list=findChild(view,"historyList");wait(30)
    verify(list.height>300);verify(list.height<=view.height);verify(list.height+list.y<=view.height)
  }
  function test_reply_composer_context_and_cursor() {
    var p=Composer.create();p.thread="9";p.participants="Alex · 5550100";p.recipientScope=["5550100"];p.text="Hello 👋";p.open=true
    var c=createTemporaryObject(composerFactory,suite,{payload:p,online:true,serviceReady:true,replyStatus:"individual"})
    verify(c!==null);verify(!findChild(c,"smsRecipient").visible);verify(findChild(c,"smsSend").enabled)
    var editor=findChild(c,"smsText");editor.forceActiveFocus();editor.cursorPosition=3
    c.payload=Object.assign({},p);compare(editor.cursorPosition,3);verify(editor.activeFocus)
    var command=Composer.send(p,"phone","r","individual");compare(command.op,"sms_reply");compare(command.thread,"9")
    p=Composer.create();c.payload=p;verify(findChild(c,"smsRecipient").visible);verify(!findChild(c,"smsSend").enabled)
  }
  function test_thread_viewport_and_reply_control_follow_composer_space() {
    var s=state()
    for(var i=3;i<50;i++)History.receive(s,{event:"message",message:record(i,1)})
    var view=createTemporaryObject(factory,suite,{historyData:s,device:"phone",thread:"9",online:true,height:650,fillViewport:true})
    var list=findChild(view,"historyList"),reply=findChild(view,"replyHistory")
    wait(30);verify(reply.visible);verify(list.height>450)
    var full=list.height,footprint=view.height-list.height
    view.replyComposerVisible=true;view.height=350;wait(30)
    verify(!reply.visible);verify(findChild(view,"loadHistory").visible)
    compare(list.height,full-300);compare(view.height-list.height,footprint)
    verify(list.contentHeight>list.height);list.contentY=50;compare(list.contentY,50)
    view.replyComposerVisible=false;view.height=650;wait(30)
    verify(reply.visible);compare(list.height,full)
  }
  function test_missing_thread_and_theme() {
    var view=createTemporaryObject(factory,suite,{historyData:History.create(),device:"phone",thread:"absent",ink:"#dddddd",accent:"#88c0d0"})
    compare(findChild(view,"historyList").count,0);verify(!findChild(view,"replyHistory").enabled)
    verify(view.implicitHeight<500)
  }
  function test_keyboard_thread_activation() {
    var view=createTemporaryObject(factory,suite,{historyData:state(),device:"phone",online:true})
    var list=findChild(view,"historyList");wait(30);openSpy.target=view;openSpy.clear()
    list.itemAtIndex(0).forceActiveFocus();keyClick(Qt.Key_Return);compare(openSpy.count,1)
  }
  function test_stale_composer_cannot_send_but_preserves_text() {
    var p=Composer.create();p.thread="9";p.text="Keep this 👋"
    var c=createTemporaryObject(composerFactory,suite,{payload:p,online:true,serviceReady:true,contextValid:false,pickerAvailable:false})
    compare(findChild(c,"smsText").text,p.text);verify(!findChild(c,"smsSend").enabled);verify(!findChild(c,"attachButton").enabled)
    verify(findChild(c,"discardSmsDraft").enabled)
  }
  function test_workspace_contacts_button_opens_browse_without_search() {
    var p=Composer.create(); p.contacts=[{name:"Alex",numbers:[{label:"mobile",number:"5550100"}]}]
    var c=createTemporaryObject(composerFactory,suite,{payload:p,workspaceMode:true,online:true,serviceReady:true})
    var button=findChild(c,"contactsButton"); verify(button.visible); compare(button.text,"Contacts")
    mouseClick(button); wait(20); compare(button.text,"Hide contacts")
    var search=findChild(c,"contactSearch"); verify(search.visible)
    var rows=findChild(c,"contactRepeater")
    search.text=""; wait(20); compare(rows.count,1)
    fieldSpy.target=c;fieldSpy.clear();mouseClick(rows.itemAt(0));wait(20)
    compare(fieldSpy.count,1);compare(fieldSpy.signalArguments[0][0],"recipient")
    mouseClick(button);wait(20);compare(rows.count,1);mouseClick(button);wait(20);compare(rows.count,0);mouseClick(button);wait(20);compare(rows.count,1)
    search.text="a"; wait(20); compare(rows.count,1)
    search.text="b"; wait(20); compare(rows.count,0)
    search.text="a"; wait(20); compare(rows.count,1)
    search.text=""; wait(20); compare(rows.count,1)
  }
  function test_contact_view_reset_preserves_draft_but_rebuilds_later() {
    var p=Composer.create();p.text="Keep draft";p.contacts=[{name:"Alex",numbers:[{label:"mobile",number:"5550100"}]}]
    var c=createTemporaryObject(composerFactory,suite,{payload:p,workspaceMode:true})
    var button=findChild(c,"contactsButton"),rows=findChild(c,"contactRepeater")
    mouseClick(button);wait(20);compare(rows.count,1);c.resetContactView();compare(rows.count,0)
    mouseClick(button);wait(20);compare(rows.count,1);compare(findChild(c,"smsText").text,"Keep draft")
  }
  function test_manual_recipient_accepts_row_and_keypad_digits() {
    var p=Composer.create(),c=createTemporaryObject(composerFactory,suite,{payload:p,workspaceMode:true})
    var field=findChild(c,"smsRecipient");field.forceActiveFocus()
    keyClick(Qt.Key_1);keyClick(Qt.Key_2,Qt.KeypadModifier);keyClick(Qt.Key_3,Qt.KeypadModifier)
    compare(field.text,"123")
  }
}
