// Pure in-memory notification state. Reply drafts are panel-local; service
// notifications and action ownership are shared, but editor text never crosses panels.
function key(device, id) { return JSON.stringify([device, id]) }
function makeCard(note) {
    return {key:key(note.device,note.id),note:note,active:true,editing:false,draft:"",
            draftReply:"",draftInternal:"",draftTitle:"",draftOccurrence:"",draftNotificationEpoch:"",pending:"",sharedPending:"",localRemovePending:"",
            pendingOwner:"",status:"",unavailable:false,usedReply:"",draftGeneration:0}
}
function receive(cards,event,clientId,serviceOwned) {
    var k,c
    if (event.event === "notification") {
        var note=event.notification;k=key(note.device,note.id)
        if(!cards[k] && Object.keys(cards).length>=128) {
            var victim=Object.keys(cards).find(function(id){var x=cards[id];return !x.editing&&!x.draft&&!x.pending&&!x.sharedPending})
            if(victim)delete cards[victim];else return cards
        }
        c=cards[k]||makeCard(note)
        if((c.editing||c.draft) && ((c.note.occurrence_id && c.note.occurrence_id!==note.occurrence_id) ||
           (c.note.notification_epoch && c.note.notification_epoch!==note.notification_epoch))) {
            c.unavailable=true;c.status="Reply no longer available"
        }
        c.note=note;c.active=true;cards[k]=c
    } else if(event.event==="notification_action_pending") {
        k=key(event.device,event.id);c=cards[k]
        if(c && c.note.internal_id===event.internal_id) {
            c.sharedPending=event.request_id;c.pendingOwner=event.owner_id||""
            if(clientId && event.owner_id===clientId) {c.pending=event.request_id;c.status="Sending…"}
            else c.status="An action is in progress on another panel."
        }
    } else if(event.event==="notification_removed" || event.event==="device_offline" || event.event==="worker_stopped") {
        Object.keys(cards).forEach(function(id) {
            c=cards[id]
            if(event.event!=="worker_stopped" && (c.note.device!==event.device ||
                (event.event==="notification_removed" && (c.note.id!==event.id || (event.occurrence_id && c.note.occurrence_id!==event.occurrence_id)))))return
            c.active=false
            if(c.editing||c.draft||c.pending||c.sharedPending) {
                c.unavailable=true
                c.status=c.pending||c.sharedPending?"Connection changed. Check the phone before trying again.":"Reply no longer available"
                c.pending="";c.sharedPending="";c.pendingOwner="";c.localRemovePending=""
            } else delete cards[id]
        })
    } else if(event.event==="notification_local_remove") {
        ;(event.entries||[]).forEach(function(entry) {
            k=entry.key||key(entry.device,entry.id);c=cards[k]
            if(!c || c.note.occurrence_id!==entry.occurrence_id || c.pending || c.sharedPending)return
            c.active=false
            if(c.editing||c.draft) {
                c.unavailable=true;c.status="Removed from Pocket Extended"
            } else delete cards[k]
        })
    } else if(event.event==="notification_action_result" || event.event==="error") {
        Object.keys(cards).forEach(function(id) {
            c=cards[id]
            if(c.sharedPending!==event.request_id && c.pending!==event.request_id)return
            var isOwner=!!clientId && event.owner_id===clientId && c.pending===event.request_id
            if(c.sharedPending===event.request_id){c.sharedPending="";c.pendingOwner=""}
            if(event.accepted && event.action==="notification_reply") {
                c.usedReply=event.reply_id||c.draftReply
                if(!isOwner && (c.editing||c.draft)) {
                    c.unavailable=true;c.status="Reply token was used on another panel. Draft saved."
                }
            }
            if(!isOwner) {
                if(c.status==="An action is in progress on another panel.")c.status=""
                return
            }
            c.pending=""
            if(event.accepted && event.action==="notification_reply") {
                c.draft="";c.editing=false;c.status="Submitted to KDE Connect";c.unavailable=false
                c.draftReply="";c.draftInternal="";c.draftTitle="";c.draftOccurrence="";c.draftNotificationEpoch=""
            } else if(event.accepted) {
                c.status=c.editing&&!c.active?"Reply no longer available":"Dismissed"
            } else {
                c.status=event.error||"Action could not be completed"
                if(c.status==="Reply no longer available")c.unavailable=true
            }
            if(!c.active&&!c.editing&&!c.draft)delete cards[id]
        })
    }
    return cards
}
function canReply(c) { return !!(c.active && !c.localRemovePending && c.note.occurrence_id && c.note.notification_epoch && c.note.reply_id && c.usedReply!==c.note.reply_id) }
function begin(c) {
    if(!canReply(c)||c.sharedPending||c.pending||c.localRemovePending)return false
    c.editing=true;c.unavailable=false;c.status=""
    c.draftReply=c.note.reply_id;c.draftInternal=c.note.internal_id
    c.draftTitle=c.note.title||c.note.app
    c.draftOccurrence=c.note.occurrence_id||"";c.draftNotificationEpoch=c.note.notification_epoch||""
    return true
}
function discard(c) {
    if(c.pending||c.sharedPending)return
    c.editing=false;c.draft="";c.status="";c.unavailable=false
    c.draftReply="";c.draftInternal="";c.draftTitle="";c.draftOccurrence="";c.draftNotificationEpoch=""
}
function replyCommand(c,request) {
    if(!c.editing||c.unavailable||!canReply(c)||!c.draft.trim()||c.pending||c.sharedPending||c.localRemovePending||
       c.draftReply!==c.note.reply_id||c.draftInternal!==c.note.internal_id||
       c.draftOccurrence!==(c.note.occurrence_id||"")||c.draftNotificationEpoch!==(c.note.notification_epoch||""))return null
    c.pending=request;c.status="Sending…"
    return {op:"notification_reply",request_id:request,device:c.note.device,id:c.note.id,
            internal_id:c.draftInternal,reply_id:c.draftReply,text:c.draft,
            occurrence_id:c.draftOccurrence,notification_epoch:c.draftNotificationEpoch}
}
function dismissCommand(c,request) {
    if(!c.active||!c.note.occurrence_id||!c.note.notification_epoch||!c.note.dismissable||c.pending||c.sharedPending||c.localRemovePending)return null
    c.pending=request;c.status="Dismissing…"
    return {op:"notification_dismiss",request_id:request,device:c.note.device,id:c.note.id,
            internal_id:c.note.internal_id,occurrence_id:c.note.occurrence_id,
            notification_epoch:c.note.notification_epoch||""}
}
