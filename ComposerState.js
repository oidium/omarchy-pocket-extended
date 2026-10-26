function create() { return {device:"",thread:"",conversationToken:"",recipientScope:[],participants:"",recipient:"",text:"",files:[],contacts:[],contactsLoading:false,contactsError:"",contactsWarning:"",contactsRequest:"",pending:"",pickerRequest:"",status:"",open:false} }
function limitText(text,limit) {
    var result=text.slice(0,limit),last=result.charCodeAt(result.length-1)
    return last>=0xD800&&last<=0xDBFF?result.slice(0,-1):result
}
function reserve(drafts,key) {
    if(drafts[key] || Object.keys(drafts).length<32)return true
    var empty=Object.keys(drafts).find(function(k){var d=drafts[k];return !d.text&&!d.files.length&&!d.pending&&!d.pickerRequest})
    if(empty){delete drafts[empty];return true}
    return false
}
function receive(c,event) {
    if (c.device && typeof event.device === "string" && event.device !== c.device) return
    if (event.event === "contacts") {
        c.contacts = Array.isArray(event.contacts) ? event.contacts : []
        c.contactsLoading=false;c.contactsRequest="";c.contactsError=event.error||""
        c.contactsWarning=event.skipped?"Some contacts could not be loaded. Manual number entry remains available.":""
    }
    else if (event.event === "files_selected" && event.request_id === c.pickerRequest) {
        c.pickerRequest = ""
        if (!event.cancelled) {
            event.files.forEach(function(f) { if (c.files.length<32 && !c.files.some(function(old) { return old.path === f.path })) c.files.push(f) })
            c.status = ""
        }
    } else if (event.event === "sms_result" && event.request_id === c.pending) {
        c.pending = ""
        if (event.accepted && !event.uncertain) { c.text=""; c.files=[]; c.status="Submitted to KDE Connect"; if(!c.thread){c.recipient="";c.open=false} }
        else c.status=event.error || "Could not send. Your draft is saved."
    } else if (event.event === "error") {
        if (event.request_id === c.pending) { c.pending="";c.status=event.error }
        if (event.request_id === c.pickerRequest) { c.pickerRequest="";c.status=event.error }
        if (event.request_id && event.request_id===c.contactsRequest) {
            c.contactsRequest="";c.contactsLoading=false;c.contactsError=event.error||"Could not load contacts."
        }
    } else if (event.event === "worker_stopped") {
        if (c.pending || c.pickerRequest) c.status="Connection changed. Check the phone and file selection before trying again."
        if(c.contactsLoading)c.contactsError="Contact loading stopped. Try again."
        c.pending="";c.pickerRequest="";c.contactsLoading=false;c.contactsRequest=""
    }
}
function send(c,device,request,replyStatus) {
    if (c.pending || c.pickerRequest || (!c.thread && !c.recipient.trim()) || (!c.text.trim() && !c.files.length)) return null
    if (c.thread && (!Array.isArray(c.recipientScope) || c.recipientScope.length !== 1)) return null
    if (c.thread && replyStatus !== "individual") return null
    c.pending=request;c.status="Sending…"
    return {op:c.thread ? "sms_reply" : "sms_send",thread:c.thread,conversation_token:c.conversationToken,recipient_scope:(c.recipientScope||[]).slice(),request_id:request,device:device,recipient:c.recipient,text:c.text,files:c.files.map(function(f) {return f.path})}
}
function contactChoices(contacts,search) {
    var query=search.trim().toLocaleLowerCase()
    var telephone=/^[+0-9().\s-]+$/.test(query) && /[0-9]/.test(query)
    // Same NANP equivalence as HistoryState.numberKey; partial numeric queries
    // remain useful for discovery, never for selecting a recipient implicitly.
    function numberKey(value) {
        var digits=value.replace(/[^0-9]/g,"")
        return digits.length===11 && digits.charAt(0)==="1" ? digits.slice(1) : digits
    }
    var digits=telephone?numberKey(query):""
    var result=[]
    contacts.forEach(function(c) {
        var name=c.name.trim().toLocaleLowerCase(),rank=-1
        if(!query)rank=0
        else if(!telephone) {
            if(name.indexOf(query)===0)rank=0
            else if(name.split(/[\s,.'’()\/_-]+/).some(function(word){return word.indexOf(query)===0}))rank=1
            else if(name.indexOf(query)>=0)rank=2
        }
        c.numbers.forEach(function(n) {
            var tier=rank,number=numberKey(n.number)
            if(telephone)tier=number===digits?0:number.indexOf(digits)===0?1:number.indexOf(digits)>=0?2:-1
            if(tier>=0)result.push({name:c.name,number:n.number,label:n.label,tier:tier})
        })
    })
    result.sort(function(a,b){return a.tier-b.tier || a.name.toLocaleLowerCase().localeCompare(b.name.toLocaleLowerCase()) || a.name.localeCompare(b.name) || a.number.localeCompare(b.number) || a.label.localeCompare(b.label)})
    return result.slice(0,100).map(function(c){return {name:c.name,number:c.number,label:c.label}})
}
