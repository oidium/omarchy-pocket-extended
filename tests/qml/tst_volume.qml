import QtQuick
import QtTest
import "../.."

TestCase {
  id:suite;name:"MediaVolumePipeline";width:400;height:120;visible:true;when:windowShown
  Component {id:factory;MediaVolume {width:320;endpoint:"phone:player-session";remoteVolume:25}}
  SignalSpy {id:requests;signalName:"requested"}
  function test_external_updates_drag_echoes_release_and_failure() {
    var v=createTemporaryObject(factory,suite),s=findChild(v,"mediaVolumeSlider")
    requests.target=v;requests.clear();wait(20)
    v.remoteVolume=60;v.remoteRevision++;compare(v.shownValue,60)
    v.remoteVolume=20;v.remoteRevision++;compare(v.shownValue,20);compare(requests.count,0)
    mousePress(s,180,s.height/2);mouseMove(s,240,s.height/2);wait(130)
    compare(requests.count,1);var first=requests.signalArguments[0][0]
    var dragged=v.shownValue;v.remoteVolume=30;v.remoteRevision++;compare(v.shownValue,dragged)
    mouseMove(s,290,s.height/2);wait(130);compare(requests.count,1)
    mouseRelease(s,290,s.height/2);var released=v.shownValue;verify(released>80)
    v.result(first,true,"");wait(130);compare(requests.count,2)
    v.remoteVolume=87;v.remoteRevision++;compare(v.shownValue,released)
    v.result(requests.signalArguments[1][0],true,"");compare(v.shownValue,87)
    v.remoteVolume=13;v.remoteRevision++;compare(v.shownValue,13);compare(requests.count,2)
    mouseClick(s,100,s.height/2);wait(30);compare(requests.count,3)
    v.result(requests.signalArguments[2][0],false,"Disconnected");compare(v.shownValue,13)
    wait(150);compare(requests.count,3)
  }
  function test_endpoint_change_discards_old_results_without_replay() {
    var v=createTemporaryObject(factory,suite),s=findChild(v,"mediaVolumeSlider")
    requests.target=v;requests.clear();wait(20)
    mouseClick(s,200,s.height/2);verify(!!v.pending);var old=v.pending
    v.endpoint="phone:replacement";v.remoteVolume=42;compare(v.pending,"");compare(v.shownValue,42)
    v.result(old,true,"");compare(v.shownValue,42);wait(150);compare(requests.count,1)
  }
}
