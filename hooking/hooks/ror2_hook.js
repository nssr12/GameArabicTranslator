console.log("[RoR2] Loading Risk of Rain 2 Arabic Translator...");

var translationCache = {};
var displayedTexts = new Set();
var activeTexts = new Map();
var isReady = false;

function isValidText(text) {
    if (!text || typeof text !== 'string') return false;
    if (text.length < 2 || text.length > 500) return false;
    if (/[\u0600-\u06FF]/.test(text)) return false;
    if (/^[\x00-\x1F\x7F-\x9F]+$/.test(text)) return false;
    if (/^[0-9a-fA-F]{8,}$/.test(text)) return false;
    if (text === 'null' || text === 'undefined') return false;
    
    var hasLetter = /[a-zA-Z]/.test(text);
    if (!hasLetter) return false;
    
    return true;
}

function writeTranslation(address, translatedText) {
    try {
        if (!address || address.isNull()) return false;
        
        try {
            address.writeUtf16String(translatedText);
            return true;
        } catch (e) {
            try {
                var newBuffer = Memory.allocUtf16String(translatedText);
                Memory.copy(address, newBuffer, Math.min(translatedText.length * 2, 800));
                return true;
            } catch (e2) {
                return false;
            }
        }
    } catch (error) {
        return false;
    }
}

function applyTranslation(originalText, translatedText) {
    var applied = false;
    for (var [address, info] of activeTexts) {
        if (info.text === originalText) {
            try {
                var ptr_addr = ptr(address);
                if (writeTranslation(ptr_addr, translatedText)) {
                    info.text = translatedText;
                    applied = true;
                }
            } catch (e) {}
        }
    }
    return applied;
}

function hookUnityText() {
    var modules = Process.enumerateModules();
    var gameModule = null;
    
    for (var i = 0; i < modules.length; i++) {
        if (modules[i].name.toLowerCase() === 'assembly-csharp.dll') {
            gameModule = modules[i];
            break;
        }
    }
    
    if (!gameModule) {
        for (var i = 0; i < modules.length; i++) {
            if (modules[i].name.toLowerCase().includes('ror2')) {
                gameModule = modules[i];
                break;
            }
        }
    }
    
    if (!gameModule) {
        send({ type: 'log', message: '[RoR2] Game module not found' });
        return;
    }
    
    send({ type: 'log', message: '[RoR2] Found module: ' + gameModule.name + ' at ' + gameModule.base });
    
    var tmProModule = null;
    for (var i = 0; i < modules.length; i++) {
        if (modules[i].name.toLowerCase().includes('textmeshpro') || modules[i].name.toLowerCase().includes('unity.textmeshpro')) {
            tmProModule = modules[i];
            break;
        }
    }
    
    if (tmProModule) {
        send({ type: 'log', message: '[RoR2] Found TextMeshPro: ' + tmProModule.name });
    }
    
    try {
        var exports = gameModule.enumerateExports();
        var textRelated = [];
        
        for (var i = 0; i < exports.length; i++) {
            var name = exports[i].name.toLowerCase();
            if ((name.includes('set_text') || name.includes('get_text') || 
                 name.includes('setstring') || name.includes('getstring') ||
                 name.includes('localize') || name.includes('language') ||
                 name.includes('translation')) && 
                exports[i].type === 'function') {
                textRelated.push(exports[i]);
            }
        }
        
        send({ type: 'log', message: '[RoR2] Found ' + textRelated.length + ' text-related exports' });
        
        for (var i = 0; i < Math.min(textRelated.length, 20); i++) {
            try {
                (function(exp) {
                    Interceptor.attach(exp.address, {
                        onEnter: function(args) {
                            for (var j = 0; j < 4; j++) {
                                try {
                                    if (args[j] && !args[j].isNull()) {
                                        var text = args[j].readUtf16String();
                                        if (text && isValidText(text)) {
                                            if (!displayedTexts.has(text)) {
                                                displayedTexts.add(text);
                                                send({ type: 'text_found', text: text, hook: exp.name });
                                            }
                                            
                                            activeTexts.set(args[j].toString(), { text: text, timestamp: Date.now() });
                                            
                                            if (translationCache[text]) {
                                                writeTranslation(args[j], translationCache[text]);
                                            }
                                            return;
                                        }
                                        
                                        text = args[j].readUtf8String();
                                        if (text && isValidText(text)) {
                                            if (!displayedTexts.has(text)) {
                                                displayedTexts.add(text);
                                                send({ type: 'text_found', text: text, hook: exp.name });
                                            }
                                            
                                            activeTexts.set(args[j].toString(), { text: text, timestamp: Date.now() });
                                            
                                            if (translationCache[text]) {
                                                var buffer = Memory.allocUtf8String(translationCache[text]);
                                                args[j] = buffer;
                                            }
                                            return;
                                        }
                                    }
                                } catch (e) {}
                            }
                        }
                    });
                })(textRelated[i]);
            } catch (e) {}
        }
    } catch (e) {
        send({ type: 'log', message: '[RoR2] Export hook error: ' + e });
    }
    
    try {
        var monoModule = Process.findModuleByName('mono-2.0-bdwgc.dll') || 
                         Process.findModuleByName('mono.dll') ||
                         Process.findModuleByName('mono-2.0.dll');
        
        if (monoModule) {
            send({ type: 'log', message: '[RoR2] Found Mono: ' + monoModule.name });
            
            try {
                var mono_thread_attach = Module.findExportByName(monoModule.name, 'mono_thread_attach');
                var mono_string_new = Module.findExportByName(monoModule.name, 'mono_string_new');
                var mono_string_to_utf8 = Module.findExportByName(monoModule.name, 'mono_string_to_utf8');
                
                if (mono_string_new) {
                    send({ type: 'log', message: '[RoR2] Found mono_string_new at ' + mono_string_new });
                }
            } catch (e) {}
        }
    } catch (e) {}
}

recv('translation', function(message) {
    if (message.original && message.translated) {
        translationCache[message.original] = message.translated;
        applyTranslation(message.original, message.translated);
        send({ type: 'log', message: '[RoR2] Translation applied: ' + message.original.substring(0, 30) + ' -> ' + message.translated.substring(0, 30) });
    }
});

recv('cache-loaded', function(message) {
    if (message.cache) {
        var count = 0;
        for (var key in message.cache) {
            translationCache[key] = message.cache[key];
            count++;
        }
        send({ type: 'log', message: '[RoR2] Loaded ' + count + ' cached translations' });
    }
});

recv('translations-batch', function(message) {
    if (message.translations) {
        var count = 0;
        for (var key in message.translations) {
            translationCache[key] = message.translations[key];
            count++;
        }
        send({ type: 'log', message: '[RoR2] Loaded batch: ' + count + ' translations' });
        
        for (var [address, info] of activeTexts) {
            if (translationCache[info.text]) {
                try {
                    writeTranslation(ptr(address), translationCache[info.text]);
                } catch (e) {}
            }
        }
    }
});

setInterval(function() {
    var now = Date.now();
    var old = [];
    for (var [address, info] of activeTexts) {
        if (now - info.timestamp > 300000) {
            old.push(address);
        }
    }
    old.forEach(function(addr) { activeTexts.delete(addr); });
}, 60000);

rpc.exports = {
    synccache: function(cacheData) {
        if (cacheData.translations) {
            for (var key in cacheData.translations) {
                translationCache[key] = cacheData.translations[key];
            }
        }
        return "OK";
    },
    getstats: function() {
        return {
            cache_size: Object.keys(translationCache).length,
            active_texts: activeTexts.size,
            displayed_texts: displayedTexts.size
        };
    }
};

try {
    hookUnityText();
    isReady = true;
    send({ type: 'ready', message: '[RoR2] Arabic Translator ready!' });
    console.log("[RoR2] Arabic Translator ready!");
} catch (error) {
    send({ type: 'error', message: '[RoR2] Init error: ' + error });
}
