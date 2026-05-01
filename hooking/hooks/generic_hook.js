var baseAddr = null;
var translationCache = {};
var displayedTexts = new Set();
var activeTranslationRequests = new Map();
var requestIdCounter = 0;

function getBaseAddress() {
    var modules = Process.enumerateModules();
    return modules[0].base;
}

function isValidText(text) {
    if (!text || text.length < 3 || text.length > 500) return false;
    if (text.includes('.dll') || text.includes('.exe') || text.includes('.pak')) return false;
    if (text.includes('0x') || text.includes('NULL') || text.includes('DEBUG')) return false;
    if (/^[0-9a-fA-F\s]+$/.test(text)) return false;
    if (/[\u0600-\u06FF]/.test(text)) return false;
    
    var englishWords = text.match(/[a-zA-Z]+/g);
    if (englishWords && englishWords.length >= 2 && text.length >= 5) return true;
    if (/[.!?,:;"']/.test(text) && text.length >= 8 && /[a-zA-Z]/.test(text)) return true;
    if (text.length >= 3 && text.length <= 50 && /^[a-zA-Z\s]+$/.test(text)) return true;
    
    return false;
}

function translateText(text, args, argIndex, hookName) {
    if (!text || !isValidText(text)) return false;
    
    if (!displayedTexts.has(text)) {
        displayedTexts.add(text);
        send({ type: 'text_found', text: text, hook: hookName });
    }
    
    if (translationCache[text]) {
        try {
            var translated = translationCache[text];
            var buffer = Memory.allocUtf16String(translated);
            args[argIndex] = buffer;
            console.log('[Hook] ' + hookName + ' CACHED: "' + text.substring(0, 20) + '" -> "' + translated.substring(0, 20) + '"');
            return true;
        } catch (e) {}
    }
    
    var normalizedText = text.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
    if (normalizedText !== text && translationCache[normalizedText]) {
        try {
            var translated = translationCache[normalizedText];
            translationCache[text] = translated;
            var buffer = Memory.allocUtf16String(translated);
            args[argIndex] = buffer;
            return true;
        } catch (e) {}
    }
    
    var reqId = ++requestIdCounter;
    activeTranslationRequests.set(reqId, { text: text, args: args, argIndex: argIndex, hookName: hookName });
    
    send({
        type: 'translate-sync-with-confirmation',
        text: text,
        requestId: reqId
    });
    
    var waitCount = 0;
    while (waitCount < 60) {
        var request = activeTranslationRequests.get(reqId);
        if (request && request.resolved) {
            activeTranslationRequests.delete(reqId);
            return request.applied;
        }
        Thread.sleep(0.01);
        waitCount++;
    }
    
    activeTranslationRequests.delete(reqId);
    return false;
}

recv('translation-confirmation', function(message) {
    var reqId = message.requestId;
    var original = message.original;
    var translated = message.translated;
    
    if (original && translated && translated !== original) {
        translationCache[original] = translated;
    }
    
    var request = activeTranslationRequests.get(reqId);
    if (request) {
        request.resolved = true;
        if (translated && translated !== original) {
            try {
                var buffer = Memory.allocUtf16String(translated);
                request.args[request.argIndex] = buffer;
                request.applied = true;
            } catch (e) {
                request.applied = false;
            }
        } else {
            request.applied = false;
        }
    }
});

recv('translation', function(message) {
    if (message.original && message.translated) {
        translationCache[message.original] = message.translated;
    }
});

recv('cache-loaded', function(message) {
    if (message.cache) {
        for (var key in message.cache) {
            translationCache[key] = message.cache[key];
        }
        send({ type: 'log', message: 'Loaded ' + Object.keys(message.cache).length + ' cached translations' });
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
    processmodificationcommand: function(cmd) {
        return "OK";
    }
};

send({ type: 'log', message: '[GenericHook] Script loaded - waiting for game hooks to be configured' });
