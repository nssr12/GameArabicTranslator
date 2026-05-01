console.log("[ManorLords] Loading Memory Scanner Arabic Translator...");

var translationCache = {};
var isReady = false;
var scanInterval = null;
var foundTexts = new Map();
var replacedCount = 0;

function isValidEnglishText(text) {
    if (!text || typeof text !== 'string') return false;
    if (text.length < 2 || text.length > 300) return false;
    if (/[\u0600-\u06FF]/.test(text)) return false;
    if (/^[\x00-\x1F\x7F-\x9F]+$/.test(text)) return false;
    if (/^[0-9a-fA-F\s\.\-_:\/\\]+$/.test(text)) return false;
    if (text.includes('.dll') || text.includes('.exe') || text.includes('.pak')) return false;
    if (text.includes('Default__') || text.includes('/Game/') || text.includes('/Engine/')) return false;
    if (text.includes('nullptr') || text.includes('undefined') || text.includes('FString')) return false;
    if (text.includes('UE4') || text.includes('UE5') || text.includes('Blueprint')) return false;
    
    var letterCount = (text.match(/[a-zA-Z]/g) || []).length;
    if (letterCount < 2) return false;
    if (letterCount / text.length < 0.3 && text.length > 5) return false;
    
    return true;
}

function scanUTF16Chunk(baseAddr, size) {
    var results = [];
    try {
        var chunk = baseAddr.readByteArray(size);
        var view = new Uint8Array(chunk);
        
        var text = '';
        var startAddr = null;
        
        for (var i = 0; i < view.length - 1; i += 2) {
            var lo = view[i];
            var hi = view[i + 1];
            
            if (hi === 0 && lo >= 0x20 && lo <= 0x7E) {
                if (!startAddr) startAddr = baseAddr.add(i);
                text += String.fromCharCode(lo);
            } else {
                if (text.length >= 3 && isValidEnglishText(text)) {
                    results.push({ text: text, addr: startAddr });
                }
                text = '';
                startAddr = null;
            }
        }
        
        if (text.length >= 3 && isValidEnglishText(text) && startAddr) {
            results.push({ text: text, addr: startAddr });
        }
    } catch(e) {}
    
    return results;
}

function hookUETextFunctions() {
    var modules = Process.enumerateModules();
    var gameModule = null;
    
    for (var i = 0; i < modules.length; i++) {
        if (modules[i].name.toLowerCase().includes('manorlords-win64-shipping')) {
            gameModule = modules[i];
            break;
        }
    }
    
    if (!gameModule) {
        for (var i = 0; i < modules.length; i++) {
            if (modules[i].name.toLowerCase().includes('shipping')) {
                gameModule = modules[i];
                break;
            }
        }
    }
    
    if (!gameModule) {
        send({ type: 'log', message: '[ManorLords] Game module not found!' });
        return false;
    }
    
    send({ type: 'log', message: '[ManorLords] Module: ' + gameModule.name + ' size=' + (gameModule.size/1024/1024).toFixed(0) + 'MB' });
    
    var heapRanges = Process.enumerateRanges('rw-');
    var totalScanned = 0;
    var foundCount = 0;
    
    send({ type: 'log', message: '[ManorLords] Scanning ' + heapRanges.length + ' memory regions...' });
    
    for (var r = 0; r < heapRanges.length; r++) {
        var range = heapRanges[r];
        if (range.size < 1024 || range.size > 500 * 1024 * 1024) continue;
        
        var chunkSize = 64 * 1024;
        
        for (var offset = 0; offset < range.size; offset += chunkSize) {
            try {
                var currentSize = Math.min(chunkSize, range.size - offset);
                var baseAddr = range.base.add(offset);
                
                var results = scanUTF16Chunk(baseAddr, currentSize);
                
                for (var i = 0; i < results.length; i++) {
                    var r_item = results[i];
                    if (!foundTexts.has(r_item.text)) {
                        foundTexts.set(r_item.text, r_item.addr);
                        foundCount++;
                    }
                }
                
                totalScanned += currentSize;
            } catch(e) {}
        }
    }
    
    send({ type: 'log', message: '[ManorLords] Scanned ' + (totalScanned/1024/1024).toFixed(0) + 'MB, found ' + foundCount + ' texts' });
    
    var cacheHits = 0;
    for (var [text, addr] of foundTexts) {
        if (translationCache[text]) {
            cacheHits++;
        }
    }
    send({ type: 'log', message: '[ManorLords] Cache matches: ' + cacheHits + ' / ' + foundTexts.size });
    
    return true;
}

function scanAndReplace() {
    var count = 0;
    for (var [text, addr] of foundTexts) {
        if (translationCache[text]) {
            try {
                var arText = translationCache[text];
                addr.writeUtf16String(arText);
                count++;
            } catch(e) {
                try {
                    var buffer = Memory.allocUtf16String(arText);
                    Memory.copy(addr, buffer, Math.min(arText.length * 2, text.length * 2 + 2));
                    count++;
                } catch(e2) {}
            }
        }
    }
    if (count > 0) {
        send({ type: 'log', message: '[ManorLords] Replaced ' + count + ' texts' });
    }
}

recv('translation', function(message) {
    if (message.original && message.translated) {
        translationCache[message.original] = message.translated;
        scanAndReplace();
    }
});

recv('cache-loaded', function(message) {
    if (message.cache) {
        var count = 0;
        for (var key in message.cache) {
            translationCache[key] = message.cache[key];
            count++;
        }
        send({ type: 'log', message: '[ManorLords] Cache: ' + count + ' translations' });
        scanAndReplace();
    }
});

recv('translations-batch', function(message) {
    if (message.translations) {
        for (var key in message.translations) {
            translationCache[key] = message.translations[key];
        }
        scanAndReplace();
    }
});

rpc.exports = {
    synccache: function(cacheData) {
        if (cacheData.translations) {
            for (var key in cacheData.translations) {
                translationCache[key] = cacheData.translations[key];
            }
        }
        return "OK";
    },
    rescan: function() {
        hookUETextFunctions();
        scanAndReplace();
        return "OK";
    },
    getstats: function() {
        return {
            cache_size: Object.keys(translationCache).length,
            found_texts: foundTexts.size,
            replaced: replacedCount
        };
    }
};

try {
    hookUETextFunctions();
    isReady = true;
    
    scanAndReplace();
    
    send({ type: 'ready', message: '[ManorLords] Ready! Found ' + foundTexts.size + ' texts' });
} catch (error) {
    send({ type: 'error', message: '[ManorLords] Error: ' + error });
}
