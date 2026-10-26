import QtQuick
import QtTest
import "../.."
TestCase {
  name:"SmsCapabilityReadiness";width:424;height:500;visible:true;when:windowShown
  Component {id:factory;SmsComposer {width:392;payload:({recipient:"5550100",text:"Ready",files:[],contacts:[],pending:"",pickerRequest:"",status:"",open:true,thread:""})}}
  function test_pending_disables_send_and_explains() {
    var c=createTemporaryObject(factory,this,{online:true,serviceReady:false,capabilityState:"pending"})
    verify(!findChild(c,"smsSend").enabled);compare(findChild(c,"smsCapabilityStatus").text,"Loading SMS capability…")
  }
  function test_confirmed_enables_send() {
    var c=createTemporaryObject(factory,this,{online:true,serviceReady:true,capabilityState:"available"})
    verify(findChild(c,"smsSend").enabled)
  }
  function test_unavailable_disables_send() {
    var c=createTemporaryObject(factory,this,{online:true,serviceReady:false,capabilityState:"unavailable"})
    verify(!findChild(c,"smsSend").enabled)
  }
  function test_group_reply_send_gate_blocks_even_with_valid_context() {
    var c=createTemporaryObject(factory,this,{online:true,serviceReady:true,capabilityState:"available",
      contextValid:true,replyStatus:"group",replyBlockMessage:"Group replies are unavailable for recipient safety.",
      payload:{recipient:"",text:"Reply",files:[],contacts:[],pending:"",pickerRequest:"",status:"",open:true,thread:"9"}})
    verify(!findChild(c,"smsSend").enabled)
    verify(findChild(c,"replyBlockNotice").text.indexOf("Group replies are unavailable")>=0)
  }
}
