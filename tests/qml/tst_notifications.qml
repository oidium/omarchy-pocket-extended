import QtQuick
import QtTest
import "../.."
import "../../NotificationState.js" as State

TestCase {
  id: testCase
  name: "InteractiveNotificationCard"
  width: 424; height: 600
  visible: true
  when: windowShown
  property var cards: ({})
  property var card
  Component {
    id: factory
    NotificationCard {
      width: 400; workerReady: true
      onEditRequested: { State.begin(testCase.cards[payload.key]); testCase.sync() }
      onDraftChanged: function(text) { testCase.cards[payload.key].draft = text; testCase.sync() }
      onDiscardRequested: { State.discard(testCase.cards[payload.key]); testCase.sync() }
    }
  }
  Component {
    id: listFactory
    Item {
      id: holder
      width: 400; height: 400
      property alias model: rows
      property alias repeater: repeater
      ListModel { id: rows; dynamicRoles: true }
      Repeater {
        id: repeater; model: rows
        NotificationCard {
          required property string cardKey
          width: 400; workerReady: true
          onDraftChanged: function(text) {
            var updated = JSON.parse(JSON.stringify(payload)); updated.draft = text
            rows.setProperty(0, "payload", updated)
          }
        }
      }
    }
  }
  function test_listmodel_refresh_keeps_delegate_and_focus() {
    State.begin(cards[State.key("phone","1")])
    var holder = createTemporaryObject(listFactory, testCase)
    holder.model.append({cardKey:State.key("phone","1"),payload:JSON.parse(JSON.stringify(cards[State.key("phone","1")]))})
    var delegate = holder.repeater.itemAt(0)
    verify(delegate !== null)
    delegate.focusEditor()
    var input = findChild(delegate,"replyEditor")
    input.insert(0,"Draft 👋"); input.cursorPosition = 2
    var updated = JSON.parse(JSON.stringify(holder.model.get(0).payload)); updated.note.body = "Refreshed"
    holder.model.setProperty(0,"payload",updated)
    compare(holder.repeater.itemAt(0),delegate)
    compare(delegate.payload.note.body,"Refreshed")
    compare(holder.model.get(0).payload.draft,"Draft 👋")
    compare(input.text,"Draft 👋"); compare(input.cursorPosition,2); verify(input.activeFocus)
  }
  function note(token, occurrence) { return {device:"phone",id:"1",occurrence_id:occurrence||"occurrence-1",notification_epoch:"worker-1",internal_id:"android",reply_id:token,app:"Chat",title:"Example",body:"A plain notification",dismissable:true,icon_path:""} }
  function sync() { card.payload = JSON.parse(JSON.stringify(cards[State.key("phone", "1")])) }
  function init() {
    cards = {}; State.receive(cards, {event:"notification",notification:note("token")})
    card = createTemporaryObject(factory, testCase, {payload:cards[State.key("phone","1")]})
    verify(card !== null)
  }
  function editor() { return findChild(card, "replyEditor") }
  function openEditor() { verify(findChild(card,"replyButton").visible); mouseClick(findChild(card,"replyButton")); compare(card.payload.editing,true); tryCompare(editor(), "activeFocus", true) }
  function test_refresh_preserves_text_cursor_focus() {
    openEditor(); editor().insert(0,"Hello 👋"); editor().cursorPosition = 2
    State.receive(cards,{event:"notification",notification:note("token")}); sync()
    compare(editor().text,"Hello 👋"); compare(editor().cursorPosition,2); verify(editor().activeFocus)
  }
  function test_emoji_inserts_at_cursor_without_changing_transport() {
    openEditor();editor().insert(0,"abc");editor().cursorPosition=1;card.emojiOpen=true
    findChild(card,"replyEmojiPicker").insertEmoji("🙂")
    compare(editor().text,"a🙂bc");compare(editor().cursorPosition,3);verify(editor().activeFocus)
    compare(cards[State.key("phone","1")].draft,"a🙂bc")
  }
  function test_long_notification_remains_compact() {
    var large=note("token");large.title="Name".repeat(100);large.body="Long text 👋 ".repeat(1000)
    State.receive(cards,{event:"notification",notification:large});sync();wait(20)
    verify(card.implicitHeight<450)
  }
  function test_replacement_keeps_editor_disables_send() {
    openEditor(); editor().insert(0,"Draft")
    State.receive(cards,{event:"notification",notification:note("replacement","occurrence-2")}); sync()
    compare(editor().text,"Draft"); verify(editor().visible)
    compare(findChild(card,"sendReplyButton").enabled,false)
    compare(findChild(card,"notificationStatus").text,"Reply no longer available")
  }
  function test_removed_keeps_editor_and_draft() {
    openEditor(); editor().insert(0,"Draft")
    State.receive(cards,{event:"notification_removed",device:"phone",id:"1"}); sync()
    compare(editor().text,"Draft"); verify(editor().visible)
    verify(!findChild(card,"dismissButton").visible)
  }
  function test_compact_theme_and_layout() {
    card.ink = "#d8dee9"; card.accent = "#88c0d0"; card.fieldBackground = "#242933"
    card.color = "#2e3440"
    openEditor(); editor().insert(0, "Thanks — see you soon 👋")
    verify(findChild(card,"sendReplyButton").enabled)
    verify(card.implicitHeight < 360)
    compare(editor().color, "#d8dee9")
    verify(grabImage(card).width > 0)
  }
  function test_local_avatar_and_remote_icon_rejection() {
    var n = note("token")
    n.icon_path = decodeURIComponent(Qt.resolvedUrl("../fixtures/avatar %231.svg").toString().replace(/^file:\/\//,""))
    State.receive(cards,{event:"notification",notification:n}); sync()
    var avatar = findChild(card,"notificationAvatar")
    tryCompare(avatar,"status",Image.Ready)
    verify(avatar.visible)
    n.icon_path = "https://example.invalid/attachment.jpg"
    State.receive(cards,{event:"notification",notification:n}); sync()
    compare(avatar.source.toString(),""); verify(!avatar.visible)
  }
  function test_contextual_controls_and_plain_text() {
    State.receive(cards,{event:"notification",notification:{device:"phone",id:"1",internal_id:"android",reply_id:"",app:"App",title:"Title",body:"<b>literal</b>",dismissable:false,icon_path:""}}); sync()
    verify(!findChild(card,"replyButton").visible); verify(!findChild(card,"dismissButton").visible)
    verify(!findChild(card,"notificationAvatar").visible)
  }
  function test_local_removal_preserves_reply_draft_and_exposes_remove() {
    openEditor();editor().insert(0,"Keep this draft")
    State.receive(cards,{event:"notification_local_remove",entries:[{key:State.key("phone","1"),occurrence_id:cards[State.key("phone","1")].note.occurrence_id}]})
    sync()
    compare(card.payload.active,false);compare(card.payload.draft,"Keep this draft")
    verify(card.payload.unavailable);verify(findChild(card,"removeNotificationButton").visible)
    verify(findChild(card,"removeNotificationButton").enabled)
    verify(findChild(card,"sendReplyButton").enabled===false)
  }
  function test_pending_local_removal_is_ignored() {
    openEditor();editor().insert(0,"Pending draft")
    cards[State.key("phone","1")].pending="request";cards[State.key("phone","1")].sharedPending="request";sync()
    State.receive(cards,{event:"notification_local_remove",entries:[{key:State.key("phone","1"),occurrence_id:cards[State.key("phone","1")].note.occurrence_id}]})
    sync()
    verify(card.payload.active);compare(card.payload.draft,"Pending draft")
  }
  function test_extended_card_can_hide_expand_control() {
    card.showExpandControl = false
    var n = note("token"); n.body = "Long body ".repeat(80)
    State.receive(cards,{event:"notification",notification:n}); sync(); wait(20)
    verify(!findChild(card,"expandButton").visible)
  }
}
