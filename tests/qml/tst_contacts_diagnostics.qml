import QtQuick
import QtTest
import "../.."
import "../../ComposerState.js" as Composer

TestCase {
  name:"ContactLoadingDiagnostics";width:460;height:800;visible:true;when:windowShown
  Component {id:factory;SmsComposer{width:420;workspaceMode:true;payload:({device:"phone",recipient:"5550100",text:"Draft",files:[],contacts:[],contactsLoading:false,contactsError:"",contactsRequest:"request-1",pending:"",pickerRequest:"",status:"",open:true,thread:""})}}
  function test_loading_empty_and_error_states_are_distinct() {
    var c=createTemporaryObject(factory,this),state=findChild(c,"contactsEmptyState"),search=findChild(c,"contactSearch")
    verify(c);tryCompare(state,"text","No synchronized contacts. Enter any phone number above.")
    c.payload=Object.assign({},c.payload,{contactsLoading:true})
    tryCompare(state,"text","Loading synchronized contacts…")
    var beforeRecipient=c.payload.recipient,beforeSearch=search.text
    c.payload=Object.assign({},c.payload,{contactsLoading:false,contactsError:"Contact service unavailable"})
    tryCompare(state,"text","Contacts unavailable: Contact service unavailable")
    compare(c.payload.recipient,beforeRecipient);compare(search.text,beforeSearch)
    var contacts=[{name:"Alex",numbers:[{number:"5550100",label:"mobile"}]}]
    c.payload=Object.assign({},c.payload,{contacts:contacts,contactsError:"Some entries were skipped"})
    verify(findChild(c,"contactsLoadWarning").visible)
    compare(c.payload.recipient,beforeRecipient)
  }
}
