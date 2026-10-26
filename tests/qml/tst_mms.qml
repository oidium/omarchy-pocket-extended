import QtQuick
import QtTest
import "../.."

TestCase {
  id:suite;name:"MmsAttachment";width:424;height:600;visible:true;when:windowShown
  readonly property string png:"iVBORw0KGgoAAAANSUhEUgAAACAAAAAYCAIAAAAUMWhjAAAAJElEQVR4nGM4uzCCpohh1IJRC0YtGLVg1IJRC0YtGLVgaFgAAKsVUkxqWU2PAAAAAElFTkSuQmCC"
  Component {id:factory;MmsAttachment {width:360}}
  SignalSpy {id:downloads;signalName:"downloadRequested"}
  SignalSpy {id:opens;signalName:"openRequested"}
  function descriptor(mime,thumb) {return {part_id:"7",identifier:"photo",mime_type:mime,thumbnail_base64:thumb}}
  function test_decode_image_and_video_thumbnail() {
    for(var type of ["image/jpeg","video/mp4"]) {
      var card=createTemporaryObject(factory,suite,{descriptor:descriptor(type,png),online:true})
      var image=findChild(card,"mmsThumbnail");tryCompare(image,"status",Image.Ready)
      verify(image.visible);verify(image.height<=110);verify(card.implicitHeight<260)
      verify(findChild(card,"mmsLabel").text.indexOf("preview")>=0)
      compare(findChild(card,"mmsAction").text,"Download file")
    }
  }
  function test_audio_file_no_thumbnail_and_malformed() {
    for(var type of ["audio/ogg","application/pdf","video/mp4"]) {
      var card=createTemporaryObject(factory,suite,{descriptor:descriptor(type,"not-base64"),online:true})
      verify(!findChild(card,"mmsThumbnail").visible);verify(findChild(card,"mmsAction").enabled)
      verify(card.implicitHeight<180)
    }
    var broken=createTemporaryObject(factory,suite,{descriptor:{part_id:"?",identifier:""},online:true})
    verify(!findChild(broken,"mmsAction").enabled);compare(findChild(broken,"mmsStatus").text,"Attachment unavailable")
  }
  function test_download_never_opens_automatically() {
    var card=createTemporaryObject(factory,suite,{descriptor:descriptor("image/png",png),online:true})
    downloads.target=card;opens.target=card;downloads.clear();opens.clear()
    var action=findChild(card,"mmsAction");mouseClick(action);compare(downloads.count,1);compare(opens.count,0)
    card.mediaState={status:"loading",pending:"r"};verify(!action.enabled)
    card.mediaState={status:"downloaded",pending:""};compare(action.text,"Open file");compare(opens.count,0)
    mouseClick(action);compare(opens.count,1)
    card.mediaState={status:"error",error:"Missing file"};compare(action.text,"Retry download")
    card.online=false;verify(!action.enabled)
  }
}
