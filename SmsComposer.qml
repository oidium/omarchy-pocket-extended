pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC
import "ComposerState.js" as ComposerState

Rectangle {
  id: composer
  required property var payload
  property bool online: false
  property bool serviceReady: false
  property string capabilityState: "pending"
  property bool contextValid:true
  property string replyStatus:"unknown"
  property string replyBlockMessage:""
  property bool pickerAvailable:true
  property color ink: "white"
  property color accent: "cyan"
  property color fieldBackground: "#222222"
  property string fontFamily: "sans-serif"
  property real bodySize: 14
  property real smallSize: 12
  property real unit: 1
  property real corner: 8
  property bool workspaceMode: false
  property bool contactsOpen: false
  property bool emojiOpen: false
  readonly property bool inputFocused: toField.activeFocus || messageEditor.activeFocus || search.activeFocus
  signal fieldEdited(string field, string value)
  signal attachRequested()
  signal removeRequested(string path)
  signal sendRequested()
  signal editorActivated()
  signal closeRequested()
  signal discardRequested()
  implicitHeight: contents.implicitHeight + 24 * unit
  color: Qt.alpha(ink,0.035); radius: corner
  onPayloadChanged: {
    if (toField.text !== payload.recipient) toField.text=payload.recipient
    if (messageEditor.text !== payload.text) messageEditor.text=payload.text
    syncContactRows()
  }
  function focusMessage() { messageEditor.forceActiveFocus() }
  function focusComposer() { if(payload.thread)messageEditor.forceActiveFocus();else toField.forceActiveFocus() }
  function resetContactView() {
    contactsOpen=false
    search.text=""
    syncContactRows()
  }
  ListModel { id:contactRows; dynamicRoles:true }
  function syncContactRows() {
    if (!contactRows) return
    contactRows.clear()
    if (composer.payload.thread || (composer.workspaceMode && !composer.contactsOpen)) return
    var choices=ComposerState.contactChoices(composer.payload.contacts || [], search.text || "")
    choices.forEach(function(choice) { contactRows.append(choice) })
  }
  onContactsOpenChanged: syncContactRows()
  FontMetrics {id:contactMetrics;font.family:composer.fontFamily;font.pixelSize:composer.smallSize}
  Column {
    id: contents
    x: 12 * composer.unit; y: x
    width: parent.width - 24 * composer.unit
    spacing: 8 * composer.unit
    Row {
      visible:!composer.workspaceMode || !!composer.payload.thread
      width: parent.width
      Copy { width: parent.width-close.width; text: composer.payload.thread?"REPLY · SMS / MMS":"NEW SMS / MMS"; font.bold:true; color:composer.accent }
      Action { id: close; text:"Close"; onClicked:composer.closeRequested() }
    }
    Column {
      objectName:"contactInstructions";width:parent.width;spacing:4*composer.unit
      visible:!composer.payload.thread
      Copy {objectName:"contactBrowseHint";width:parent.width;wrapMode:Text.Wrap;text:"SELECT CONTACTS TO BROWSE SYNCHRONIZED CONTACTS";font.pixelSize:composer.smallSize}
      Copy {objectName:"contactLimitHint";width:parent.width;wrapMode:Text.Wrap;text:"Up to 100 matches. Narrow your search for more.";font.pixelSize:composer.smallSize}
    }
    Row {
      visible:!composer.payload.thread
      width: parent.width; spacing: 6 * composer.unit
      Field {
        id: toField; objectName:"smsRecipient"
        width: parent.width - (contacts.visible ? contacts.width+parent.spacing : 0)
        placeholderText:"To: Enter number…"
        text:composer.payload.recipient
        readOnly:!!composer.payload.pending
        onTextChanged:if(text!==composer.payload.recipient)composer.fieldEdited("recipient",text)
        onActiveFocusChanged:if(activeFocus)composer.editorActivated()
        Keys.onPressed:function(event) {
          if (!(event.modifiers & Qt.KeypadModifier)) return
          if (event.key < Qt.Key_0 || event.key > Qt.Key_9) return
          var digit=String.fromCharCode("0".charCodeAt(0)+event.key-Qt.Key_0)
          insert(cursorPosition,digit);event.accepted=true
        }
      }
      Action {
        id:contacts; objectName:"contactsButton"
        text:composer.contactsOpen?"Hide contacts":"Contacts"; visible:composer.workspaceMode || composer.payload.contacts.length>0
        enabled:!composer.payload.pending
        onClicked:{ composer.contactsOpen=!composer.contactsOpen; if(composer.contactsOpen){search.text="";search.forceActiveFocus()} }
      }
    }
    Column {
      width:parent.width;spacing:4*composer.unit
      visible:!composer.payload.thread && (composer.workspaceMode || composer.contactsOpen)
        Field { id:search;objectName:"contactSearch";width:parent.width;placeholderText:"Search contacts by name or number…";enabled:!composer.payload.pending;onTextChanged:{if(text.length)composer.contactsOpen=true;composer.syncContactRows()} }
      QQC.ScrollView {
        id:contactViewport;objectName:"contactViewport"
        width:parent.width;height:4*(2*contactMetrics.height+12*composer.unit)
        // Do not derive this from ScrollView's internal contentItem: it can
        // collapse to zero width when clear/repopulate briefly empties the list.
        contentWidth:availableWidth
        contentHeight:contactList.implicitHeight
        clip:true
        Column {
          id:contactList;objectName:"contactList";width:contactViewport.availableWidth
          Repeater {
            objectName:"contactRepeater"
            model:contactRows
            Action {
              required property var modelData
              width:contactList.width
              text:modelData.name+" · "+modelData.label+"\n"+modelData.number
              enabled:!composer.payload.pending
              onClicked:{composer.fieldEdited("recipient",modelData.number);composer.contactsOpen=false;messageEditor.forceActiveFocus()}
            }
          }
        }
        Copy {
          parent:contactViewport
          x:8*composer.unit;y:8*composer.unit;width:parent.width-16*composer.unit
          objectName:"contactsEmptyState";visible:contactRows.count===0
          text:!composer.payload.contacts.length
            ? (composer.payload.contactsLoading?"Loading synchronized contacts…"
              : composer.payload.contactsError ? "Contacts unavailable: "+composer.payload.contactsError
              : "No synchronized contacts. Enter any phone number above.")
            : composer.contactsOpen?"No matching contacts":""
          font.pixelSize:composer.smallSize;color:Qt.alpha(composer.ink,0.65);wrapMode:Text.WordWrap
        }
      }
      Copy {objectName:"contactsLoadWarning";width:parent.width;visible:composer.payload.contacts.length>0&&!!(composer.payload.contactsError||composer.payload.contactsWarning);text:"Contacts warning: "+(composer.payload.contactsError||composer.payload.contactsWarning);wrapMode:Text.WordWrap;font.pixelSize:composer.smallSize;color:Qt.alpha(composer.ink,0.7)}
    }
    Copy {width:parent.width;visible:!!composer.payload.thread;text:"To: "+composer.payload.participants;wrapMode:Text.Wrap;font.pixelSize:composer.smallSize}
    Copy {objectName:"replyBlockNotice";width:parent.width;visible:!!composer.replyBlockMessage||!composer.contextValid;text:composer.replyBlockMessage||"Conversation changed. Draft preserved. Copy any text you need, then discard this draft to start a current reply.";wrapMode:Text.Wrap;font.pixelSize:composer.smallSize}
    QQC.ScrollView {
      width:parent.width;height:Math.min(150*composer.unit,Math.max(90*composer.unit,messageEditor.implicitHeight));clip:true
      QQC.TextArea {
        id:messageEditor;objectName:"smsText"
        width:parent.width;text:composer.payload.text;textFormat:TextEdit.PlainText;wrapMode:TextEdit.Wrap
        placeholderText:"Write an SMS/MMS message…";placeholderTextColor:Qt.alpha(composer.ink,0.45)
        color:composer.ink;selectionColor:composer.accent;selectedTextColor:composer.fieldBackground
        font.family:composer.fontFamily;font.pixelSize:composer.bodySize
        padding:8*composer.unit;selectByMouse:true;readOnly:!!composer.payload.pending
        background:Rectangle{color:composer.fieldBackground;radius:composer.corner;border.width:1;border.color:messageEditor.activeFocus?composer.accent:Qt.alpha(composer.ink,0.2)}
        onTextChanged:if(text!==composer.payload.text)composer.fieldEdited("text",text)
        onActiveFocusChanged:if(activeFocus)composer.editorActivated()
      }
    }
    Flow {
      width:parent.width;spacing:6*composer.unit
      Action {objectName:"attachButton";text:composer.payload.pickerRequest?"Choosing…":"Attach";enabled:composer.pickerAvailable&&composer.serviceReady&&!composer.payload.pickerRequest&&!composer.payload.pending;onClicked:composer.attachRequested()}
      Action {objectName:"emojiButton";text:"Emoji";focusPolicy:Qt.NoFocus;enabled:!composer.payload.pending;onClicked:composer.emojiOpen=!composer.emojiOpen}
      Action {objectName:"discardSmsDraft";text:"Discard draft";enabled:!composer.payload.pending&&!composer.payload.pickerRequest;onClicked:composer.discardRequested()}
    }
    EmojiPicker {objectName:"smsEmojiPicker";width:parent.width;visible:composer.emojiOpen;targetEditor:messageEditor;ink:composer.ink;accent:composer.accent;unit:composer.unit;enabled:!composer.payload.pending}
    Column {
      width:parent.width;spacing:4*composer.unit
      Repeater {
        model:composer.payload.files
        Row {
          id:fileRow
          required property var modelData
          width:parent.width
          Copy {width:parent.width-remove.width;text:fileRow.modelData.name+" · "+Math.ceil(fileRow.modelData.size/1024)+" KB";elide:Text.ElideMiddle;font.pixelSize:composer.smallSize;anchors.verticalCenter:parent.verticalCenter}
          Action {id:remove;objectName:"removeAttachment";text:"Remove";enabled:!composer.payload.pending;onClicked:composer.removeRequested(parent.modelData.path)}
        }
      }
    }
    Copy {width:parent.width;visible:composer.payload.files.length>0;text:"Attachment support and size limits depend on Android and your carrier.";font.pixelSize:composer.smallSize;color:Qt.alpha(composer.ink,0.65);wrapMode:Text.WordWrap}
    Flow {
      width:parent.width;spacing:6*composer.unit
      Action {
        objectName:"smsSend";text:composer.payload.pending?"Sending…":"Send SMS/MMS"
        enabled:composer.contextValid&&(!composer.payload.thread||composer.replyStatus==="individual")&&composer.online&&composer.serviceReady&&!composer.payload.pending&&!composer.payload.pickerRequest&&(!!composer.payload.thread||composer.payload.recipient.trim().length>0)&&(composer.payload.text.trim().length>0||composer.payload.files.length>0)
        onClicked:composer.sendRequested()
      }
      Copy {objectName:"smsCapabilityStatus";text:!composer.online?"Phone offline — draft saved":composer.capabilityState==="pending"?"Loading SMS capability…":composer.capabilityState==="unavailable"?"SMS unavailable in KDE Connect":"";font.pixelSize:composer.smallSize}
    }
    Copy {objectName:"smsStatus";width:parent.width;text:composer.payload.status;visible:text!=="";wrapMode:Text.WordWrap;font.pixelSize:composer.smallSize}
  }
  component Copy: Text {textFormat:Text.PlainText;color:composer.ink;font.family:composer.fontFamily;font.pixelSize:composer.bodySize}
  component Field: QQC.TextField {
    color:composer.ink;placeholderTextColor:Qt.alpha(composer.ink,0.45);font.family:composer.fontFamily;font.pixelSize:composer.bodySize
    selectByMouse:true;padding:8*composer.unit
    background:Rectangle{color:composer.fieldBackground;radius:composer.corner;border.width:1;border.color:parent.activeFocus?composer.accent:Qt.alpha(composer.ink,0.2)}
  }
  component Action: QQC.Button {
    id:button
    padding:6*composer.unit;font.family:composer.fontFamily;font.pixelSize:composer.smallSize
    opacity:enabled?1:0.45
    contentItem:Text{text:button.text;font:button.font;color:composer.ink;textFormat:Text.PlainText;elide:Text.ElideRight}
    background:Rectangle{radius:composer.corner;color:button.hovered?Qt.alpha(composer.accent,0.15):"transparent";border.width:1;border.color:button.activeFocus?composer.accent:Qt.alpha(composer.ink,0.18)}
  }
}
