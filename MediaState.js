// MMS descriptors only. Notification icons never enter this adapter.
function byteLength(value) {
    try {return unescape(encodeURIComponent(value)).length} catch(e) {return Infinity}
}
function safeText(value,limit) {
    if(typeof value!=="string")return ""
    var result="",used=0
    for(var i=0;i<value.length;i++) {
        var part=value.charAt(i),code=value.charCodeAt(i)
        if(code>=0xD800&&code<=0xDBFF) {
            if(i+1>=value.length||value.charCodeAt(i+1)<0xDC00||value.charCodeAt(i+1)>0xDFFF)return ""
            part+=value.charAt(++i)
        } else if(code>=0xDC00&&code<=0xDFFF)return ""
        var size=byteLength(part)
        if(used+size>limit)break
        result+=part;used+=size
    }
    return result
}
function exactText(value,limit) {return typeof value==="string"&&value.length>0&&value.length<=limit&&byteLength(value)<=limit?value:""}
function exactIds(value,count,limit) {
    if(!Array.isArray(value)||value.length>count)return []
    if(value.some(function(id){return typeof id!=="string"||!id||id.length>limit||byteLength(id)>limit}))return []
    return value.filter(function(id,index){return value.indexOf(id)===index})
}
function normalizeMedia(data) {
    data=data&&typeof data==="object"&&!Array.isArray(data)?data:{}
    var player=exactText(data.player,256)
    return {player:player,playerList:exactIds(data.playerList||[],16,256),
        title:safeText(data.title,512),artist:safeText(data.artist,512),album:safeText(data.album,512),
        volume:Number.isInteger(data.volume)&&data.volume>=0&&data.volume<=100?data.volume:undefined,
        length:Number.isInteger(data.length)&&data.length>=0&&data.length<=Number.MAX_SAFE_INTEGER?data.length:undefined,
        position:Number.isInteger(data.position)&&data.position>=0&&data.position<=Number.MAX_SAFE_INTEGER?data.position:undefined,
        isPlaying:typeof data.isPlaying==="boolean"?data.isPlaying:undefined,
        canSeek:typeof data.canSeek==="boolean"?data.canSeek:undefined}
}
function normalizeSnapshot(devices) {
    if(!Array.isArray(devices))return []
    return devices.slice(0,64).filter(function(d){return d&&typeof d==="object"&&!Array.isArray(d)&&typeof d.id==="string"&&/^[A-Za-z0-9_]{1,256}$/.test(d.id)}).map(function(d) {
        var links=Array.isArray(d.links)?d.links.slice(0,16).map(function(x){return safeText(x,128)}).filter(Boolean):[]
        var can=exactIds(d.can,128,128)
        return {id:d.id,name:safeText(d.name,256)||"Phone",online:d.online===true,links:links,
            battery:Number.isInteger(d.battery)&&d.battery>=0&&d.battery<=100?d.battery:-1,
            charging:d.charging===true,can:can,media:normalizeMedia(d.media),notifications:[]}
    })
}
function key(m,a) {return JSON.stringify([m.device_id,m.thread_id,m.message_id,a.part_id,a.identifier])}
function usable(a) {return a && /^\d+$/.test(String(a.part_id)) && typeof a.identifier==="string" && a.identifier.length>0 && a.identifier!=="." && a.identifier!==".." && !/[\\/\x00-\x1f]/.test(a.identifier)}
function thumbnail(a) {
    var data=a&&a.thumbnail_base64
    if(typeof data!=="string"||data.length>524288||!data.length||data.length%4!==0||!/^[A-Za-z0-9+/]+={0,2}$/.test(data))return ""
    var type=data.indexOf("iVBORw0KGgo")===0?"png":data.indexOf("/9j/")===0?"jpeg":data.indexOf("R0lGOD")===0?"gif":data.indexOf("UklGR")===0?"webp":""
    return type?"data:image/"+type+";base64,"+data:""
}
function command(states,m,a,request,open) {
    if(!usable(a))return null
    var k=key(m,a),s=states[k]
    if(s&&s.pending)return null
    if(open&&(!s||s.status!=="downloaded"))return null
    states[k]={pending:request,status:open?"opening":"loading",identity:k,error:""}
    var keys=Object.keys(states)
    if(keys.length>300)delete states[keys[0]]
    return {op:open?"attachment_open":"attachment",request_id:request,device:m.device_id,thread:m.thread_id,message_id:m.message_id,part_id:a.part_id,identifier:a.identifier}
}
function receive(states,event) {
    if(event.event==="worker_stopped"||event.event==="device_offline") {
        Object.keys(states).forEach(function(k){if(event.event==="worker_stopped"||JSON.parse(k)[0]===event.device)delete states[k]});return
    }
    Object.keys(states).forEach(function(k) {
        var s=states[k]
        if(!s.pending||s.pending!==event.request_id)return
        if(event.event==="attachment_ready") {
            if(k!==JSON.stringify([event.device,event.thread,event.message_id,event.part_id,event.identifier])||event.kind!=="mms_download")return
            s.pending="";s.status="downloaded";s.error=""
        } else if(event.event==="attachment_opened") {s.pending="";s.status="downloaded"}
        else if(event.event==="error") {s.pending="";s.status="error";s.error=event.error||"Attachment unavailable"}
    })
}
function prune(states,history) {
    Object.keys(states).forEach(function(k) {
        var id=JSON.parse(k),t=history.threads[JSON.stringify([id[0],id[1]])],m=t&&t.messages[id[2]]
        if(!m||!m.attachments.some(function(a){return String(a.part_id)===id[3]&&a.identifier===id[4]}))delete states[k]
    })
}
