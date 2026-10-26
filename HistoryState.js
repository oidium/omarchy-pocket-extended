// Ephemeral view of KDE Connect records, never a second messaging database.
var MAX_THREADS = 200
var MAX_MESSAGES = 300
function create() { return {threads:{},contacts:{},online:{},loaded:{},available:{},errors:{},replyUncertainDevices:{},replyUncertainAll:false} }
function key(device,thread) { return JSON.stringify([device,String(thread)]) }
function numberKey(value) {
    var n=String(value).replace(/[^0-9]/g, "")
    // KDE Connect may mix NANP local numbers and their +1/E.164 form.
    if(n.length===11 && n.charAt(0)==="1") n=n.slice(1)
    return /^[0-9]{3,}$/.test(n)?n:null
}
function name(state,device,address) {
    var matches=(state.contacts[device]||[]).filter(function(c) {
        return numberKey(address)!==null && c.numbers.some(function(n) { return numberKey(n.number)===numberKey(address) })
    })
    return matches.length===1 && matches[0].name ? matches[0].name : address
}
function participants(state,device,addresses) {
    return addresses.map(function(a) { var n=name(state,device,a);return n===a?a:n+"\n"+a }).join("\n\n") || "Unknown participant"
}
function compare(a,b) {
    if (a.timestamp!==b.timestamp) return b.timestamp-a.timestamp
    // Decimal identities remain strings, including beyond JS integer precision.
    return b.message_id.length-a.message_id.length || b.message_id.localeCompare(a.message_id)
}
function messages(thread) { return Object.keys(thread.messages).map(function(k) {return thread.messages[k]}).sort(compare) }
function observedReplyStatus(event,m) {
    if (event.reply_status === "group" || event.reply_status === "incomplete" || event.reply_status === "individual" || event.reply_status === "unknown")
        return event.reply_status
    var a=m.addresses
    if(Array.isArray(a)&&a.length>1)return "group"
    if(!Array.isArray(a)||a.length!==1||m.addresses_complete===false)return "incomplete"
    return "individual"
}
function effectiveReplyStatus(state,device,observed) {
    return state.replyUncertainAll || state.replyUncertainDevices["$"+device] ? "unknown" : observed
}
// Keep the reason for a restriction separate from its displayed status.
// Missing risk metadata on an incomplete event means sticky, never recoverable.
function receiveAuthorization(state,t,event,observed,scope) {
    var previous=t.replyRisk||((t.replyStatus==="group"||t.replyStatus==="incomplete")?t.replyStatus:"")
    var incoming=observed==="group"?"group":observed==="incomplete"?(event.reply_risk==="ordering"?"ordering":"incomplete"):""
    var recovered=previous==="ordering"&&observed==="individual"&&event.reply_scope_recovered===true&&
        !!event.conversation_token&&event.conversation_token!==(t.token||"")&&Array.isArray(scope)&&scope.length===1
    if(previous==="group"||incoming==="group")t.replyRisk="group"
    else if(previous==="incomplete"||incoming==="incomplete")t.replyRisk="incomplete"
    else if(incoming==="ordering"||(previous==="ordering"&&!recovered))t.replyRisk="ordering"
    else t.replyRisk=""
    var status=t.replyRisk==="ordering"?"incomplete":t.replyRisk||observed
    t.replyStatus=effectiveReplyStatus(state,t.device,status)
    t.replyScope=t.replyStatus==="individual"&&Array.isArray(scope)?scope.slice():null
    if(event.conversation_token)t.token=event.conversation_token
}
function receive(state,event) {
    var t,k
    if (event.event==="contacts") state.contacts[event.device]=event.contacts||[]
    else if(event.event==="reply_scope") {
        t=state.threads[key(event.device,event.thread)]
        if(t) {
            receiveAuthorization(state,t,event,event.reply_status,event.recipient_scope)
        }
    } else if(event.event==="reply_scope_uncertain") {
        if(event.all===true) {
            state.replyUncertainAll=true
            state.replyUncertainDevices={}
        } else if(typeof event.device==="string") state.replyUncertainDevices["$"+event.device]=true
        Object.keys(state.threads).forEach(function(id) {
            t=state.threads[id]
            if(event.all===true||t.device===event.device){t.replyStatus="unknown";t.replyScope=null}
        })
    }
    else if (event.event==="device") {
        state.online[event.device.id]=!!event.device.online
        if(event.device.plugins) state.available[event.device.id]=event.device.plugins.indexOf("kdeconnect_sms")>=0
    }
    else if (event.event==="threads_refreshed") {state.loaded[event.device]=true;delete state.errors[event.device]}
    else if (event.event==="threads_error") state.errors[event.device]=event.error
    else if (event.event==="message") {
        var m=event.message;k=key(m.device_id,m.thread_id)
        t=state.threads[k]
        if (!t) t=state.threads[k]={device:m.device_id,id:m.thread_id,messages:{},order:[],head:null,stale:false,pending:"",status:"",bounded:false,replyStatus:"unknown",replyScope:null,replyRisk:""}
        if(t.stale) t.head=null
        t.stale=false
        receiveAuthorization(state,t,event,observedReplyStatus(event,m),
            Array.isArray(event.recipient_scope)?event.recipient_scope:m.addresses)
        if(!t.messages[m.message_id])t.order.push(m.message_id)
        t.messages[m.message_id]=m
        if (!t.head || compare(m,t.head)<=0 || t.head.message_id===m.message_id) t.head=m
        if (t.order.length>MAX_MESSAGES) { delete t.messages[t.order.shift()];t.bounded=true }
        var keys=Object.keys(state.threads)
        if (keys.length>MAX_THREADS) delete state.threads[keys[0]]
    } else if (event.event==="messages_evicted") {
        t=state.threads[key(event.device,event.thread)]
        if(t){event.ids.forEach(function(id){delete t.messages[id]});t.order=t.order.filter(function(id){return !!t.messages[id]});t.bounded=true}
    } else if (event.event==="history_result") {
        t=state.threads[key(event.device,event.thread)]
        if (t && t.pending===event.request_id) {
            t.pending=""
            t.status=event.reason==="disconnected"?"Phone disconnected — refresh history":event.received?"Available history updated":"No additional history received. You can try again."
        }
    } else if (event.event==="error") {
        Object.keys(state.threads).forEach(function(id) {t=state.threads[id];if(t.pending===event.request_id){t.pending="";t.status=event.error}})
    } else if (event.event==="thread_removed" || event.event==="thread_evicted") delete state.threads[key(event.device,event.thread)]
    else if (event.event==="device_offline" || event.event==="worker_stopped") {
        Object.keys(state.threads).forEach(function(id) {
            t=state.threads[id]
            if(event.event==="worker_stopped"||t.device===event.device){t.stale=true;t.messages={};t.order=[];t.pending="";t.status="Reconnect to refresh history"}
        })
        if(event.event==="worker_stopped"){
            state.online={};state.loaded={}
            // A new worker has a new Store and no surviving safety evidence.
            state.replyUncertainDevices={};state.replyUncertainAll=false
            Object.keys(state.threads).forEach(function(id) {
                var thread=state.threads[id]
                thread.replyStatus="unknown"
                thread.replyRisk=""
                thread.replyScope=null
                thread.token=""
                thread.head=null
            })
        }
        else {state.online[event.device]=false;state.loaded[event.device]=false}
    }
    ;[state.contacts,state.online,state.loaded,state.available,state.errors].forEach(function(map) {
        var ids=Object.keys(map);while(ids.length>16)delete map[ids.shift()]
    })
}
function threads(state,device) {
    return Object.keys(state.threads).map(function(k){return state.threads[k]}).filter(function(t){return t.device===device&&t.head}).sort(function(a,b){return compare(a.head,b.head)})
}
function hasReplyAuthorization(t) {return !!t&&t.replyStatus==="individual"&&Array.isArray(t.replyScope)&&t.replyScope.length===1}
function summary(t) {return {id:t.id,head:t.head,replyScope:t.replyScope||[],replyStatus:t.replyStatus||"unknown",replyBlocked:!hasReplyAuthorization(t),group:t.replyStatus==="group"||Object.keys(t.messages).some(function(k){var a=t.messages[k].addresses;return a&&a.length>1}),stale:t.stale,pending:t.pending,status:t.status,bounded:t.bounded}}
function load(state,device,thread,request) {
    var t=state.threads[key(device,thread)]
    if(!t||t.pending||t.stale) return null
    t.pending=request;t.status="Loading available history…"
    return {op:"history",device:device,thread:thread,request_id:request,size:25}
}
function replyBlockText(status) {
    return status==="group" ? "Group replies are unavailable for recipient safety." :
        status==="incomplete" ? "Recipient list is incomplete — refresh history before replying." :
        status==="individual" ? "" : "Recipient scope is not verified — refresh history before replying."
}
function timestamp(value) {
    var date=new Date(value)
    return isNaN(date.getTime())?"":date.toLocaleString()
}
function sender(state,m) {
    return m.direction==="outgoing"?"You":m.direction==="incoming"?participants(state,m.device_id,m.addresses):"Unknown direction"
}
function status(m) {
    // Android's read bit is intentionally absent: it is not a recipient receipt.
    return ({received:"Incoming",sent:"Sent",outbox:"Outbox",failed:"Failed",queued:"Queued",draft:"Draft"})[m.state]||"Unknown state"
}
