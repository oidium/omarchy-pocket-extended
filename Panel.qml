pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "NotificationState.js" as NotificationState
import "ComposerState.js" as ComposerState
import "HistoryState.js" as HistoryState
import "MediaState.js" as MediaState

Panel {
  id: root
  property bool previewMode: false
  moduleName: "io.github.oidium.pocket-extended"
  // The shell-wide service owns the sole authoritative IPC handler. Preview
  // mode has no service and keeps the old local-only behavior.
  manageIpc: false
  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  readonly property var service: !previewMode && bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor(moduleName) : null
  property var localDependencies: ({})
  property var localDevices: []
  property bool localLoaded: false
  property string localConnectionError: ""
  property var localNotificationCards: ({})
  property var attachedService: null
  property string attachedServiceEpoch: ""
  property string clientId: ""
  property string attachedDraftSlot: ""
  // Used only by the synthetic two-panel fixture when no QWindow screen exists.
  property string panelDraftSlotOverride: ""
  readonly property string draftSlotIdentity: resolveDraftSlotIdentity()
  property bool localMessagingReady: false
  property string localMessagingError: ""
  property int localMessagingRestarts: 0
  property var localHistoryState: HistoryState.create()
  property var localMediaStates: ({})
  property var localRemoteMedia: ({})
  property var localCallEvents: []

  readonly property string bridge: decodeURIComponent(Qt.resolvedUrl("bridge.py").toString().replace(/^file:\/\//, ""))
  readonly property color ink: Color.popups.text
  readonly property color subdued: Qt.alpha(ink, 0.62)
  readonly property string face: bar ? bar.fontFamily : Style.font.family
  property var dependencies: service ? service.dependencies : localDependencies
  readonly property var missingDependencies: Object.keys(dependencies).filter(function(name) { return !dependencies[name] })
  readonly property bool missingCore: dependencies.kdeconnect===false || dependencies["python-gobject"]===false
  property var devices: service ? service.devices : localDevices
  property string selectedId: ""
  property bool loaded: service ? service.loaded : localLoaded
  property string connectionError: service ? service.connectionError : localConnectionError
  property string message: ""
  property bool messageError: false
  property string busyVerb: ""
  property var notificationCards: localNotificationCards
  property int notificationSequence: 0
  ListModel { id: notificationModel; dynamicRoles: true }
  property bool messagingReady: service ? service.messagingReady : localMessagingReady
  property string messagingError: service ? (service.notificationStateError || service.messagingError) : localMessagingError
  readonly property string notificationStateError: service ? service.notificationStateError : ""
  property int messagingRestarts: service ? service.messagingRestarts : localMessagingRestarts
  property var smsComposer: ComposerState.create()
  property var smsDrafts: ({})
  property var historyState: service ? service.historyState : localHistoryState
  property var mediaStates: service ? service.mediaStates : localMediaStates
  property var remoteMedia: service ? service.remoteMedia : localRemoteMedia
  property string workspaceContext: ""
  property var localRemovalConfirmation: null
  property var localRemovalRequests: ({})
  property string selectedNotification: ""
  property int workspaceVisit: 0
  property var manualSendView: ({})
  readonly property bool historyButtonActive: opened && (workspaceContext === "history" || workspaceContext === "thread")
  property bool historyOpen: false
  property string historyThread: ""
  property int smsSequence: 0
  property var callEvents: service ? service.callEvents : localCallEvents
  readonly property var visibleCalls: callEvents.filter(function(c) { return root.phone && c.device === root.phone.id && c.presentation === "dedicated" })

  Connections {
    target: root.service
    function onEventReceived(event) { root.handleServiceEvent(event) }
    function onOpenRequested() { root.open() }
    function onCloseRequested() { root.close() }
    function onToggleRequested() { root.toggle() }
  }

  function resolveDraftSlotIdentity() {
    if(panelDraftSlotOverride && panelDraftSlotOverride.length<=256)return "fixture:"+panelDraftSlotOverride
    try {
      var window=barButton.QsWindow.window,screen=window?window.screen:null
      var name=screen?String(screen.name||""):""
      var position=bar?String(bar.position||""):""
      if(name && name.length<=256 && position && position.length<=16)
        return "monitor:"+JSON.stringify([moduleName,name,position])
    } catch(e) {}
    return ""
  }

  function panelDraftPayload() {
    var sms=[]
    Object.keys(smsDrafts).forEach(function(key) {
      var d=smsDrafts[key]
      if(!d || (!d.text && !d.files.length && !d.pending && !d.pickerRequest))return
      if(sms.length>=32)return
      sms.push({device:d.device,thread:d.thread,conversationToken:d.conversationToken||"",
        recipientScope:Array.isArray(d.recipientScope)&&d.recipientScope.length<=16?d.recipientScope.slice():[],participants:d.participants||"",
        recipient:d.recipient||"",text:ComposerState.limitText(String(d.text||""),65536),
        files:(d.files||[]).slice(0,32).filter(function(f){return typeof f.path==="string"&&f.path.length<=4096}).map(function(f){return {path:f.path,name:String(f.name||"").slice(0,256),size:Number(f.size)||0}}),
        open:!!d.open,status:d.pending||d.pickerRequest?"Connection changed. Check the phone and file selection before trying again.":String(d.status||""),
        wasPending:!!(d.pending||d.pickerRequest)})
    })
    var notifications=[]
    Object.keys(localNotificationCards).forEach(function(key) {
      var c=localNotificationCards[key]
      if(!c || (!c.editing&&!c.draft) || notifications.length>=32)return
      var n=c.note||{}
      notifications.push({note:{device:n.device,id:n.id,occurrence_id:n.occurrence_id||"",
        notification_epoch:n.notification_epoch||"",internal_id:n.internal_id||"",reply_id:n.reply_id||"",
        title:String(n.title||"").slice(0,4096),app:String(n.app||"").slice(0,1024),
        body:String(n.body||"").slice(0,16384),dismissable:!!n.dismissable,icon_path:String(n.icon_path||"").slice(0,4096),icon_kind:n.icon_kind||"notification_icon"},
        draft:String(c.draft||"").slice(0,16384),draftReply:c.draftReply||"",draftInternal:c.draftInternal||"",
        draftTitle:c.draftTitle||"",draftOccurrence:c.draftOccurrence||"",
        draftNotificationEpoch:c.draftNotificationEpoch||"",draftUnavailable:!!c.unavailable,
        draftStatus:c.unavailable?String(c.status||"Reply no longer available"):"",
        draftGeneration:Number(c.draftGeneration)||0,usedReply:c.usedReply||""})
    })
    return {sms:sms,notifications:notifications,workspaceContext:workspaceContext,
      historyThread:historyThread,selectedNotification:selectedNotification,
      activeSmsDevice:smsComposer.device||"",activeSmsThread:smsComposer.thread||""}
  }

  function persistPanelDrafts() {
    if(service && clientId && attachedDraftSlot && !service.savePanelDraftSnapshot(clientId,attachedDraftSlot,panelDraftPayload())) {
      message="Draft preservation capacity reached. Finish or discard a draft on another monitor first.";messageError=true
    }
  }

  function restorePanelDrafts(saved) {
    if(!saved)return
    var nextSms=({})
    ;(saved.sms||[]).forEach(function(d) {
      if(!d || typeof d.device!=="string" || typeof d.thread!=="string")return
      var c=ComposerState.create()
      Object.assign(c,d,{pending:"",pickerRequest:"",contactsLoading:false,contactsRequest:"",
        contacts:historyState.contacts[d.device]||[],files:Array.isArray(d.files)?d.files.slice(0,32):[]})
      if(d.wasPending)c.status="Connection changed. Check the phone and file selection before trying again."
      nextSms[HistoryState.key(c.device,c.thread)]=c
    })
    smsDrafts=nextSms
    smsComposer=Object.assign({},smsDrafts[HistoryState.key(saved.activeSmsDevice||"",saved.activeSmsThread||"")]||ComposerState.create())
    workspaceContext=String(saved.workspaceContext||"")
    historyThread=String(saved.historyThread||"")
    historyOpen=workspaceContext==="history"||workspaceContext==="thread"
    selectedNotification=String(saved.selectedNotification||"")
    ;(saved.notifications||[]).forEach(function(d) {
      if(!d||!d.note||typeof d.note.device!=="string"||typeof d.note.id!=="string")return
      var n=d.note,base=NotificationState.key(n.device,n.id),current=localNotificationCards[base]
      var same=!!(current&&current.active&&current.note.occurrence_id===n.occurrence_id&&
        current.note.notification_epoch===n.notification_epoch&&current.note.internal_id===n.internal_id&&current.note.reply_id===n.reply_id)
      var card=same?current:NotificationState.makeCard(n)
      card.key=same?base:JSON.stringify([n.device,n.id,n.occurrence_id,"saved-draft"])
      card.note=same?current.note:n;card.active=same;card.editing=true;card.draft=String(d.draft||"")
      card.draftReply=d.draftReply||"";card.draftInternal=d.draftInternal||"";card.draftTitle=d.draftTitle||""
      // Keep the proof captured when editing began. A newer display note must
      // never grant its occurrence or worker epoch to an older draft.
      card.draftOccurrence=d.draftOccurrence||"";card.draftNotificationEpoch=d.draftNotificationEpoch||""
      card.draftGeneration=Number(d.draftGeneration)||0
      card.unavailable=!!d.draftUnavailable || !same || !card.draftOccurrence || !card.draftNotificationEpoch ||
        card.draftOccurrence!==card.note.occurrence_id || card.draftNotificationEpoch!==card.note.notification_epoch
      if(card.unavailable)card.status=d.draftStatus||"Reply no longer available"
      if(!same)card.usedReply=d.usedReply||""
      localNotificationCards[card.key]=card
    })
    localNotificationCards=Object.assign({},localNotificationCards)
    syncNotificationCards()
  }

  function syncNotificationSnapshot() {
    if (!service) return
    var previous=localNotificationCards,next=({}),snapshot=service.notificationSnapshot()
    snapshot.forEach(function(item) {
      var key=item.key,old=previous[key],card=old||NotificationState.makeCard(item.note)
      var same=old && card.note.internal_id===item.note.internal_id && card.note.reply_id===item.note.reply_id
      if(old && !same && (card.editing||card.draft)) {
        card.unavailable=true;card.status="Reply no longer available"
      }
      card.note=item.note;card.active=item.active;card.usedReply=item.usedReply
      card.sharedPending=item.pending;card.pendingOwner=item.pendingOwner
      card.pending=card.pendingOwner===clientId?item.pending:""
      if(item.unavailable)card.unavailable=true
      if(item.status && !card.editing)card.status=item.status
      next[key]=card
    })
    Object.keys(previous).forEach(function(key) {
      if(next[key])return
      var card=previous[key]
      if(card.editing||card.draft||card.pending||card.sharedPending) {
        card.active=false;card.unavailable=true
        if(card.pending||card.sharedPending)card.status="Connection changed. Check the phone before trying again."
        card.pending="";card.sharedPending="";card.pendingOwner=""
        next[key]=card
      }
    })
    localNotificationCards=next
    syncNotificationCards()
  }
  function invalidateLocalRemovalRequests() {
    var requests=localRemovalRequests
    Object.keys(requests).forEach(function(request) {
      var pending=requests[request]
      pending.keys.forEach(function(key) {
        var card=localNotificationCards[key]
        if(card && card.localRemovePending===request)card.localRemovePending=""
      })
    })
    localRemovalRequests=({})
    localNotificationCards=Object.assign({},localNotificationCards)
    syncNotificationCards()
    if(Object.keys(requests).length) {
      message="Local notification cleanup may have completed before the service stopped. Refresh and review the list; drafts are saved."
      messageError=true
    }
  }

  function attachService() {
    var nextService=service
    var nextEpoch=nextService?String(nextService.serviceEpoch||""):""
    var nextSlot=draftSlotIdentity
    if(attachedService===nextService && attachedServiceEpoch===nextEpoch && attachedDraftSlot===nextSlot)return
    // The QObject reference can already be null after direct destruction.
    // The primitive epoch remains available to detect that transition.
    if(attachedServiceEpoch && attachedServiceEpoch!==nextEpoch) {
      Object.keys(smsDrafts).forEach(function(key) { ComposerState.receive(smsDrafts[key],{event:"worker_stopped"}) })
      smsComposer=Object.assign({},smsDrafts[HistoryState.key(smsComposer.device,smsComposer.thread)]||smsComposer)
      NotificationState.receive(localNotificationCards,{event:"worker_stopped"},clientId)
      localNotificationCards=Object.assign({},localNotificationCards)
      invalidateLocalRemovalRequests()
    }
    if(attachedService && clientId && typeof attachedService.unregisterPanel==="function")attachedService.unregisterPanel(clientId)
    attachedService=nextService
    attachedServiceEpoch=nextEpoch
    clientId=nextService?nextService.registerPanel(nextSlot):""
    attachedDraftSlot=nextSlot
    if(nextService) {
      syncNotificationSnapshot()
      if(nextSlot)restorePanelDrafts(nextService.panelDraftSnapshot(nextSlot))
    }
    else if(!previewMode) {
      localDependencies={};localDevices=[];localLoaded=true;localConnectionError="Pocket messaging service is unavailable."
      localMessagingReady=false;localMessagingError="Pocket messaging service is unavailable."
      syncNotificationCards()
    }
    if(nextService && nextService.messagingError)localMessagingError=nextService.messagingError
  }
  onServiceChanged: attachService()
  onDraftSlotIdentityChanged: attachService()

  function newRequestId(prefix) {
    if (service) return service.nextRequestId(prefix)
    return prefix + "-" + (++smsSequence)
  }

  function showWorkspace(context, note) {
    if (popup.workspaceWidth < Style.space(260)) {
      message = "Not enough room to the left on this screen."; messageError = true; return false
    }
    localRemovalConfirmation=null
    workspaceVisit += 1
    workspaceContext = context; selectedNotification = note || ""
    historyOpen = context === "history" || context === "thread"
    Qt.callLater(function() { workspaceScroll.contentY=0; workspaceClose.forceActiveFocus() })
    return true
  }
  function closeWorkspace() {
    localRemovalConfirmation=null
    workspaceVisit += 1; workspaceContext = ""; historyOpen = false
    closeComposer(); Qt.callLater(function(){if(root.opened)keyArea.forceActiveFocus()})
  }
  function requestContacts(device) {
    if(!device)return
    smsComposer.contactsLoading=true;smsComposer.contactsError="";smsComposer.contactsRequest=newRequestId("contacts")
    saveComposer()
    smsCommand({op:"contacts",request_id:smsComposer.contactsRequest,device:device})
  }
  function showHistory() {
    if(!showWorkspace("history"))return
    historyThread=""; closeComposer()
    if(phone)smsCommand({op:"contacts",request_id:newRequestId("contacts"),device:phone.id})
  }
  function showNotifications(key) { showWorkspace(key ? "notification" : "notifications",key) }
  readonly property int activeNoteCount: {
    var n=0
    for(var i=0;i<notificationModel.count;i++) {
      var c=notificationModel.get(i).payload
      if(phone && c.note.device===phone.id && c.active)n++
    }
    return n
  }
  function syncNotificationCards() {
    var cards = notificationCards
    for (var i = notificationModel.count - 1; i >= 0; --i)
      if (!cards[notificationModel.get(i).cardKey]) notificationModel.remove(i)
    Object.keys(cards).forEach(function(key) {
      var payload = JSON.parse(JSON.stringify(cards[key]))
      for (var i = 0; i < notificationModel.count; ++i) {
        if (notificationModel.get(i).cardKey === key) {
          notificationModel.setProperty(i, "payload", payload)
          return
        }
      }
      notificationModel.append({cardKey: key, payload: payload})
    })
  }
  function handleServiceEvent(event) {
    if(event.event==="notification_local_remove_uncertain") {
      var pending=localRemovalRequests[event.request_id]
      if(pending) {
        var remaining=Object.assign({},localRemovalRequests);delete remaining[event.request_id];localRemovalRequests=remaining
        pending.keys.forEach(function(key) {
          var card=localNotificationCards[key]
          if(card && card.localRemovePending===event.request_id)card.localRemovePending=""
        })
        localNotificationCards=Object.assign({},localNotificationCards)
        syncNotificationCards()
        message=event.error||"Local notification cleanup may have completed before the service stopped. Refresh and review the list; drafts are saved."
        messageError=true
      }
      return
    }
    NotificationState.receive(localNotificationCards,event,clientId)
    if(event.event==="notification_local_remove" || event.event==="notification_local_remove_failed" ||
       event.event==="notification_local_remove_capacity" || event.event==="notification_local_remove_result")
      finishLocalNotificationRemoval(event)
    localNotificationCards=Object.assign({},localNotificationCards)
    syncNotificationCards()
    if(event.event === "volume_result" || (event.event === "error" && event.request_id === volumeControl.pending)) {
      if(!event.device || (phone && event.device === phone.id))
        volumeControl.result(event.request_id, event.accepted === true, event.error || "Could not update media volume")
    }
    var closeManual = event.event === "sms_result" && event.accepted && !event.uncertain
      && event.request_id === smsComposer.pending && !smsComposer.thread
      && (!event.device || event.device === smsComposer.device)
      && manualSendView.request === event.request_id && manualSendView.visit === workspaceVisit
      && workspaceContext === "new"
    Object.keys(smsDrafts).forEach(function(k) {
      var draft = smsDrafts[k]
      if(!event.device || event.device === draft.device) ComposerState.receive(draft, event)
    })
    smsComposer = Object.assign({}, smsDrafts[HistoryState.key(smsComposer.device, smsComposer.thread)] || smsComposer)
    if(event.event === "threads_refreshed" && historyOpen && historyThread && phone && event.device === phone.id)
      loadHistory()
    syncNotificationCards()
    if(closeManual) closeWorkspace()
  }
  function messagingEvent(event) {
    if(event.event==="notification_local_remove_uncertain") {
      var pending=localRemovalRequests[event.request_id]
      if(!pending)return
      var next=Object.assign({},localRemovalRequests);delete next[event.request_id];localRemovalRequests=next
      pending.keys.forEach(function(key) {
        var card=localNotificationCards[key]
        if(card && card.localRemovePending===event.request_id)card.localRemovePending=""
      })
      localNotificationCards=Object.assign({},localNotificationCards)
      syncNotificationCards()
      message=event.error||"Local notification cleanup may have completed before the service stopped. Refresh and review the list; drafts are saved."
      messageError=true
      return
    }
    if(event.event==="media_state") {
      remoteMedia[event.device]={media:MediaState.normalizeMedia(event.media),
        token:typeof event.token==="string"&&event.token.length<=128?event.token:"",
        revision:Number.isInteger(event.revision)&&event.revision>=0?event.revision:0}
      remoteMedia=Object.assign({},remoteMedia);return
    }
    if(event.event==="volume_result" || (event.event==="error" && event.request_id===volumeControl.pending)) {
      if(!event.device || (phone && event.device===phone.id))volumeControl.result(event.request_id,event.accepted===true,event.error||"Could not update media volume")
      return
    }
    if(event.event==="device_offline"){delete remoteMedia[event.device];remoteMedia=Object.assign({},remoteMedia)}
    if(event.event==="worker_stopped")remoteMedia={}
    if (event.event === "call_events") callEvents = event.calls
    else if (event.event === "worker_stopped") callEvents = []
    else if (event.event === "device_offline") callEvents = callEvents.filter(function(c) { return c.device !== event.device })
    if (event.event === "ready") { messagingReady = true; if(!service)messagingError = "" }
    if (event.event === "error" && !event.request_id && !service) messagingError = event.error
    var closeManual = event.event === "sms_result" && event.accepted && !event.uncertain
      && event.request_id === smsComposer.pending && !smsComposer.thread
      && (!event.device || event.device === smsComposer.device)
      && manualSendView.request === event.request_id && manualSendView.visit === workspaceVisit
      && workspaceContext === "new"
    NotificationState.receive(notificationCards, event)
    HistoryState.receive(historyState,event)
    MediaState.receive(mediaStates,event)
    MediaState.prune(mediaStates,historyState)
    mediaStates=JSON.parse(JSON.stringify(mediaStates))
    historyState = Object.assign({},historyState)
    if(event.event==="threads_refreshed" && historyOpen && historyThread && phone && event.device===phone.id) loadHistory()
    Object.keys(smsDrafts).forEach(function(k) {
      var draft=smsDrafts[k]
      if(!event.device || event.device===draft.device) ComposerState.receive(draft,event)
    })
    smsComposer = Object.assign({}, smsDrafts[HistoryState.key(smsComposer.device,smsComposer.thread)] || smsComposer)
    syncNotificationCards()
    persistPanelDrafts()
    if(closeManual)closeWorkspace()
  }
  function smsCommand(command) {
    if (service) { service.messagingCommand(command); return }
    messagingEvent({event:"error",request_id:command.request_id,
      error:previewMode?"Preview only — nothing sent":"Pocket messaging service is unavailable"})
  }
  function saveComposer() {smsDrafts[HistoryState.key(smsComposer.device,smsComposer.thread)]=smsComposer;smsComposer=Object.assign({},smsComposer);persistPanelDrafts()}
  function smsField(field,value) {
    if(field==="text" && value.length>65536){value=ComposerState.limitText(value,65536);smsComposer.status="Draft limited to 65,536 characters"}
    if(field==="recipient")value=value.slice(0,100)
    smsComposer[field]=value;saveComposer()
  }
  function openComposer(thread) {
    if(!phone)return
    thread=thread||""
    if(!showWorkspace(thread ? "thread" : "new"))return
    var key=HistoryState.key(phone.id,thread)
    if(!ComposerState.reserve(smsDrafts,key)){message="Draft limit reached (32). Discard an unused draft before starting another.";messageError=true;return}
    var existing=!!smsDrafts[key]
    smsComposer=smsDrafts[key]||ComposerState.create()
    smsComposer.device=phone.id;smsComposer.thread=thread;smsComposer.open=true
    if(!thread && smsComposer.status==="Submitted to KDE Connect")smsComposer.status=""
    var t=historyState.threads[key]
    if(thread) {
      smsComposer.participants=t&&Array.isArray(t.replyScope)&&t.replyScope.length===1?HistoryState.participants(historyState,phone.id,t.replyScope):t&&t.head?HistoryState.participants(historyState,phone.id,t.head.addresses):""
      smsComposer.conversationToken=t?t.token||"":""
      smsComposer.recipientScope=t&&Array.isArray(t.replyScope)?t.replyScope.slice():t&&t.head&&t.head.addresses?t.head.addresses.slice():[]
    } else if(!existing || (!smsComposer.text && !smsComposer.files.length && !smsComposer.pending)) {
      smsComposer.participants=""
      smsComposer.conversationToken=""
      smsComposer.recipientScope=[]
    }
    smsComposer.contacts=historyState.contacts[phone.id]||[]
    saveComposer()
    Qt.callLater(function(){workspaceContent.forceLayout();smsEditor.focusComposer();root.reveal(smsEditor)})
    if(!smsComposer.contacts.length)requestContacts(phone.id)
  }
  function closeComposer() {smsComposer.open=false;if(smsEditor)smsEditor.resetContactView();saveComposer()}
  function discardComposer() {
    if(smsComposer.pending||smsComposer.pickerRequest)return
    var thread=smsComposer.thread
    delete smsDrafts[HistoryState.key(smsComposer.device,thread)]
    openComposer(thread)
  }
  function composerSend() {
    if(!phone || phone.id!==smsComposer.device)return
    var current=historyState.threads[HistoryState.key(smsComposer.device,smsComposer.thread)]
    var replyStatus=smsComposer.thread?(current?HistoryState.summary(current).replyStatus:"unknown"):"individual"
    if(smsComposer.thread && (!current || current.stale ||
        replyStatus!=="individual" || !Array.isArray(current.replyScope) || current.replyScope.length!==1 ||
        !Array.isArray(smsComposer.recipientScope) || smsComposer.recipientScope.length!==1 ||
        smsComposer.conversationToken!==(current.token||"") ||
        JSON.stringify(smsComposer.recipientScope)!==JSON.stringify(current.replyScope)))return
    var command=ComposerState.send(smsComposer,smsComposer.device,newRequestId("sms"),replyStatus)
    if(command && !smsComposer.thread)manualSendView={request:command.request_id,visit:workspaceVisit}
    saveComposer();if(command)smsCommand(command)
  }
  function composerAttach() {
    smsComposer.pickerRequest=newRequestId("files");saveComposer()
    smsCommand({op:"pick_files",request_id:smsComposer.pickerRequest,device:smsComposer.device})
  }
  function composerRemove(path) {smsComposer.files=smsComposer.files.filter(function(f){return f.path!==path});saveComposer()}
  function loadHistory() {
    if(!phone)return
    if (service) { service.loadHistory(phone.id, historyThread, newRequestId("history")); return }
    var command=HistoryState.load(historyState,phone.id,historyThread,newRequestId("history"))
    historyState=Object.assign({},historyState);if(command)smsCommand(command)
  }
  function mediaRequest(message,attachment,open) {
    if (service) { service.mediaRequest(message, attachment, newRequestId("media"), open); return }
    var command=MediaState.command(mediaStates,message,attachment,newRequestId("media"),open)
    mediaStates=JSON.parse(JSON.stringify(mediaStates));if(command)smsCommand(command)
  }
  function openThread(thread) {if(!showWorkspace("thread"))return;historyThread=thread;closeComposer();loadHistory()}
  readonly property string currentDeviceId: phone ? phone.id : ""
  onCurrentDeviceIdChanged: {localRemovalConfirmation=null;historyThread="";closeComposer();workspaceContext="";workspaceVisit+=1}
  function localNotificationEntries(keys, deviceId) {
    var result=[],targetDevice=deviceId||currentDeviceId
    Object.keys(notificationCards).forEach(function(key) {
      if(keys && keys.indexOf(key)<0)return
      var c=notificationCards[key]
      if(c.note.device!==targetDevice)return
      result.push({device:c.note.device,id:c.note.id,occurrence_id:c.note.occurrence_id,key:key,
        editing:!!c.editing,draft:c.draft||"",draftReply:c.draftReply||"",draftInternal:c.draftInternal||"",
        draftGeneration:Number(c.draftGeneration)||0,
        pending:!!(c.pending||c.sharedPending||c.localRemovePending)})
    })
    return result
  }
  function removalSnapshot(entries) {
    return entries.map(function(e){return {key:e.key,device:e.device,id:e.id,occurrence_id:e.occurrence_id,
      editing:e.editing,draft:e.draft,draftReply:e.draftReply,draftInternal:e.draftInternal,
      draftGeneration:e.draftGeneration,pending:e.pending}})
      .sort(function(a,b){return a.key.localeCompare(b.key)})
  }
  function requestLocalNotificationRemove(key) {
    var c=notificationCards[key]
    if(!c||c.pending||c.sharedPending||c.localRemovePending)return
    removeLocalNotifications([key],false)
  }
  function removeLocalNotifications(keys,confirmedDrafts) {
    var deviceId=confirmedDrafts&&localRemovalConfirmation?localRemovalConfirmation.device:currentDeviceId
    if(!deviceId){message="Select a device before removing notifications.";messageError=true;return}
    var entries=localNotificationEntries(keys,deviceId)
    if(!entries.length){message="There are no removable notifications on this device.";messageError=false;return}
    var skippedPending=entries.filter(function(e){return e.pending}).length
    if(skippedPending) {
      message="Some notifications are still processing. Clear them after the action finishes.";messageError=false
      entries=entries.filter(function(e){return !e.pending})
      if(!entries.length)return
    }
    var needsConfirmation=entries.some(function(e){return e.editing||!!e.draft})
    if(!confirmedDrafts && needsConfirmation) {
      localRemovalConfirmation={device:deviceId,keys:keys?keys.slice():null,entries:removalSnapshot(entries)}
      message="Review the drafts and notification cards before confirming removal.";messageError=false;return
    }
    if(confirmedDrafts) {
      var confirmation=localRemovalConfirmation
      if(!confirmation || confirmation.device!==currentDeviceId){localRemovalConfirmation=null;return}
      var current=localNotificationEntries(confirmation.keys,confirmation.device)
      if(JSON.stringify(removalSnapshot(current))!==JSON.stringify(confirmation.entries)) {
        localRemovalConfirmation={device:confirmation.device,keys:confirmation.keys,entries:removalSnapshot(current)}
        message="The notification or draft list changed. Review and confirm again.";messageError=false;return
      }
      entries=current
    }
    if(!service||!clientId){message="Pocket messaging service is unavailable; notifications were not removed.";messageError=true;return}
    var targets=entries.map(function(e){return {device:e.device,id:e.id,occurrence_id:e.occurrence_id}})
    var result=service.removeLocalNotifications(clientId,targets)
    if(!result.accepted){message=result.error||"Could not remove notifications.";messageError=true;return}
    var pendingEntries=Object.assign({},localRemovalRequests)
    pendingEntries[result.request_id]={device:deviceId,keys:entries.map(function(e){return e.key}),
      confirmed:!!confirmedDrafts,entries:removalSnapshot(entries),skippedPending:skippedPending}
    localRemovalRequests=pendingEntries
    entries.forEach(function(e){var c=notificationCards[e.key];if(c&&c.note.occurrence_id===e.occurrence_id)c.localRemovePending=result.request_id})
    localNotificationCards=Object.assign({},localNotificationCards);syncNotificationCards()
    localRemovalConfirmation=null
    message="Saving local notification removal…";messageError=false
  }
  function confirmLocalNotificationRemove() {
    if(!localRemovalConfirmation)return
    removeLocalNotifications(localRemovalConfirmation.keys,true)
  }
  function finishLocalNotificationRemoval(event) {
    var pending=localRemovalRequests[event.request_id]
    if(!pending)return
    var next=Object.assign({},localRemovalRequests);delete next[event.request_id];localRemovalRequests=next
    if(event.event!=="notification_local_remove") {
      pending.keys.forEach(function(key){var c=notificationCards[key];if(c)c.localRemovePending=""})
      localNotificationCards=Object.assign({},localNotificationCards);syncNotificationCards()
      message=event.error||"The local notification cleanup could not be saved. Nothing was removed.";messageError=true;return
    }
    var accepted={},skipped=0
    ;(event.entries||[]).forEach(function(e){accepted[NotificationState.key(e.device,e.id)]=e.occurrence_id})
    pending.keys.forEach(function(key){
      var c=notificationCards[key]
      if(!c)return
      if(accepted[key]!==c.note.occurrence_id){
        if(c.localRemovePending===event.request_id)c.localRemovePending=""
        skipped++
        return
      }
      c.localRemovePending=""
      var snapshot=pending.entries.find(function(row){return row.key===key})
      if(pending.confirmed&&snapshot&&c.draft===snapshot.draft&&c.editing===snapshot.editing&&
          (Number(c.draftGeneration)||0)===(Number(snapshot.draftGeneration)||0)&&
          c.draftReply===snapshot.draftReply&&c.draftInternal===snapshot.draftInternal)NotificationState.discard(c)
      if(!c.draft&&!c.editing&&!c.pending&&!c.sharedPending)delete notificationCards[key]
    })
    localNotificationCards=Object.assign({},localNotificationCards);syncNotificationCards()
    message=skipped?"Some notification cards changed before cleanup. Review the list and try again.":
      pending.skippedPending?"Removed from Pocket Extended on this device. Some notifications are still processing and were left untouched.":"Removed from Pocket Extended on this device.";messageError=skipped>0
  }

  function notificationEdit(key, operation, text) {
    var card=notificationCards[key]
    if(!card)return
    if(operation==="begin") {
      if(Object.keys(notificationCards).filter(function(k){return notificationCards[k].editing}).length>=32)
        card.status="Reply draft limit reached (32). Discard an unused draft."
      else NotificationState.begin(card)
    } else if(operation==="draft") {
      if(card.pending||card.sharedPending)return
      var nextDraft=ComposerState.limitText(text,16384)
      if(card.draft!==nextDraft)card.draftGeneration=(Number(card.draftGeneration)||0)+1
      card.draft=nextDraft
      if(text.length>16384)card.status="Reply limited to 16,384 characters"
    } else if(operation==="discard") {
      NotificationState.discard(card)
      if(!card.active&&!card.pending&&!card.sharedPending)delete notificationCards[key]
    } else {
      var command=operation==="reply"?NotificationState.replyCommand(card,newRequestId("notification-draft")):
        NotificationState.dismissCommand(card,newRequestId("notification-draft"))
      if(!command)return
      if(service&&clientId) {
        var ownedRequest=service.submitNotificationAction(clientId,command)
        if(!ownedRequest) {
          card.pending="";card.status=service.messagingReady?"Reply no longer available":"Messaging service is unavailable"
          card.unavailable=service.messagingReady
        } else {card.pending=ownedRequest;card.pendingOwner=clientId}
      } else if(previewMode) messagingCommand(command)
      else {card.pending="";card.status="Pocket messaging service is unavailable";card.unavailable=true}
    }
    localNotificationCards=Object.assign({},localNotificationCards)
    syncNotificationCards()
    persistPanelDrafts()
  }

  function previewInspect(mode) {
    if (!previewMode) return "Preview disabled"
    if (mode === "new")openComposer("")
    else if(mode === "all-notifications")showNotifications("")
    else if(mode === "collapse")closeWorkspace()
    else if (mode === "reply" && notificationRepeater.count) {
      showNotifications(notificationRepeater.itemAt(0).cardKey)
      var card = notificationRepeater.itemAt(0)
      notificationEdit(card.cardKey, "begin", "")
      notificationEdit(card.cardKey, "draft", "Thanks — see you soon 👋")
      Qt.callLater(function() { card.focusEditor(); root.reveal(card) })
    } else if (mode === "top") scroll.contentY = 0
    else if (mode === "history") {showWorkspace("thread");historyThread="9";Qt.callLater(function(){root.reveal(historyView)})}
    else if (mode === "composer") {historyOpen=true;historyThread="9";openComposer("9");Qt.callLater(function(){smsEditor.focusMessage();root.reveal(smsEditor)})}
    else if (mode === "bottom") scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height)
    return JSON.stringify({opened:root.opened,originX: popup.cardOrigin.x, originY: popup.cardOrigin.y, width: popup.contentWidth, height: popup.contentHeight,
      workspace:workspaceContext,workspaceX:popup.workspaceX,workspaceY:popup.workspaceY,workspaceWidth:popup.workspaceWidth,workspaceHeight:popup.workspaceHeight,screenHeight:popup.screenH,barHeight:popup.barH,notificationHeight:notificationPreview.height,
      contentHeight: scroll.contentHeight, viewportHeight: scroll.height,
      scrollY: scroll.contentY, color: String(Color.popups.background), font: root.face})
  }
  function replyHasFocus() {
    if(smsEditor.visible&&smsEditor.inputFocused)return true
    for (var i = 0; i < notificationRepeater.count; ++i)
      if ((notificationRepeater.itemAt(i) as NotificationCard).editorFocused) return true
    return false
  }
  function messagingCommand(command) {
    if (service) { service.messagingCommand(command); return }
    messagingEvent({event:"error",request_id:command.request_id,
      error:previewMode?"Preview only — nothing sent":"Pocket messaging service is unavailable"})
  }
  readonly property var phone: {
    for (var i = 0; i < devices.length; ++i)
      if (devices[i].id === selectedId) return devices[i]
    return devices.length ? devices[0] : null
  }
  readonly property bool online: !!phone && phone.online
  readonly property string smsCapabilityState: !phone || !phone.online ? "offline" : (phone.can === undefined ? "pending" : (phone.can.indexOf("kdeconnect_sms") >= 0 ? "available" : "unavailable"))
  readonly property var mediaRecord: phone ? remoteMedia[phone.id] || ({}) : ({})
  readonly property var media: mediaRecord.media || (phone ? phone.media : ({}))
  readonly property int noteCount: {
    var count = 0
    for (var i = 0; i < notificationModel.count; ++i)
      if (phone && notificationModel.get(i).payload.note.device === phone.id) count++
    return count
  }
  readonly property bool playing: online && !!media.player
  readonly property bool busy: action.running

  function can(feature) {
    if (!online || phone.can.indexOf("kdeconnect_" + feature) < 0) return false
    if (feature === "sftp") return dependencies.sshfs === true && dependencies["kio-fuse"] === true && dependencies.nautilus === true
    if (feature === "share") return dependencies["omarchy-file-select"] === true
    return true
  }
  function reveal(item) {
    if (!root.opened) return
    var ancestor=item
    while(ancestor && ancestor!==workspaceContent)ancestor=ancestor.parent
    var inWorkspace=ancestor===workspaceContent
    var target = inWorkspace ? workspaceScroll : scroll
    var container = inWorkspace ? workspaceContent : content
    var point = item.mapToItem(container, 0, 0)
    if(point.y < target.contentY)target.contentY=point.y
    else if(point.y+item.height > target.contentY+target.height)
      target.contentY=Math.max(0,Math.min(point.y,target.contentHeight-target.height))
  }
  function refresh() {
    if (service) { service.refresh(); return }
    if(previewMode)return
    localLoaded=true;localDevices=[];localConnectionError="Pocket messaging service is unavailable."
    localMessagingReady=false;localMessagingError="Pocket messaging service is unavailable."
  }
  function run(verb, value) {
    if (previewMode) { message = "Preview only — no device action performed"; return }
    if (!online || busy) return
    message = ""; busyVerb = verb
    action.command = ["python3", bridge, verb, phone.id, value === undefined ? "" : String(value)]
    action.running = true
    if (verb === "share") root.close()
  }
  function refreshAll() {
    if (service) { service.refreshAll(); return }
    refresh()
  }
  function nextDevice() {
    if (devices.length < 2) return
    var index = devices.findIndex(function(d) { return d.id === phone.id })
    selectedId = devices[(index + 1) % devices.length].id
    message = ""
  }
  function nextPlayer() {
    var players = media.playerList || []
    if (!players.length) return
    run("player", players[(players.indexOf(media.player) + 1) % players.length])
  }
  onOpenedChanged: {
    if (opened) { refresh(); message = "" }
    else { historyNavigation.hasCursor=false; historyNavigation.focus=false }
  }
  Component.onCompleted: { attachService(); refresh() }
  Component.onDestruction: {
    persistPanelDrafts()
    if(attachedService && clientId && typeof attachedService.unregisterPanel==="function")attachedService.unregisterPanel(clientId)
  }

  Timer { interval: root.opened ? 4000 : 30000; repeat: true; running: true; onTriggered: root.refresh() }
  Timer { id: feedbackTimer; interval: 7000; onTriggered: if (!root.messageError) root.message = "" }
  Process {
    id: action
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          root.messageError = !result.ok
          root.message = result.ok ? result.message : result.error
        } catch (e) { root.messageError = true; root.message = "Action could not be completed. Try again." }
        feedbackTimer.restart(); root.refresh()
      }
    }
  }

  BarIconButton {
    id: barButton
    anchors.fill: parent
    bar: root.bar
    text: ""
    iconComponent: Component {
      Item {
        Rectangle {
          anchors.centerIn: parent
          width: parent.width * 0.57; height: parent.height * 0.86
          color: "transparent"; radius: Style.space(2)
          border.width: Math.max(1, Style.space(1.4))
          border.color: root.opened ? Color.accent : root.barForeground
          Rectangle {
            width: parent.width * 0.3; height: Math.max(1, Style.space(1))
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(3)
            color: parent.border.color
          }
        }
      }
    }
    active: root.opened
    activeColor: Color.accent
    tooltipText: "Pocket Extended · KDE Connect" + (root.phone ? " · " + root.phone.name + (root.online ? (root.phone.battery >= 0 ? " · " + root.phone.battery + "%" : " · Connected") : " · Offline") : " · No paired phone")
    onPressed: root.toggle()
    Rectangle {
      visible: root.activeNoteCount > 0
      width: Style.space(4); height: width; radius: width / 2
      anchors.right: parent.right; anchors.rightMargin: Style.space(2)
      anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(7)
      color: Color.accent
    }
  }

  ExtendedPanel {
    id: popup
    anchorItem: barButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyArea
    workspaceOpen: root.workspaceContext !== ""
    contentWidth: fittedContentWidth(Style.space(424))
    contentHeight: fittedContentHeight(content.implicitHeight)

    workspaceItem: Item {
      anchors.fill:parent
      Keys.onEscapePressed:root.closeWorkspace()
      Column {
        anchors.fill:parent;spacing:Style.space(12)
        Row {
          width:parent.width;spacing:Style.space(6)
          Label {width:parent.width-workspaceClose.width-parent.spacing;text:root.workspaceContext==="new"?"NEW MESSAGE":root.workspaceContext==="history"?"MESSAGE HISTORY":root.workspaceContext==="thread"?"CONVERSATION":"NOTIFICATIONS";font.bold:true;font.pixelSize:Style.font.caption;color:Color.accent;anchors.verticalCenter:parent.verticalCenter}
          QuickButton {id:workspaceClose;text:"Close ×";onClicked:root.closeWorkspace()}
        }
        QuickButton {visible:root.workspaceContext==="notification";text:"‹ All Notifications";onClicked:root.showNotifications("")}
        Flickable {
          id:workspaceScroll
          width:parent.width;height:parent.height-y
          contentWidth:width;contentHeight:workspaceContent.implicitHeight;clip:true
          boundsBehavior:Flickable.StopAtBounds
          QQC.ScrollBar.vertical:QQC.ScrollBar {policy:QQC.ScrollBar.AsNeeded}
          Column {
            id:workspaceContent;width:parent.width-Style.space(8);spacing:Style.space(10)
          ConversationView {
            id:historyView
            visible:(root.workspaceContext==="history"||root.workspaceContext==="thread")&&!!root.phone;width:parent.width
            // Reserve only the existing composer's rendered height. History
            // continues scrolling internally; closing Reply returns this space.
            height:replyComposerVisible ? Math.max(minimumViewportHeight, workspaceScroll.height-smsEditor.height-workspaceContent.spacing) : workspaceScroll.height
            replyComposerVisible:root.workspaceContext==="thread" && smsEditor.visible
            fillViewport:true
            historyData:root.historyState;device:root.phone?root.phone.id:"";thread:root.historyThread
            mediaStates:root.mediaStates
            onMediaRequested:function(message,attachment,open){root.mediaRequest(message,attachment,open)}
            online:root.online&&root.messagingReady
            ink:root.ink;accent:Color.accent;fieldBackground:Color.popups.background
            fontFamily:root.face;bodySize:Style.font.body;smallSize:Style.font.bodySmall
            unit:Style.space(1);corner:Style.cornerRadius
            onOpenThread:function(thread){root.openThread(thread)}
            onBackRequested:root.showHistory()
            onLoadRequested:root.loadHistory()
            onReplyRequested:root.openComposer(root.historyThread)
          }
          SmsComposer {
            id:smsEditor
            visible: (root.workspaceContext==="new" || root.workspaceContext==="thread") && root.smsComposer.open && !!root.phone && root.smsComposer.device===root.phone.id
            width: parent.width
            workspaceMode: true
            payload: root.smsComposer
            replyStatus:!root.smsComposer.thread?"individual":(root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)]?HistoryState.summary(root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)]).replyStatus:"unknown")
            replyBlockMessage:replyStatus==="individual"&&root.smsComposer.thread&&root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)]&&(root.smsComposer.conversationToken!==root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)].token||JSON.stringify(root.smsComposer.recipientScope||[])!==JSON.stringify(root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)].replyScope||[]))?"Conversation recipient authorization changed. Review a current reply before sending.":HistoryState.replyBlockText(replyStatus)
            contextValid:!root.smsComposer.thread || (replyStatus==="individual" && !!root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)] && root.smsComposer.recipientScope.length===1 && root.smsComposer.conversationToken===root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)].token && JSON.stringify(root.smsComposer.recipientScope||[])===JSON.stringify(root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)].replyScope||[]))
            online: root.online && (!root.smsComposer.thread || !!root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)] && !root.historyState.threads[HistoryState.key(root.smsComposer.device,root.smsComposer.thread)].stale)
            serviceReady: root.messagingReady && root.smsCapabilityState === "available"
            capabilityState:root.smsCapabilityState
            pickerAvailable:root.dependencies["omarchy-file-select"]===true
            ink: root.ink; accent: Color.accent; fieldBackground: Color.popups.background
            fontFamily: root.face; bodySize: Style.font.body; smallSize: Style.font.bodySmall
            unit: Style.space(1); corner: Style.cornerRadius
            onFieldEdited: function(field, value) { root.smsField(field, value) }
            onAttachRequested: root.composerAttach()
            onRemoveRequested: function(path) { root.composerRemove(path) }
            onSendRequested: root.composerSend()
            onCloseRequested: {if(root.workspaceContext==="new")root.closeWorkspace();else root.closeComposer()}
            onDiscardRequested: root.discardComposer()
            onEditorActivated: root.reveal(this)
          }
            Repeater {
              id: notificationRepeater
              model: notificationModel
              NotificationCard {
                required property string cardKey
                width: workspaceContent.width
                visible: !!root.phone && payload.note.device === root.phone.id && (root.workspaceContext==="notifications" || (root.workspaceContext==="notification" && cardKey===root.selectedNotification))
                height: visible ? implicitHeight : 0
                expanded: true
                showExpandControl: false
                ink: root.ink; accent: Color.accent; fieldBackground: Color.popups.background
                fontFamily: root.face; bodySize: Style.font.body; smallSize: Style.font.bodySmall
                unit: Style.space(1); corner: Style.cornerRadius
                workerReady: root.messagingReady && root.online
                onEditRequested: root.notificationEdit(cardKey, "begin", "")
                onDraftChanged: function(text) { root.notificationEdit(cardKey, "draft", text) }
                onDiscardRequested: root.notificationEdit(cardKey, "discard", "")
                onReplyRequested: root.notificationEdit(cardKey, "reply", "")
                onDismissRequested: root.notificationEdit(cardKey, "dismiss", "")
                onRemoveRequested: root.requestLocalNotificationRemove(cardKey)
                onEditorActivated: root.reveal(this)
              }
            }
            Label {width:parent.width;wrapMode:Text.Wrap;visible:(root.workspaceContext==="notification"&&!root.notificationCards[root.selectedNotification])||(root.workspaceContext==="notifications"&&root.noteCount===0);text:"No notification available.";color:root.subdued}
            Rectangle {
              objectName:"localNotificationConfirm"
              visible:(root.workspaceContext==="notifications"||root.workspaceContext==="notification")&&!!root.localRemovalConfirmation
              width:parent.width;height:confirmColumn.implicitHeight+Style.space(20)
              color:Qt.alpha(Color.urgent,0.08);radius:Style.cornerRadius;border.width:1;border.color:Qt.alpha(Color.urgent,0.35)
              Column {
                id:confirmColumn;anchors.left:parent.left;anchors.right:parent.right;anchors.margins:Style.space(10);spacing:Style.space(6)
                Label {width:parent.width;wrapMode:Text.WordWrap;text:"Remove these notification cards from Pocket Extended? Unsent reply drafts on this panel will be discarded. Other panels keep their drafts.";color:root.ink}
                Row {spacing:Style.space(6)
                  QuickButton {objectName:"confirmLocalNotificationRemoval";text:"Discard drafts and remove";onClicked:root.confirmLocalNotificationRemove()}
                  QuickButton {objectName:"cancelLocalNotificationRemoval";text:"Cancel";onClicked:root.localRemovalConfirmation=null}
                }
              }
            }
            Label {objectName:"localNotificationActionStatus";width:parent.width;visible:root.workspaceContext==="notifications"&&root.message!=="";text:root.message;color:root.messageError?Color.urgent:root.subdued;wrapMode:Text.WordWrap}
            QuickButton {
              objectName:"clearLocalNotifications"
              visible:root.workspaceContext==="notifications"
              enabled:!!root.phone&&Object.keys(root.notificationCards).some(function(k){return root.notificationCards[k].note.device===root.phone.id})
              text:"Clear all notifications"
              onClicked:root.removeLocalNotifications(null,false)
            }
          }
        }
      }
    }

    Item {
      id: keyArea
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: {if(root.workspaceContext)root.closeWorkspace();else root.close()}
      Keys.onPressed: function(event) {
        if (root.replyHasFocus()) return
        if (event.text === "b" && root.can("sftp")) { root.run("files"); event.accepted = true }
        if (event.text === "r") { root.refreshAll(); event.accepted = true }
      }
      Flickable {
        id: scroll
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }

        Column {
          id: content
          width: scroll.width
          spacing: Style.space(16)

          Row {
            width: parent.width
            spacing: Style.space(8)
            Label {
              width: parent.width - refreshButton.width - closeButton.width - parent.spacing * 2
              anchors.verticalCenter: parent.verticalCenter
              text: "POCKET EXTENDED"; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.5
            }
            PocketButton {
              id: refreshButton; iconText: "󰑐"; tooltipText: "Refresh · R"; focusable: true
              foreground: root.ink; enabled: !root.busy
              onClicked: root.refreshAll()
            }
            PocketButton {
              id: closeButton; iconText: "󰅖"; tooltipText: "Close · Esc"; focusable: true
              foreground: root.ink; onClicked: root.close()
            }
          }

          Rectangle {
            width: parent.width
            visible: root.missingDependencies.length > 0
            height: setupInfo.implicitHeight + Style.space(24)
            radius: Style.cornerRadius
            color: Qt.alpha(Color.urgent, 0.08)
            border.width: 1; border.color: Qt.alpha(Color.urgent, 0.4)
            Column {
              id: setupInfo
              anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(12); spacing: Style.space(6)
              Label { width: parent.width; text:root.missingCore?"Finish core setup":"Optional feature setup"; font.bold: true; color:root.missingCore?Color.urgent:Color.accent }
              Label { width: parent.width; text: "Missing: " + root.missingDependencies.join(", "); wrapMode: Text.WordWrap }
              Label {
                width: parent.width; font.pixelSize: Style.font.bodySmall; color: root.subdued; wrapMode: Text.WrapAnywhere
                text: root.missingDependencies.indexOf("omarchy-file-select") >= 0
                  ? "Update Omarchy to restore its file chooser. See the README for other packages, then refresh."
                  : "In a terminal, run: sudo pacman -S --needed " + root.missingDependencies.join(" ") + " — then refresh."
              }
            }
          }

          Rectangle {
            width: parent.width
            height: hero.implicitHeight + Style.space(32)
            radius: Style.cornerRadius
            color: Qt.alpha(Color.accent, 0.08)
            border.width: 1; border.color: Qt.alpha(Color.accent, 0.2)
            Column {
              id: hero
              anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(16)
              spacing: Style.space(14)
              Row {
                width: parent.width; spacing: Style.space(14)
                Rectangle {
                  width: Style.space(38); height: Style.space(56); radius: Style.space(7)
                  color: "transparent"; border.width: 2; border.color: root.online ? Color.accent : root.subdued
                  anchors.verticalCenter: parent.verticalCenter
                  Rectangle { width: parent.width * 0.4; height: 2; radius: 1; color: parent.border.color; anchors.top: parent.top; anchors.topMargin: 5; anchors.horizontalCenter: parent.horizontalCenter }
                  Text { anchors.centerIn: parent; text: root.online ? "󰄬" : "󰅖"; color: parent.border.color; font.family: root.face; font.pixelSize: Style.font.heading }
                  Rectangle { width: 9; height: 2; radius: 1; color: parent.border.color; anchors.bottom: parent.bottom; anchors.bottomMargin: 5; anchors.horizontalCenter: parent.horizontalCenter }
                }
                Column {
                  width: parent.width - Style.space(52); spacing: Style.space(5)
                  Label { width: parent.width; text: root.phone ? root.phone.name : root.loaded ? "Your phone belongs here" : "Finding your phone…"; font.pixelSize: Style.font.title; font.bold: true; wrapMode: Text.WordWrap }
                  Label { width: parent.width; text: root.online ? "CONNECTED  /  " + (root.phone.links.join(" + ") || "KDE Connect") : root.phone ? "OFFLINE  /  Waiting to reconnect" : "Pair a device in KDE Connect"; color: root.online ? Color.accent : root.subdued; font.pixelSize: Style.font.caption; wrapMode: Text.WordWrap }
                }
              }
              Row {
                visible: root.online && root.phone.battery >= 0
                width: parent.width; spacing: Style.space(12)
                Label { id: percent; text: root.phone ? root.phone.battery + "%" : ""; font.pixelSize: Style.font.heading; font.bold: true; color: root.phone && root.phone.battery <= 15 ? Color.urgent : root.ink }
                Rectangle {
                  width: parent.width - percent.width - charge.width - parent.spacing * 2; height: Style.space(5); radius: height / 2
                  anchors.verticalCenter: parent.verticalCenter; color: Qt.alpha(root.ink, 0.12)
                  Rectangle { width: parent.width * Math.max(0, Math.min(100, root.phone ? root.phone.battery : 0)) / 100; height: parent.height; radius: parent.radius; color: percent.color; Behavior on width { NumberAnimation { duration: 200 } } }
                }
                Label { id: charge; anchors.verticalCenter: parent.verticalCenter; text: root.phone && root.phone.charging ? "Charging" : "Battery"; font.pixelSize: Style.font.caption; color: root.subdued }
              }
              PocketButton { visible: root.devices.length > 1; text: "Switch device  →"; focusable: true; foreground: root.ink; onClicked: root.nextDevice() }
            }
          }

          Label {
            width: parent.width; visible: !root.online
            text: root.connectionError || (root.phone ? "Open KDE Connect on your phone to reconnect. Your shortcuts will be ready when it returns." : "Open KDE Connect settings to pair your phone with this laptop.")
            color: root.subdued; wrapMode: Text.WordWrap
          }

          Column {
            width: parent.width; spacing: Style.space(8)
            ActionTile { width: parent.width; title: "Browse files"; detail: "Your phone’s shared storage"; glyph: "󰉋"; primary: true; verb: "files"; feature: "sftp"; height: Style.space(64) }
            Row {
              width: parent.width; spacing: Style.space(8)
              ActionTile { width: (parent.width - parent.spacing * 2) / 3; title: "Photos"; glyph: "󰋩"; verb: "photos"; feature: "sftp"; compact: true }
              ActionTile { width: (parent.width - parent.spacing * 2) / 3; title: "Downloads"; glyph: "󰇚"; verb: "downloads"; feature: "sftp"; compact: true }
              ActionTile { width: (parent.width - parent.spacing * 2) / 3; title: "Documents"; glyph: "󰈙"; verb: "documents"; feature: "sftp"; compact: true }
            }
            Row {
              width: parent.width; spacing: Style.space(8)
              QuickButton { width: (parent.width - parent.spacing * 2) / 3; text: "Send file"; iconText: "󰒍"; enabled: root.can("share") && !root.busy; onClicked: root.run("share") }
              QuickButton { width: (parent.width - parent.spacing * 2) / 3; text: "Clipboard"; iconText: "󰅍"; enabled: root.can("clipboard") && !root.busy; onClicked: root.run("clipboard") }
              QuickButton { width: (parent.width - parent.spacing * 2) / 3; text: "Ring"; iconText: "󰍡"; tooltipText: "Make your phone ring"; enabled: root.can("findmyphone") && !root.busy; onClicked: root.run("ring") }
            }
          }

          Label {
            width: parent.width; visible: root.busy || root.message !== ""
            text: root.busy ? (["files", "photos", "downloads", "documents"].indexOf(root.busyVerb) >= 0 ? "Connecting to phone storage…" : root.busyVerb === "share" ? "Choose a file in the file picker…" : "Working…") : root.message
            color: root.messageError ? Color.urgent : Color.accent; wrapMode: Text.WordWrap; font.pixelSize: Style.font.bodySmall
          }

          PanelSeparator { foreground: root.ink }
          SectionLabel { visible: root.visibleCalls.length > 0; text: "CALL ACTIVITY" }
          Repeater {
            model: root.visibleCalls
            CallCard {
              required property var modelData
              width: content.width; record: modelData
              ink: root.ink; accent: Color.accent; fontFamily: root.face
              fontSize: Style.font.bodySmall; unit: Style.space(1); corner: Style.cornerRadius
            }
          }
          Row {
            visible:!!root.phone; width:parent.width; spacing:Style.space(8)
            QuickButton {id:historyNavigation;width:(parent.width-parent.spacing)/2;text:"Message History";selected:root.historyButtonActive;onClicked:root.showHistory()}
            QuickButton {width:(parent.width-parent.spacing)/2;text:"New Message";selected:root.workspaceContext==="new";onClicked:root.openComposer("")}
          }
          PanelSeparator { foreground: root.ink }
          Column {
            width: parent.width; spacing: Style.space(10)
            SectionLabel { text: "ON YOUR PHONE" }
            Row {
              width: parent.width; spacing: Style.space(12)
              Label { text: "󰎈"; font.pixelSize: Style.font.display; color: Color.accent }
              Column {
                width: parent.width - Style.space(48); spacing: Style.space(3)
                Label { width: parent.width; text: root.media.title || (root.playing ? "Ready to play" : "Nothing playing"); font.bold: true; elide: Text.ElideRight }
                Label { width: parent.width; text: root.media.artist || (root.online ? "Start music or a podcast on your phone" : "Reconnect to control playback"); font.pixelSize: Style.font.bodySmall; color: root.subdued; elide: Text.ElideRight }
              }
            }
            PocketButton {
              visible: (root.media.playerList || []).length > 0
              text: (root.media.player || "Select player") + ((root.media.playerList || []).length > 1 ? "  ⇄" : "")
              foreground: root.subdued; fontSize: Style.font.caption; focusable: true
              enabled: !root.busy; onClicked: root.nextPlayer()
            }
            Row {
              width: parent.width; spacing: Style.space(8)
              QuickButton { iconText: "󰒮"; tooltipText: "Previous track"; enabled: root.playing && !root.busy; onClicked: root.run("media", "Previous") }
              QuickButton { iconText: root.media.isPlaying ? "󰏤" : "󰐊"; tooltipText: root.media.isPlaying ? "Pause" : "Play"; selected: root.playing; enabled: root.playing && !root.busy; onClicked: root.run("media", "PlayPause") }
              QuickButton { iconText: "󰒭"; tooltipText: "Next track"; enabled: root.playing && !root.busy; onClicked: root.run("media", "Next") }
              Label { text: "󰕾"; color: root.subdued; anchors.verticalCenter: parent.verticalCenter }
              MediaVolume {
                id:volumeControl
                width: Math.max(40, parent.width - Style.space(182)); anchors.verticalCenter: parent.verticalCenter
                endpoint:root.phone && root.mediaRecord.token ? root.phone.id+":"+root.mediaRecord.token : ""
                remoteVolume:root.media.volume||0;remoteRevision:root.mediaRecord.revision||0
                enabled:root.playing&&root.messagingReady&&!!endpoint;opacity:enabled?1:0.35
                unit:Style.space(1);accent:Color.accent;trackColor:Qt.alpha(root.ink,0.12)
                requestIdFactory: root.service ? function() { return root.service.nextRequestId("volume") } : null
                onRequested:function(request,value){root.messagingCommand({op:"media_volume",request_id:request,device:root.phone.id,token:root.mediaRecord.token,value:value})}
                onFailed:function(error){root.messageError=true;root.message=error}
              }
            }
          }

          PanelSeparator { foreground: root.ink }
          Column {
            width: parent.width; spacing: Style.space(10)
            Row {
              width:parent.width
              SectionLabel {width:parent.width-viewAll.width;text:"NOTIFICATIONS"+(root.activeNoteCount?"  /  "+root.activeNoteCount:"");anchors.verticalCenter:parent.verticalCenter}
              QuickButton {id:viewAll;text:"View all";onClicked:root.showNotifications("")}
            }
            Label {
              id: notificationStateWarning
              objectName: "notificationStateWarning"
              width: parent.width; visible: !!root.notificationStateError
              text: root.notificationStateError
              color: Color.urgent; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
            }
            Label {
              width: parent.width; visible: root.activeNoteCount === 0
              text: root.messagingError && !root.notificationStateError ? root.messagingError : !root.online ? "Notifications appear when your phone is connected." : !root.can("notifications") ? "Enable notification sync in KDE Connect on your phone." : "All quiet. You’re caught up."
              color: root.subdued; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
            }
            Flickable {
              id:notificationPreview
              width:parent.width
              height:Math.min(previews.implicitHeight,Style.space(150))
              contentWidth:width;contentHeight:previews.implicitHeight;clip:true
              boundsBehavior:Flickable.StopAtBounds
              QQC.ScrollBar.vertical:QQC.ScrollBar {policy:QQC.ScrollBar.AsNeeded}
              Column {
                id:previews;width:parent.width-Style.space(8);spacing:Style.space(6)
                Repeater {
                  model:notificationModel
                  NotificationPreview {
                    required property string cardKey
                    required property var payload
                    width:previews.width;visible:!!root.phone&&payload.note.device===root.phone.id&&payload.active
                    height:visible?implicitHeight:0
                    note:payload.note;ink:root.ink;accent:Color.accent;fontFamily:root.face
                    smallSize:Style.font.bodySmall;unit:Style.space(1);corner:Style.cornerRadius
                    onActivated:root.showNotifications(cardKey)
                    onActiveFocusChanged:if(activeFocus){var p=mapToItem(previews,0,0);notificationPreview.contentY=Math.max(0,Math.min(p.y,notificationPreview.contentHeight-notificationPreview.height))}
                  }
                }
              }
            }
          }

          PanelSeparator { foreground: root.ink }
          Row {
            width: parent.width
            Label { width: parent.width - settingsButton.width; anchors.verticalCenter: parent.verticalCenter; text: "KDE Connect  ·  Local connection"; color: root.subdued; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
            PocketButton { id: settingsButton; iconText: "󰒓"; tooltipText: "KDE Connect settings"; foreground: root.ink; focusable: true; onClicked: { if(!root.previewMode)Quickshell.execDetached(["kdeconnect-app"]); root.close() } }
          }
        }
      }
    }
  }

  component PocketButton: Button {
    onActiveFocusChanged: if (activeFocus) root.reveal(this)
  }
  component Label: Text {
    textFormat: Text.PlainText
    color: root.ink
    font.family: root.face
    font.pixelSize: Style.font.body
  }
  component SectionLabel: Label { font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.5; color: root.subdued }
  component QuickButton: PocketButton { foreground: root.ink; fontFamily: root.face; fontSize: Style.font.bodySmall; focusable: true; bordered: true; horizontalPadding: Style.space(6); opacity: enabled ? 1 : 0.35 }
  component ActionTile: Rectangle {
    id: tile
    property string title: ""
    property string detail: ""
    property string glyph: ""
    property string verb: ""
    property string feature: ""
    property bool primary: false
    property bool compact: false
    enabled: root.can(feature) && !root.busy
    activeFocusOnTab: enabled
    onActiveFocusChanged: if (activeFocus) root.reveal(this)
    height: Style.space(68)
    radius: Style.cornerRadius
    opacity: enabled ? 1 : 0.35
    color: pointer.containsMouse || activeFocus ? Qt.alpha(Color.accent, 0.18) : Qt.alpha(Color.accent, primary ? 0.1 : 0.035)
    border.width: 1
    border.color: pointer.containsMouse || activeFocus ? Color.accent : Qt.alpha(root.ink, 0.13)
    Behavior on color { ColorAnimation { duration: 120 } }
    Accessible.role: Accessible.Button
    Accessible.name: title
    Accessible.onPressAction: if (enabled) root.run(verb)
    Keys.onReturnPressed: root.run(verb)
    Keys.onSpacePressed: root.run(verb)
    MouseArea { id: pointer; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.run(tile.verb) }
    Column {
      visible: tile.compact; anchors.centerIn: parent; spacing: Style.space(5)
      Label { anchors.horizontalCenter: parent.horizontalCenter; text: tile.glyph; color: Color.accent; font.pixelSize: Style.font.heading }
      Label { anchors.horizontalCenter: parent.horizontalCenter; text: tile.title; font.pixelSize: Style.font.caption }
    }
    Row {
      visible: !tile.compact; anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.margins: Style.space(14); spacing: Style.space(12)
      Label { anchors.verticalCenter: parent.verticalCenter; text: tile.glyph; color: Color.accent; font.pixelSize: Style.font.heading }
      Column {
        width: parent.width - Style.space(62); spacing: Style.space(3)
        Label { text: tile.title; font.bold: true }
        Label { text: tile.detail; font.pixelSize: Style.font.caption; color: root.subdued }
      }
      Label { anchors.verticalCenter: parent.verticalCenter; text: "↗"; color: Color.accent }
    }
  }
}
