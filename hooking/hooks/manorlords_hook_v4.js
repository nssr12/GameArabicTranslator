// Manor Lords Arabic Translator — v4 (full Unicode + heuristic-based filtering)
//
// الفروقات الجوهرية عن v3:
//   1) **UTF-16 كامل** بدل ASCII فقط — يمسك Latin extended, German umlauts, الخ
//      v3 كان يكسر النص الألماني عند ü/ö → قصاصات.
//   2) **Score-based filtering** بدل blacklist تكتيكي
//      نُعطي كل نص "naturalness score":
//        + spaces، حروف عادية، أطوال معقولة، capitalization طبيعي
//        - _, ::, ., نمط camelCase, نمط asset path, _v1 suffix, الخ
//   3) **فلاتر MetaSound** صريحة (External_, Variable_, _v1, _1.0)
//   4) **فلاتر asset paths** (/Game/, Materials/, Textures/, ends with .png/.uasset)
//   5) **فلاتر audio device names** (parens with hardware model)

console.log("[ManorLords-v4] Loading…");

const STATE = {
    cache: {},
    texts: new Map(),
    stats: {
        scans: 0,
        ranges_scanned: 0,
        ranges_skipped_file_backed: 0,
        candidates_total: 0,
        filtered_short: 0,
        filtered_arabic: 0,
        filtered_score: 0,
        filtered_metasound: 0,
        filtered_asset_path: 0,
        filtered_audio_device: 0,
        filtered_path: 0,
        filtered_cvar: 0,
        filtered_ue_internal: 0,
        filtered_desc_prefix: 0,
        texts_found: 0,
        cache_hits: 0,
        replaced: 0,
        write_failures: 0,
    },
    scanIntervalId: null,
    ready: false,
};

const CONFIG = {
    scan_interval_ms: 10000,
    min_text_length: 4,
    max_text_length: 800,
    chunk_size: 64 * 1024,
    min_region_size: 4096,
    max_region_size: 200 * 1024 * 1024,
    send_new_texts_to_python: true,
    skip_file_backed: true,
    min_naturalness_score: 3,  // أي نص بسكور أقل → ضوضاء
};

// ============== فلاتر سريعة ==============
function isMetaSoundString(text) {
    // أنماط أسماء عقد MetaSound — كثيرة جداً في heap للعبة UE5
    if (/_v\d+$/.test(text)) return true;             // ..._v1, ..._v2
    if (/_\d+\.\d+$/.test(text)) return true;         // ..._1.0, ..._1.1
    if (text.startsWith("External_")) return true;
    if (text.startsWith("Variable_")) return true;
    if (text.startsWith("Variable (")) return true;
    if (text.startsWith("Output_Output.")) return true;
    if (text.startsWith("Input_Input.")) return true;
    if (text.startsWith("Literal_Literal.")) return true;
    if (text.startsWith("Template_UE.")) return true;
    if (text.startsWith("Variable_InitVariable.")) return true;
    if (text.startsWith("Crossfade.")) return true;
    if (text.startsWith("TriggerRoute.")) return true;
    if (text.startsWith("TriggerAccumulator.")) return true;
    if (text.startsWith("TriggerAny.")) return true;
    if (text.startsWith("TriggerCompare.")) return true;
    if (text.startsWith("BandSplitter.")) return true;
    if (text.startsWith("AudioMixer.")) return true;
    if (text.startsWith("VariableAccessor.")) return true;
    if (text.startsWith("VariableMutator.")) return true;
    if (text.startsWith("VariableDeferredAccessor.")) return true;
    if (text.startsWith("InitVariable.")) return true;
    if (text.startsWith("Array.")) return true;
    if (text.startsWith("Convert.")) return true;
    if (text.startsWith("MapRange.")) return true;
    if (text.startsWith("AbsoluteValue.")) return true;
    if (text.startsWith("Print Log.")) return true;
    if (text.startsWith("SampleAndHold.")) return true;
    if (text.startsWith("ADSR Envelope.")) return true;
    if (text.startsWith("AD Envelope.")) return true;
    if (text.startsWith("Receive.")) return true;
    if (text.startsWith("Send.")) return true;
    if (text.startsWith("Output.")) return true;
    if (text.startsWith("Input.")) return true;
    if (text.startsWith("Literal.")) return true;
    if (text.includes("Enum:")) return true;     // Enum:WaveTableEnvelopeMode
    if (text.includes(":Array")) return true;    // float:Array, Bool:Array
    return false;
}

function isAssetPath(text) {
    // مسارات داخل اللعبة
    if (text.includes("/Game/")) return true;
    if (text.includes("/Engine/")) return true;
    if (text.includes("/Script/")) return true;
    if (text.includes("/Content/")) return true;
    if (text.includes("/Plugins/")) return true;
    if (text.includes("/Restricted/")) return true;
    if (text.includes("Materials/")) return true;
    if (text.includes("Textures/")) return true;
    if (text.includes("Sounds/")) return true;
    if (text.includes("Slate/")) return true;
    if (text.includes("Submixes/")) return true;
    if (text.includes("Database/")) return true;
    if (text.includes("Portraits/")) return true;
    // امتدادات ملفات في النهاية
    if (/\.(png|jpg|jpeg|tga|exr|wav|ogg|mp3|uexp|uasset|umap|ubulk|fbx|usf|ush|json|ini|xml)\b/i.test(text)) return true;
    // نمط أسماء UE asset: M_X, T_X, SK_X, SM_X, BP_X, A_X, NS_X
    if (/^[A-Z]+_[A-Z][a-zA-Z]/.test(text) && text.length < 60 && !text.includes(" ")) return true;
    return false;
}

function isAudioDeviceName(text) {
    // أسماء أجهزة صوت Windows: "Speakers (Realtek(R) Audio)", "NVIDIA Output (...)"
    if (/\([^)]{5,}\)/.test(text) && text.length < 80) {
        const lower = text.toLowerCase();
        if (lower.includes("audio") || lower.includes("realtek") || lower.includes("nvidia") ||
            lower.includes("speakers") || lower.includes("microphone") || lower.includes("headphones") ||
            lower.includes("hdmi") || lower.includes("hyperx") || lower.includes("voicemeeter")) {
            return true;
        }
    }
    return false;
}

function isCVarShort(text) {
    // CVar أو asset name قصير غير محتوي على مسافات
    if (text.includes(" ")) return false;
    // مع نقاط في الوسط
    if (/^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(text)) return true;
    return false;
}

// ============== Score-based naturalness ==============
function computeNaturalness(text) {
    let score = 0;

    // إيجابيات
    const spaces = (text.match(/ /g) || []).length;
    score += spaces * 2;                                          // كل مسافة +2

    // مسافة بين كلمتين بحرف صغير + كبير = جملة طبيعية
    if (/[a-z] [A-Z]/.test(text)) score += 3;
    if (/[a-z] [a-z]/.test(text)) score += 2;

    // علامات ترقيم طبيعية
    if (/[.,!?](\s|$)/.test(text)) score += 2;

    // كلمات شائعة (heuristic قوي للنص الإنجليزي الطبيعي)
    const commonWords = /\b(the|and|of|to|in|is|a|you|your|for|with|on|are|that|this|by|or|from|be|at|as|an|will|can|all|when|what|how|do|not|but|have|has|been|new|game|menu|settings|options|continue|quit|exit)\b/gi;
    const wordMatches = (text.match(commonWords) || []).length;
    score += wordMatches * 3;

    // حروف عربية / الماني / فرنسي
    if (/[À-ſ]/.test(text)) score += 2;                 // Latin extended
    if (/[؀-ۿ]/.test(text)) score -= 100;               // عربي = مرفوض (مترجم)

    // طول معقول
    if (text.length >= 4 && text.length <= 80) score += 1;
    if (text.length >= 8 && text.length <= 50) score += 2;

    // capitalization طبيعي (Title Case أو Sentence case)
    if (/^[A-Z][a-z]/.test(text)) score += 1;

    // ===== سلبيات =====
    // أنماط برمجية
    if (text.includes("_")) score -= 3;                           // underscores نادرة في النص الطبيعي
    if (text.includes("::")) score -= 10;
    if (/[<>{}\[\]|`~]/.test(text)) score -= 5;
    if (text.includes("\\")) score -= 5;
    if (text.includes("$")) score -= 3;

    // camelCase (حرف كبير بعد صغير بدون مسافة)
    const camelMatches = (text.match(/[a-z][A-Z]/g) || []).length;
    if (camelMatches > 2) score -= camelMatches;                  // كل camel = -1 (لو > 2)

    // نمط نقاط في الوسط (CVar أو asset path)
    if (/[a-z]\.[A-Z]/.test(text)) score -= 5;
    if ((text.match(/\./g) || []).length > 3) score -= 5;

    // أرقام كثيرة في النص
    const digits = (text.match(/\d/g) || []).length;
    if (digits > text.length * 0.3) score -= 5;

    // كل حروف كبيرة (UPPER_CASE)
    if (/^[A-Z_0-9]+$/.test(text)) score -= 5;

    return score;
}

function isValidGameText(text) {
    if (!text || typeof text !== 'string') return false;

    if (text.length < CONFIG.min_text_length) { STATE.stats.filtered_short++; return false; }
    if (text.length > CONFIG.max_text_length) { STATE.stats.filtered_short++; return false; }

    // عربي بالفعل (مترجم سابقاً)
    if (/[؀-ۿ]/.test(text)) { STATE.stats.filtered_arabic++; return false; }

    // فلاتر سريعة (قبل score)
    if (isMetaSoundString(text)) { STATE.stats.filtered_metasound++; return false; }
    if (isAssetPath(text)) { STATE.stats.filtered_asset_path++; return false; }
    if (isAudioDeviceName(text)) { STATE.stats.filtered_audio_device++; return false; }
    if (isCVarShort(text)) { STATE.stats.filtered_cvar++; return false; }

    // فلاتر مسارات ouAS Windows
    if (text.includes("\\") || /^[A-Z]:[\/\\]/.test(text)) {
        STATE.stats.filtered_path++; return false;
    }

    // CVar descriptions طويلة
    if (text.length > 30) {
        if (/^(Enable|Disable|Set|Sets|Whether|Controls|If true|If false|If enabled|If non-zero|Force|Forces|Toggle|Allows|Used to|Number of|Maximum|Maximum |Minimum |Sets the |Returns |Specifies |Configure |Defines |Default |Determines |Skip|Skips )/.test(text)) {
            STATE.stats.filtered_desc_prefix++; return false;
        }
    }

    // UE internal types
    if (text.includes("Default__") || text.includes("FString") || text.includes("UObject") ||
        text.includes("FName") || text.includes("BP_") || text.includes("TArray<") ||
        text.includes("TMap<") || text.includes("TSet<")) {
        STATE.stats.filtered_ue_internal++; return false;
    }

    // score-based
    const score = computeNaturalness(text);
    if (score < CONFIG.min_naturalness_score) {
        STATE.stats.filtered_score++;
        return false;
    }

    return true;
}

// ============== استخراج UTF-16 (يدعم Unicode كامل) ==============
function scanUTF16Chunk(baseAddr, size) {
    const results = [];
    try {
        const chunk = baseAddr.readByteArray(size);
        const view = new Uint8Array(chunk);
        let text = '';
        let startAddr = null;

        for (let i = 0; i < view.length - 1; i += 2) {
            const lo = view[i];
            const hi = view[i + 1];
            const code = lo | (hi << 8);

            // قبول مدى Unicode الواسع:
            // - ASCII printable (0x20-0x7E)
            // - Latin-1 Supplement (0xA0-0xFF) — German umlauts, ñ, ç, etc.
            // - Latin Extended A/B (0x100-0x24F)
            // - استثنينا أحرف التحكّم (< 0x20) و surrogates (0xD800-0xDFFF)
            const isAccepted = (
                (code >= 0x20 && code <= 0x7E) ||
                (code >= 0xA0 && code <= 0x24F) ||
                (code >= 0x0590 && code <= 0x06FF)  // عربي/عبري (للكشف عن مترجم سابقاً)
            );

            if (isAccepted) {
                if (!startAddr) startAddr = baseAddr.add(i);
                text += String.fromCharCode(code);
            } else {
                if (text.length >= CONFIG.min_text_length) {
                    STATE.stats.candidates_total++;
                    if (isValidGameText(text)) {
                        results.push({ text, addr: startAddr });
                    }
                }
                text = '';
                startAddr = null;
            }
        }
        if (text.length >= CONFIG.min_text_length && startAddr) {
            STATE.stats.candidates_total++;
            if (isValidGameText(text)) {
                results.push({ text, addr: startAddr });
            }
        }
    } catch (e) { /* memory region not readable */ }
    return results;
}

// ============== Scan كامل ==============
function fullScan() {
    STATE.stats.scans++;
    const t0 = Date.now();
    let newTextsFound = 0;

    const ranges = Process.enumerateRanges('rw-');

    for (const range of ranges) {
        if (CONFIG.skip_file_backed && range.file) {
            STATE.stats.ranges_skipped_file_backed++;
            continue;
        }

        if (range.size < CONFIG.min_region_size ||
            range.size > CONFIG.max_region_size) continue;

        STATE.stats.ranges_scanned++;

        for (let offset = 0; offset < range.size; offset += CONFIG.chunk_size) {
            try {
                const sz = Math.min(CONFIG.chunk_size, range.size - offset);
                const addr = range.base.add(offset);
                const results = scanUTF16Chunk(addr, sz);

                for (const r of results) {
                    if (!STATE.texts.has(r.text)) {
                        STATE.texts.set(r.text, {
                            addr: r.addr,
                            last_seen: Date.now(),
                            replaced: false,
                        });
                        STATE.stats.texts_found++;
                        newTextsFound++;

                        if (CONFIG.send_new_texts_to_python) {
                            send({
                                type: 'text_found',
                                text: r.text,
                                address: r.addr.toString(),
                            });
                        }
                    } else {
                        const item = STATE.texts.get(r.text);
                        item.last_seen = Date.now();
                        item.addr = r.addr;
                    }
                }
            } catch (e) { /* skip */ }
        }
    }

    const elapsed = Date.now() - t0;
    send({
        type: 'scan_complete',
        message: `[v4] scan #${STATE.stats.scans} في ${elapsed}ms — ${newTextsFound} نص جديد (إجمالي ${STATE.texts.size})`,
        new_texts: newTextsFound,
        total_texts: STATE.texts.size,
        elapsed_ms: elapsed,
    });

    applyTranslations();
}

function applyTranslations() {
    let count = 0;
    let failures = 0;

    for (const [text, item] of STATE.texts) {
        const ar = STATE.cache[text];
        if (!ar) continue;
        if (item.replaced) continue;

        try {
            const maxBytes = (text.length + 1) * 2;
            const arBytes = (ar.length + 1) * 2;
            if (arBytes <= maxBytes) {
                item.addr.writeUtf16String(ar);
            } else {
                const safe = ar.substring(0, text.length);
                item.addr.writeUtf16String(safe);
            }
            item.replaced = true;
            count++;
        } catch (e) {
            failures++;
        }
    }

    if (count > 0 || failures > 0) {
        STATE.stats.replaced += count;
        STATE.stats.write_failures += failures;
        send({
            type: 'replaced',
            message: `[v4] استبدل ${count} نص (${failures} فشل)`,
            count, failures,
        });
    }
}

recv('translation', (msg) => {
    if (msg.original && msg.translated) {
        STATE.cache[msg.original] = msg.translated;
        STATE.stats.cache_hits++;
        applyTranslations();
    }
});

recv('translations_batch', (msg) => {
    if (msg.translations) {
        let added = 0;
        for (const key of Object.keys(msg.translations)) {
            if (!STATE.cache[key]) {
                STATE.cache[key] = msg.translations[key];
                added++;
            }
        }
        send({ type: 'log', message: `[v4] استلم ${added} ترجمة (إجمالي cache: ${Object.keys(STATE.cache).length})` });
        applyTranslations();
    }
});

recv('rescan_now', () => { fullScan(); });

recv('shutdown', () => {
    if (STATE.scanIntervalId) {
        clearInterval(STATE.scanIntervalId);
        STATE.scanIntervalId = null;
    }
    send({ type: 'log', message: '[v4] متوقّف' });
});

rpc.exports = {
    getstats: () => ({
        ...STATE.stats,
        cache_size: Object.keys(STATE.cache).length,
        tracked_texts: STATE.texts.size,
    }),
    rescannow: () => { fullScan(); return 'OK'; },
    pingbatch: (data) => {
        if (data && data.translations) {
            for (const key of Object.keys(data.translations)) {
                STATE.cache[key] = data.translations[key];
            }
            applyTranslations();
        }
        return Object.keys(STATE.cache).length;
    },
    listall: () => Array.from(STATE.texts.keys()),
};

try {
    send({
        type: 'log',
        message: `[v4] Full Unicode + score-based filtering. Threshold: ${CONFIG.min_naturalness_score}`,
    });

    fullScan();

    STATE.scanIntervalId = setInterval(() => {
        try { fullScan(); }
        catch (e) { send({ type: 'error', message: '[v4] scan خطأ: ' + e }); }
    }, CONFIG.scan_interval_ms);

    STATE.ready = true;
    send({
        type: 'ready',
        message: `[v4] جاهز! scan أوّلي وجد ${STATE.texts.size} نص.`,
    });
} catch (error) {
    send({ type: 'error', message: '[v4] init خطأ: ' + error });
}
