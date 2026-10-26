pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import "NotificationState.js" as NotificationState
import "HistoryState.js" as HistoryState
import "MediaState.js" as MediaState
import "ServiceEpoch.js" as ServiceEpoch

// One instance is created by Omarchy for the plugin, independently of the
// number of monitor-specific bar widgets.  All messaging state and the worker
// therefore have one owner and one command stream.
Item {
  id: service

  property var shell: null
  readonly property string pluginId: "io.github.oidium.pocket-extended"
  readonly property string bridge: decodeURIComponent(Qt.resolvedUrl("bridge.py").toString().replace(/^file:\/\//, ""))
  readonly property string messagingWorker: decodeURIComponent(Qt.resolvedUrl("messaging_service.py").toString().replace(/^file:\/\//, ""))

  property var dependencies: ({})
  property var devices: []
  property bool loaded: false
  property string connectionError: ""
  property var notificationCards: ({})
  // Local cleanup tombstones prevent older snapshots from restoring removed cards.
  property var localNotificationRemovals: ({})
  property var notificationOccurrences: ({})
  property string notificationWorkerEpoch: ""
  property double notificationRevisionWatermark: 0
  readonly property int maxNotificationOccurrences: 4096
  property var localRemovalRequests: ({})
  property double requestSequence: 0
  property int panelSequence: 0
  property var panelDraftSnapshots: ({})
  property var panelDraftOwners: ({})
  readonly property int maxPanelDraftOwners: 8
  readonly property string serviceEpoch: ServiceEpoch.next()
  property var notificationActionOwners: ({})
  property bool messagingReady: false
  property string messagingError: ""
  property string notificationStateError: ""
  property int messagingRestarts: 0
  // Process.onExited is also delivered while the service is being torn down.
  // Keep destruction from scheduling a new worker after plugin disable/reload.
  property bool shuttingDown: false
  property var historyState: HistoryState.create()
  property var mediaStates: ({})
  property var remoteMedia: ({})
  property var callEvents: []

  signal eventReceived(var event)
  signal openRequested()
  signal closeRequested()
  signal toggleRequested()

  function publish(event) { eventReceived(event) }

  // Request ids cross the shared worker/event stream, so allocate them here
  // rather than in monitor-local Panel instances.
  function nextRequestId(prefix) {
    requestSequence += 1
    return serviceEpoch + "-" + String(prefix) + "-" + String(requestSequence)
  }

  function registerPanel(slot) {
    panelSequence += 1
    var client=serviceEpoch + "-panel-" + String(panelSequence)
    if(typeof slot==="string" && slot.length>0 && slot.length<=512) {
      var owners=Object.assign({},panelDraftOwners)
      if(Object.keys(owners).length>=32)delete owners[Object.keys(owners)[0]]
      owners[client]=slot;panelDraftOwners=owners
    }
    return client
  }

  function unregisterPanel(client) {
    if(!panelDraftOwners[client])return
    var owners=Object.assign({},panelDraftOwners);delete owners[client];panelDraftOwners=owners
  }

  function prunePanelDraftSnapshots() {
    var next=Object.assign({},panelDraftSnapshots),changed=false
    Object.keys(next).forEach(function(slot){if(Date.now()-next[slot].savedAt>30*24*60*60*1000){delete next[slot];changed=true}})
    if(changed)panelDraftSnapshots=next
  }

  function panelDraftSnapshot(slot) {
    prunePanelDraftSnapshots()
    var saved=panelDraftSnapshots[slot]
    if(!saved)return null
    if(Date.now()-saved.savedAt>30*24*60*60*1000) {
      var next=Object.assign({},panelDraftSnapshots);delete next[slot];panelDraftSnapshots=next
      return null
    }
    return JSON.parse(JSON.stringify(saved.state))
  }

  function savePanelDraftSnapshot(client, slot, state) {
    prunePanelDraftSnapshots()
    if(!client || panelDraftOwners[client]!==slot || !state || typeof slot!=="string" || slot.length>512)return false
    if(!Array.isArray(state.sms) || state.sms.length>32 || !Array.isArray(state.notifications) || state.notifications.length>32)return false
    if(JSON.stringify(state).length>3*1024*1024)return false
    if(!state.sms.length && !state.notifications.length) {
      var cleared=Object.assign({},panelDraftSnapshots);delete cleared[slot];panelDraftSnapshots=cleared;return true
    }
    var saved=Object.assign({},panelDraftSnapshots)
    if(!saved[slot] && Object.keys(saved).length>=maxPanelDraftOwners) {
      var expired=Object.keys(saved).find(function(key){return Date.now()-saved[key].savedAt>30*24*60*60*1000})
      if(expired)delete saved[expired];else return false
    }
    saved[slot]={savedAt:Date.now(),state:JSON.parse(JSON.stringify(state))}
    panelDraftSnapshots=saved
    return true
  }

  function notificationSnapshot() {
    return Object.keys(notificationCards).filter(function(key) {
      var card=notificationCards[key]
      return localNotificationRemovals[key]!==card.note.occurrence_id
    }).map(function(key) {
      var card = notificationCards[key]
      return {key:key, note:JSON.parse(JSON.stringify(card.note)), active:card.active,
        usedReply:card.usedReply || "", pending:card.pending || "",
        pendingOwner:card.pendingOwner || "", status:card.status || "",
        unavailable:!!card.unavailable}
    })
  }

  function removeLocalNotifications(clientId, entries) {
    if (!clientId || !Array.isArray(entries) || !messagingReady || !messaging.running)
      return {accepted:false, error:"Pocket messaging service is unavailable"}
    var safe=[], pending=0
    if(entries.length>128)return {accepted:false,capacity:true,error:"Local notification state capacity reached. Remove notifications in smaller groups."}
    entries.forEach(function(entry) {
      if (!entry || typeof entry.device!=="string" || typeof entry.id!=="string" ||
          typeof entry.occurrence_id!=="string" || !entry.occurrence_id) return
      var key=NotificationState.key(entry.device,entry.id),card=notificationCards[key]
      if(card && (card.pending||card.sharedPending||card.localRemovePending)) {pending++;return}
      var active=notificationOccurrences[key]===entry.occurrence_id
      var alreadyClosed=!notificationOccurrences[key] && (!card || !card.active)
      if(!active&&!alreadyClosed)return
      if(!safe.some(function(old){return old.device===entry.device&&old.id===entry.id}))
        safe.push({device:entry.device,id:entry.id,occurrence_id:entry.occurrence_id,closed:!active})
    })
    if(!safe.length)return {accepted:false,pending:pending,capacity:entries.length>128,
      error:pending?"Some notifications are still processing. Clear them after the action finishes.":
        entries.length>128?"Local notification state capacity reached. Remove notifications in smaller groups.":"No removable notifications were accepted"}
    var request=nextRequestId("local-remove")
    localRemovalRequests[request]={clientId:clientId,entries:safe,workerEpoch:notificationWorkerEpoch}
    localRemovalRequests=Object.assign({},localRemovalRequests)
    var durable=safe.filter(function(entry){return !entry.closed})
    if(durable.length) {
      var sent=messagingCommand({op:"notification_local_remove",request_id:request,entries:durable})
      if(!sent){delete localRemovalRequests[request];localRemovalRequests=Object.assign({},localRemovalRequests);return {accepted:false,error:"Pocket messaging service is unavailable"}}
    } else {
      Qt.callLater(function(){service.messagingEvent({event:"notification_local_remove",request_id:request,entries:[],volatile_closed:safe})})
    }
    return {accepted:true,request_id:request,pending:pending,entries:safe}
  }

  function submitNotificationAction(clientId, draftCommand) {
    if (!messagingReady || !messaging.running || !clientId || !draftCommand) return ""
    var key = NotificationState.key(draftCommand.device, draftCommand.id)
    var card = notificationCards[key]
    if (!card || !card.active || card.pending ||
        card.note.internal_id !== draftCommand.internal_id ||
        !card.note.occurrence_id || draftCommand.occurrence_id!==card.note.occurrence_id ||
        !notificationWorkerEpoch || draftCommand.notification_epoch!==notificationWorkerEpoch ||
        card.note.notification_epoch!==notificationWorkerEpoch) return ""
    var op = draftCommand.op
    var command
    if (op === "notification_reply") {
      if (typeof draftCommand.reply_id !== "string" || !draftCommand.reply_id ||
          card.note.reply_id !== draftCommand.reply_id || card.usedReply === draftCommand.reply_id ||
          typeof draftCommand.text !== "string" || !draftCommand.text.trim() || draftCommand.text.length > 16384)
        return ""
      command = {op:op, request_id:"", device:card.note.device, id:card.note.id,
        internal_id:card.note.internal_id, reply_id:draftCommand.reply_id, text:draftCommand.text,
        occurrence_id:draftCommand.occurrence_id,notification_epoch:draftCommand.notification_epoch}
    } else if (op === "notification_dismiss") {
      if (!card.note.dismissable) return ""
      command = {op:op, request_id:"", device:card.note.device, id:card.note.id,
        internal_id:card.note.internal_id,occurrence_id:draftCommand.occurrence_id,
        notification_epoch:draftCommand.notification_epoch}
    } else return ""

    var request = nextRequestId("notification")
    command.request_id = request
    card.pending = request
    card.sharedPending = request
    card.pendingOwner = clientId
    card.status = op === "notification_reply" ? "Sending…" : "Dismissing…"
    notificationCards = Object.assign({}, notificationCards)
    notificationActionOwners[request] = {clientId:clientId, key:key, action:op,
      replyId:command.reply_id || "", internalId:card.note.internal_id,
      id:card.note.id, device:card.note.device,occurrenceId:command.occurrence_id,
      notificationEpoch:command.notification_epoch}
    publish({event:"notification_action_pending", device:card.note.device, id:card.note.id,
      internal_id:card.note.internal_id, request_id:request, owner_id:clientId})
    messagingCommand(command)
    return request
  }

  function normalizeWorkerDevice(raw) {
    if(!raw || typeof raw!=="object" || Array.isArray(raw) || typeof raw.id!=="string" ||
       raw.id.length>256 || !/^[A-Za-z0-9_]+$/.test(raw.id))return null
    var nameValid=raw.name_valid!==false && typeof raw.name==="string" && raw.name.length>0 &&
      MediaState.safeText(raw.name,256)===raw.name && !/[\x00-\x1F\x7F]/.test(raw.name)
    var plugins=null,capabilities=raw.online===true?"pending":"offline"
    if(raw.plugins!==null && raw.plugins!==undefined) {
      var valid=Array.isArray(raw.plugins) && raw.plugins.length<=128 &&
        raw.plugins.every(function(x){return typeof x==="string"&&/^[A-Za-z0-9_.-]{1,128}$/.test(x)&&MediaState.byteLength(x)<=128})
      plugins=valid?MediaState.exactIds(raw.plugins,128,128):[]
      capabilities=valid?"available":"unavailable"
    }
    return {id:raw.id,name:nameValid?raw.name:"Phone",name_valid:nameValid,online:raw.online===true,
      plugins:plugins,capabilities:capabilities,generation:Number.isInteger(raw.generation)&&raw.generation>=0?raw.generation:0}
  }

  function messagingEvent(event) {
    if(event.event==="device") {
      var safeDevice=normalizeWorkerDevice(event.device)
      if(!safeDevice)return
      event=Object.assign({},event,{device:safeDevice})
    }
    if(event.event==="ready") {
      notificationWorkerEpoch=String(event.notification_epoch||"")
      notificationRevisionWatermark=Number(event.notification_revision)||0
      var occurrences=({}),removed=({})
      ;(event.notification_occurrences||[]).forEach(function(item){
        if(!item||typeof item.device!=="string"||typeof item.id!=="string"||typeof item.occurrence_id!=="string")return
        var key=NotificationState.key(item.device,item.id);occurrences[key]=item.occurrence_id
        if(item.removed)removed[key]=item.occurrence_id
      })
      notificationOccurrences=occurrences;localNotificationRemovals=removed
    }
    var actionOwner = notificationActionOwners[event.request_id]
    if (actionOwner && (event.event === "notification_action_result" || event.event === "error")) {
      event = Object.assign({}, event, {owner_id:actionOwner.clientId,
        action:actionOwner.action, id:event.id || actionOwner.id,
        device:event.device || actionOwner.device,
        reply_id:actionOwner.replyId, notification_key:actionOwner.key})
      var actionCard = notificationCards[actionOwner.key]
      if (actionCard && actionCard.pending === event.request_id) {
        actionCard.pending = ""
        actionCard.sharedPending = ""
        actionCard.pendingOwner = ""
        actionCard.status = event.accepted ? "Submitted to KDE Connect" : (event.error || "Action could not be completed")
        if (event.accepted && actionOwner.action === "notification_reply")
          actionCard.usedReply = actionOwner.replyId
        notificationCards = Object.assign({}, notificationCards)
      }
      delete notificationActionOwners[event.request_id]
    }
    if(event.event==="notification" && event.notification) {
      if(!event.notification.occurrence_id || event.notification_epoch!==notificationWorkerEpoch)return
      event=Object.assign({},event,{notification:Object.assign({},event.notification,{notification_epoch:event.notification_epoch})})
      var notificationKey=NotificationState.key(event.notification.device,event.notification.id)
      var revision=Number(event.notification.revision)||0
      if(!revision || revision<=notificationRevisionWatermark)return
      var priorOccurrence=notificationOccurrences[notificationKey]
      if(!priorOccurrence && Object.keys(notificationOccurrences).length>=maxNotificationOccurrences) {
        messagingError="Notification tracking capacity reached. Refresh after notification activity settles; new cards are temporarily unavailable."
        publish({event:"notification_state_capacity",error:messagingError})
        return
      }
      notificationRevisionWatermark=revision
      if(priorOccurrence && priorOccurrence!==event.notification.occurrence_id && localNotificationRemovals[notificationKey]===priorOccurrence) {
        delete localNotificationRemovals[notificationKey]
        localNotificationRemovals=Object.assign({},localNotificationRemovals)
      }
      notificationOccurrences[notificationKey]=event.notification.occurrence_id
      notificationOccurrences=Object.assign({},notificationOccurrences)
      if(localNotificationRemovals[notificationKey]===event.notification.occurrence_id)return
    }
    if(event.event==="notification_removed") {
      var removedKey=NotificationState.key(event.device,event.id)
      var removedRevision=Number(event.revision)||0
      if(event.notification_epoch!==notificationWorkerEpoch || !removedRevision ||
          removedRevision<=notificationRevisionWatermark ||
          (event.occurrence_id && notificationOccurrences[removedKey] && event.occurrence_id!==notificationOccurrences[removedKey]))return
      notificationRevisionWatermark=removedRevision
      if(event.authoritative && notificationOccurrences[removedKey]===event.occurrence_id) {
        delete notificationOccurrences[removedKey]
        delete localNotificationRemovals[removedKey]
        notificationOccurrences=Object.assign({},notificationOccurrences)
        localNotificationRemovals=Object.assign({},localNotificationRemovals)
      }
    }
    if(event.event==="notification_local_remove" || event.event==="notification_local_remove_failed" ||
       event.event==="notification_local_remove_capacity" || event.event==="notification_local_remove_result") {
      var ownedRemoval=localRemovalRequests[event.request_id]
      if(!ownedRemoval || ownedRemoval.workerEpoch!==notificationWorkerEpoch)return
    }
    if(event.event==="notification_local_remove") {
      var requestState=localRemovalRequests[event.request_id]
      ;(event.entries||[]).forEach(function(entry){
        var key=NotificationState.key(entry.device,entry.id)
        if(notificationOccurrences[key]===entry.occurrence_id)localNotificationRemovals[key]=entry.occurrence_id
      })
      var completedRemoval=localRemovalRequests[event.request_id]
      ;((event.volatile_closed||[]).concat(completedRemoval?completedRemoval.entries.filter(function(entry){
        var key=NotificationState.key(entry.device,entry.id),card=notificationCards[key]
        return entry.closed&&!notificationOccurrences[key]&&(!card||!card.active)&&(!card||card.note.occurrence_id===entry.occurrence_id)
      }):[])).forEach(function(entry){
        // Closed entries are already absent from authoritative worker state.
        // Publish completion to panels so their local drafts/cards can settle,
        // but do not retain a volatile tombstone in the service-wide map.
        if(!(event.entries||[]).some(function(saved){return saved.device===entry.device&&saved.id===entry.id&&saved.occurrence_id===entry.occurrence_id}))
          event.entries=(event.entries||[]).concat([{device:entry.device,id:entry.id,occurrence_id:entry.occurrence_id}])
      })
      localNotificationRemovals=Object.assign({},localNotificationRemovals)
      event.client_id=requestState?requestState.clientId:""
      delete localRemovalRequests[event.request_id];localRemovalRequests=Object.assign({},localRemovalRequests)
    } else if(event.event==="notification_local_remove_failed" || event.event==="notification_local_remove_capacity" || event.event==="notification_local_remove_result") {
      var failedRequest=localRemovalRequests[event.request_id]
      event.client_id=failedRequest.clientId
      delete localRemovalRequests[event.request_id];localRemovalRequests=Object.assign({},localRemovalRequests)
    }
    if (event.event === "media_state") {
      remoteMedia[event.device] = {
        media: MediaState.normalizeMedia(event.media),
        token: typeof event.token === "string" && event.token.length <= 128 ? event.token : "",
        revision: Number.isInteger(event.revision) && event.revision >= 0 ? event.revision : 0
      }
      remoteMedia = Object.assign({}, remoteMedia)
      publish(event)
      return
    }
    if (event.event === "device_offline") {
      delete remoteMedia[event.device]
      remoteMedia = Object.assign({}, remoteMedia)
      callEvents = callEvents.filter(function(c) { return c.device !== event.device })
      var retainedOccurrences=Object.assign({},notificationOccurrences)
      Object.keys(retainedOccurrences).forEach(function(key) {
        try { if(JSON.parse(key)[0]===event.device)delete retainedOccurrences[key] } catch(e) {}
      })
      notificationOccurrences=retainedOccurrences
    }
    if (event.event === "worker_stopped") {
      remoteMedia = {}
      callEvents = []
      messagingReady = false
      notificationWorkerEpoch = ""
      notificationOccurrences = ({})
      notificationActionOwners = ({})
      Object.keys(localRemovalRequests).forEach(function(request) {
        var pending=localRemovalRequests[request]
        publish({event:"notification_local_remove_uncertain",request_id:request,
          client_id:pending.clientId,notification_epoch:pending.workerEpoch,
          error:"Local notification cleanup may have completed before the worker stopped. Refresh and review the list."})
      })
      localRemovalRequests = ({})
    } else if (event.event === "call_events") {
      callEvents = event.calls
    }
    if (event.event === "ready") {
      messagingReady = true
      if (Object.prototype.hasOwnProperty.call(event,"notification_state_error"))
        notificationStateError=String(event.notification_state_error||"")
      messagingError = ""
    }
    if ((event.event === "error" || event.event === "notification_state_capacity") && !event.request_id) messagingError = event.error
    if (event.event !== "notification_action_result" && !(event.event === "error" && event.owner_id))
      NotificationState.receive(notificationCards, event, "", true)
    notificationCards = Object.assign({}, notificationCards)
    HistoryState.receive(historyState, event)
    MediaState.receive(mediaStates, event)
    MediaState.prune(mediaStates, historyState)
    mediaStates = JSON.parse(JSON.stringify(mediaStates))
    historyState = Object.assign({}, historyState)
    publish(event)
  }

  function messagingCommand(command) {
    if (!messagingReady || !messaging.running) {
      messagingEvent({event: "error", request_id: command.request_id,
        error: "Messaging service is unavailable"})
      return false
    }
    messaging.write(JSON.stringify(command) + "\n")
    return true
  }

  function refresh() {
    if (!snapshot.running) snapshot.running = true
  }

  function refreshAll() {
    refresh()
    // An explicit Refresh can recover an exhausted worker, but a pair of
    // monitor controls must still start only this one service-owned process.
    if (!messaging.running) {
      messagingRestart.stop()
      messagingRestarts = 0
      messagingReady = false
      messaging.running = true
      return
    }
    if (messagingReady)
      messagingCommand({op: "refresh", request_id: nextRequestId("refresh")})
  }

  function loadHistory(device, thread, requestId) {
    var command = HistoryState.load(historyState, device, thread, requestId)
    historyState = Object.assign({}, historyState)
    if (command) messagingCommand(command)
  }

  function mediaRequest(message, attachment, requestId, open) {
    var command = MediaState.command(mediaStates, message, attachment, requestId, open)
    mediaStates = JSON.parse(JSON.stringify(mediaStates))
    if (command) messagingCommand(command)
  }


  Process {
    id: messaging
    command: ["python3", service.messagingWorker]
    stdinEnabled: true
    running: true
    stdout: SplitParser {
      onRead: function(line) {
        try { service.messagingEvent(JSON.parse(line)) }
        catch (e) { service.messagingError = "Could not read messaging updates." }
      }
    }
    onExited: {
      service.messagingReady = false
      service.messagingEvent({event: "worker_stopped"})
      service.messagingError = "Messaging service stopped."
      if (!service.shuttingDown && service.messagingRestarts < 3) messagingRestart.restart()
    }
  }

  Timer {
    id: messagingRestart
    interval: 2000
    onTriggered: { service.messagingRestarts += 1; messaging.running = true }
  }

  Process {
    id: snapshot
    command: ["python3", service.bridge, "snapshot"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          service.dependencies = result.dependencies || {}
          service.devices = MediaState.normalizeSnapshot(result.devices)
          service.connectionError = result.ok ? "" : (result.error || "Could not reach KDE Connect. Open its settings and try again.")
        } catch (e) {
          service.devices = []
          service.connectionError = "Could not read device status. Try Refresh."
        }
        service.loaded = true
      }
    }
  }

  IpcHandler {
    target: service.pluginId
    function open(): void { service.openRequested() }
    function show(): void { service.openRequested() }
    function close(): void { service.closeRequested() }
    function hide(): void { service.closeRequested() }
    function toggle(): void { service.toggleRequested() }
    function refresh(): void { service.refreshAll() }
  }

  Timer { interval: 3600000; repeat: true; running: true; onTriggered: service.prunePanelDraftSnapshots() }

  Component.onCompleted: {
    service.shuttingDown = false
    service.refresh()
  }
  Component.onDestruction: {
    service.shuttingDown = true
    messagingRestart.stop()
    messaging.running = false
    snapshot.running = false
  }
}
