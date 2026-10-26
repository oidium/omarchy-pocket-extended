.pragma library

// Service instances can be replaced while panel components survive. Keep a
// process-local monotone component in addition to time/randomness so request
// IDs cannot be reused by a replacement service in the same QML engine.
var sequence = 0

function next() {
    sequence += 1
    return Date.now().toString(36) + "-" + sequence.toString(36) + "-" +
        Math.random().toString(36).slice(2, 10)
}
