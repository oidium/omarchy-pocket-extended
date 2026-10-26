.pragma library

// Process-local shared suppression survives service-object recreation while the
// shell QML engine remains alive. PersistentProperties is the shell-reload backstop.
var removals = ({})

function restore(saved) {
    if(!saved||typeof saved!=="object"||Array.isArray(saved))return
    Object.keys(saved).forEach(function(key){if(!removals[key])removals[key]=saved[key]})
}
function remember(key,internalId) {
    removals[key]=internalId
    return Object.assign({},removals)
}
function forget(key) {
    delete removals[key]
    return Object.assign({},removals)
}
function isRemoved(key,internalId) { return removals[key]===internalId }
function all() { return Object.assign({},removals) }
