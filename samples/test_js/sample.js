// Test JS file for audison scan --js
const crypto = require('crypto');

// BUG: createHash only uses data, not algorithm param
function hashData(data, algorithm = 'sha256') {
    const hash = crypto.createHash('sha256');
    hash.update(data);
    return hash.digest('hex');
}

// CORRECT: all params used
function hashWithSalt(data, salt) {
    const hash = crypto.createHash('sha256');
    hash.update(data);
    hash.update(salt);
    return hash.digest('hex');
}
