// Manor Lords Arabic Translator — v5 (aggressive CVar description killer)
//
// مشكلة v4: شروحات CVars نص إنجليزي طبيعي مع spaces وكلمات شائعة فمرّ من naturalness score.
// مثل: "World space distance along a cone trace to switch to using the global distance field..."
//
// إضافات v5:
//   1) **مرجع CVar داخل النص** → فوراً skip (نمط r.X.Y أو p.X.Y)
//   2) **مصطلحات تقنية لا تظهر في UI لعبة** (CVar, PSO, GBuffer, BVH, RHI, shader, cone, clipmap, LRU, RDG)
//   3) **بادئات option lists**: " 0", "0:", "1:", "(default)", "[default]"
//   4) **+30 بادئة وصف** (When, Note, Render, Force, Larger, Higher, Lower, Bias, Causes, Uses, etc.)
//   5) **طول > 80 + يحوي ":" + يحوي رقم** = على الأرجح وصف خياري
//   6) Score threshold أعلى (5 بدل 3)

console.log("[ManorLords-v5] Loading…");

const STATE = {
    cache: {},
    texts: new Map(),
    stats: {
        scans: 0,
        ranges_skipped_file_backed: 0,
        candidates_total: 0,
        filtered_short: 0,
        filtered_arabic: 0,
        filtered_metasound: 0,
        filtered_asset_path: 0,
        filtered_audio_device: 0,
        filtered_cvar_ref: 0,        // **جديد**: يحوي مرجع r.X.Y
        filtered_tech_term: 0,       // **جديد**: مصطلح تقني
        filtered_option_list: 0,     // **جديد**: 0:, 1:, etc.
        filtered_desc_prefix: 0,
        filtered_path: 0,
        filtered_ue_internal: 0,
        filtered_score: 0,
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
    min_naturalness_score: 5,
};

// ============== فلاتر MetaSound (من v4) ==============
function isMetaSoundString(text) {
    if (/_v\d+$/.test(text)) return true;
    if (/_\d+\.\d+$/.test(text)) return true;
    if (text.startsWith("External_") || text.startsWith("Variable_") ||
        text.startsWith("Variable (") || text.startsWith("Output_Output.") ||
        text.startsWith("Input_Input.") || text.startsWith("Literal_Literal.") ||
        text.startsWith("Template_UE.") || text.startsWith("Crossfade.") ||
        text.startsWith("TriggerRoute.") || text.startsWith("TriggerAccumulator.") ||
        text.startsWith("TriggerAny.") || text.startsWith("TriggerCompare.") ||
        text.startsWith("BandSplitter.") || text.startsWith("AudioMixer.") ||
        text.startsWith("VariableAccessor.") || text.startsWith("VariableMutator.") ||
        text.startsWith("VariableDeferredAccessor.") || text.startsWith("InitVariable.") ||
        text.startsWith("Array.") || text.startsWith("Convert.") ||
        text.startsWith("MapRange.") || text.startsWith("AbsoluteValue.") ||
        text.startsWith("Print Log.") || text.startsWith("SampleAndHold.") ||
        text.startsWith("ADSR Envelope.") || text.startsWith("AD Envelope.") ||
        text.startsWith("Receive.") || text.startsWith("Send.") ||
        text.startsWith("Output.") || text.startsWith("Input.") ||
        text.startsWith("Literal.")) return true;
    if (text.includes("Enum:") || text.includes(":Array")) return true;
    return false;
}

function isAssetPath(text) {
    if (/\/(Game|Engine|Script|Content|Plugins|Restricted)\//.test(text)) return true;
    if (/(Materials|Textures|Sounds|Slate|Submixes|Database|Portraits)\//.test(text)) return true;
    if (/\.(png|jpg|jpeg|tga|exr|wav|ogg|mp3|uexp|uasset|umap|ubulk|fbx|usf|ush|json|ini|xml)\b/i.test(text)) return true;
    if (/^[A-Z]+_[A-Z][a-zA-Z]/.test(text) && text.length < 60 && !text.includes(" ")) return true;
    return false;
}

function isAudioDeviceName(text) {
    if (/\([^)]{5,}\)/.test(text) && text.length < 80) {
        const lower = text.toLowerCase();
        if (/(audio|realtek|nvidia|speakers|microphone|headphones|hdmi|hyperx|voicemeeter|dualsense|bluetooth)/.test(lower)) {
            return true;
        }
    }
    return false;
}

// ============== ⭐ فلاتر CVar descriptions العدوانية (جديدة في v5) ==============

// يحوي مرجع CVar داخل النص → 99% وصف CVar
function containsCVarReference(text) {
    // مثل r.CacheUpdateEveryFrame, p.Chaos.SomeFlag, fx.Niagara.X
    // النمط: حرف صغير أو 2+ حرف + . + حرف كبير + ...
    if (/\b[a-z][a-z0-9]*\.[A-Z][a-zA-Z0-9]+(\.[A-Z][a-zA-Z0-9]+)*\b/.test(text)) return true;
    return false;
}

// مصطلحات تقنية لا تظهر في UI لعبة عادية
const TECH_TERMS = [
    "CVar", "cvar", "PSO", "PSOs", "GBuffer", "BVH", "RHI", "DXR",
    "RDG", "LRU", "MSAA", "VSM", "DFAO", "SSAO", "TSR", "TAA",
    "VRAM", "AABB", "RGP", "GPU", "shader", "Shader", "Shaders",
    "clipmap", "Clipmap", "raytrac", "RayTrac", "raster", "Raster",
    "scalability", "Scalability", "atlas", "Atlas", "voxel", "Voxel",
    "framebuffer", "Framebuffer", "rendertarget", "RenderTarget",
    "render thread", "Render Thread", "command buffer", "Command Buffer",
    "compute shader", "Compute Shader", "vertex shader", "Vertex Shader",
    "pixel shader", "Pixel Shader", "Substrate", "subsurface",
    "octree", "Octree", "frustum", "Frustum", "occlusion", "Occlusion",
    "Nanite", "NaNite", "Lumen", "lumen", "MetaSound", "Metasound",
    "PhysX", "Chaos", "kinematic", "Kinematic", "demosaic",
    "tessellation", "Tessellation", "anisotrop", "Anisotrop",
    "thread group", "Thread Group", "memory pool", "Memory Pool",
    "buffer pool", "Buffer Pool", "instance buffer", "Instance Buffer",
    "DLSS", "FSR", "XeSS", "Reflex", "Streamline",
    "actor channel", "Actor Channel", "subsystem", "Subsystem",
    "asset registry", "Asset Registry", "blueprint", "Blueprint",
    "FName", "FString", "FText", "UObject", "AActor",
];

function containsTechTerm(text) {
    for (const term of TECH_TERMS) {
        if (text.includes(term)) return true;
    }
    return false;
}

// قوائم خيارات (CVar option list)
function isOptionList(text) {
    // " 0:", " 1:", "0:", "1:", "0 -", "1 -", "0 (", "(default)"
    if (/^\s*\d+\s*[:\-\(]/.test(text)) return true;
    if (/^\s*[<>]\s*=?\s*\d+/.test(text)) return true;     // >0, <=0
    if (text.includes("(default)")) return true;
    if (text.includes("[default]")) return true;
    if (/\(default\s*=\s*/.test(text)) return true;        // (default = 1)
    if (/^[\s]*-?\d+\s*:\s*/.test(text)) return true;      // -1:, -2:
    return false;
}

// بادئات وصف ملحقة بأنواع جديدة كثيرة
const DESC_PREFIXES_V5 = [
    "When ", "If ", "Note", "Render ", "Force ", "Forces ", "Larger ", "Higher ",
    "Lower ", "Bias ", "Causes ", "Uses ", "Use ", "This ", "These ", "Those ",
    "Will ", "Would ", "May ", "Must ", "Should ", "Probably ", "Typical ",
    "Default ", "Defaults ", "Override ", "Overrides ", "Specifies ",
    "Sets ", "Set ", "Enable ", "Enables ", "Disable ", "Disables ",
    "Allow ", "Allows ", "Toggle ", "Toggles ", "Whether ", "Controls ",
    "Determines ", "Define ", "Defines ", "Skip ", "Skips ",
    "World space ", "Screen space ", "View space ", "Object space ",
    "Number of ", "Maximum ", "Minimum ", "Min ", "Max ",
    "Texture ", "Mesh ", "Material ", "Geometry ", "Geometric",
    "Performs ", "Perform ", "Includes ", "Include ", "Exclude ", "Excludes ",
    "Run ", "Runs ", "Process ", "Processes ", "Cache ", "Caches ",
    "Apply ", "Applies ", "Add ", "Adds ", "Remove ", "Removes ",
    "Get ", "Gets ", "Find ", "Finds ", "Returns ", "Return ",
    "Create ", "Creates ", "Destroy ", "Destroys ", "Update ", "Updates ",
    "Read ", "Reads ", "Write ", "Writes ",
    "Output ", "Outputs ", "Input ", "Inputs ",
    "Configure ", "Configures ", "Convert ", "Converts ",
    "Validate ", "Validates ", "Verify ", "Verifies ",
    "Wait ", "Waits ", "Block ", "Blocks ",
    "Time ", "Frame ", "Multiplier ", "Threshold ", "Scale ", "Scales ",
    "Initial ", "Final ", "Current ", "Previous ", "Next ",
    "Selects ", "Select ", "Choose ", "Chooses ",
    "Sequencer ", "Console ", "Editor ", "Engine ", "Platform ",
    "Adjust ", "Adjusts ", "Adjusting ", "Setting ", "Settings ",
    "Avoid ", "Avoids ", "Prevent ", "Prevents ",
    "Computes ", "Compute ", "Calculate ", "Calculates ",
    "Provides ", "Provide ", "Handle ", "Handles ", "Handling ",
    "0 ", "1 ", "2 ", "3 ", "4 ", "5 ", "<", ">", "=", "[",
];

function isDescriptionPrefix(text) {
    if (text.length < 25) return false;
    for (const p of DESC_PREFIXES_V5) {
        if (text.startsWith(p)) return true;
    }
    return false;
}

// طويل + يحوي ":" + يحوي رقم = option list ممتدّ
function isLongTechExplain(text) {
    if (text.length < 80) return false;
    const hasColon = text.includes(":");
    const hasDigit = /\d/.test(text);
    const hasParens = text.includes("(") && text.includes(")");
    if (hasColon && hasDigit) return true;
    if (hasParens && hasDigit && text.length > 120) return true;
    return false;
}

// ============== Score-based naturalness ==============
function computeNaturalness(text) {
    let score = 0;

    const spaces = (text.match(/ /g) || []).length;
    score += spaces * 2;

    if (/[a-z] [A-Z]/.test(text)) score += 3;
    if (/[a-z] [a-z]/.test(text)) score += 2;

    if (/[.,!?](\s|$)/.test(text)) score += 2;

    const commonWords = /\b(the|and|of|to|in|is|a|you|your|for|with|on|are|that|this|by|or|from|be|at|as|an|will|can|all|when|what|how|do|not|but|have|has|been|new|game|menu|settings|options|continue|quit|exit)\b/gi;
    const wordMatches = (text.match(commonWords) || []).length;
    score += wordMatches * 2;

    if (/[À-ſ]/.test(text)) score += 2;
    if (/[؀-ۿ]/.test(text)) score -= 100;

    if (text.length >= 4 && text.length <= 80) score += 1;
    if (text.length >= 8 && text.length <= 50) score += 2;

    if (/^[A-Z][a-z]/.test(text)) score += 1;

    // سلبيات
    if (text.includes("_")) score -= 3;
    if (text.includes("::")) score -= 10;
    if (/[<>{}\[\]|`~]/.test(text)) score -= 5;
    if (text.includes("\\")) score -= 5;
    if (text.includes("$")) score -= 3;

    const camelMatches = (text.match(/[a-z][A-Z]/g) || []).length;
    if (camelMatches > 2) score -= camelMatches;

    if (/[a-z]\.[A-Z]/.test(text)) score -= 5;
    if ((text.match(/\./g) || []).length > 3) score -= 5;

    const digits = (text.match(/\d/g) || []).length;
    if (digits > text.length * 0.3) score -= 5;

    if (/^[A-Z_0-9]+$/.test(text)) score -= 5;

    return score;
}

function isValidGameText(text) {
    if (!text || typeof text !== 'string') return false;

    if (text.length < CONFIG.min_text_length) { STATE.stats.filtered_short++; return false; }
    if (text.length > CONFIG.max_text_length) { STATE.stats.filtered_short++; return false; }

    if (/[؀-ۿ]/.test(text)) { STATE.stats.filtered_arabic++; return false; }

    // ⭐ فلاتر v5 الجديدة (قبل أي شيء)
    if (containsCVarReference(text)) { STATE.stats.filtered_cvar_ref++; return false; }
    if (containsTechTerm(text)) { STATE.stats.filtered_tech_term++; return false; }
    if (isOptionList(text)) { STATE.stats.filtered_option_list++; return false; }
    if (isLongTechExplain(text)) { STATE.stats.filtered_desc_prefix++; return false; }

    // فلاتر من v4
    if (isMetaSoundString(text)) { STATE.stats.filtered_metasound++; return false; }
    if (isAssetPath(text)) { STATE.stats.filtered_asset_path++; return false; }
    if (isAudioDeviceName(text)) { STATE.stats.filtered_audio_device++; return false; }

    if (text.includes("\\") || /^[A-Z]:[\/\\]/.test(text)) {
        STATE.stats.filtered_path++; return false;
    }

    if (isDescriptionPrefix(text)) {
        STATE.stats.filtered_desc_prefix++; return false;
    }

    if (text.includes("Default__") || text.includes("FString") || text.includes("UObject") ||
        text.includes("FName") || text.includes("BP_") || text.includes("TArray<") ||
        text.includes("TMap<") || text.includes("TSet<")) {
        STATE.stats.filtered_ue_internal++; return false;
    }

    const score = computeNaturalness(text);
    if (score < CONFIG.min_naturalness_score) {
        STATE.stats.filtered_score++;
        return false;
    }

    return true;
}

// ============== UTF-16 scan (Unicode كامل) ==============
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

            const isAccepted = (
                (code >= 0x20 && code <= 0x7E) ||
                (code >= 0xA0 && code <= 0x24F) ||
                (code >= 0x0590 && code <= 0x06FF)
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
    } catch (e) { }
    return results;
}

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
            } catch (e) { }
        }
    }

    const elapsed = Date.now() - t0;
    send({
        type: 'scan_complete',
        message: `[v5] scan #${STATE.stats.scans} في ${elapsed}ms — ${newTextsFound} جديد (إجمالي ${STATE.texts.size})`,
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
            if (arBytes <= maxBytes) item.addr.writeUtf16String(ar);
            else item.addr.writeUtf16String(ar.substring(0, text.length));
            item.replaced = true;
            count++;
        } catch (e) { failures++; }
    }
    if (count > 0 || failures > 0) {
        STATE.stats.replaced += count;
        STATE.stats.write_failures += failures;
        send({ type: 'replaced', message: `[v5] استبدل ${count} (${failures} فشل)`, count, failures });
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
            if (!STATE.cache[key]) { STATE.cache[key] = msg.translations[key]; added++; }
        }
        send({ type: 'log', message: `[v5] استلم ${added} ترجمة` });
        applyTranslations();
    }
});
recv('rescan_now', () => { fullScan(); });
recv('shutdown', () => {
    if (STATE.scanIntervalId) clearInterval(STATE.scanIntervalId);
    send({ type: 'log', message: '[v5] متوقّف' });
});

rpc.exports = {
    getstats: () => ({ ...STATE.stats, cache_size: Object.keys(STATE.cache).length, tracked_texts: STATE.texts.size }),
    rescannow: () => { fullScan(); return 'OK'; },
    pingbatch: (data) => {
        if (data && data.translations) {
            for (const key of Object.keys(data.translations)) STATE.cache[key] = data.translations[key];
            applyTranslations();
        }
        return Object.keys(STATE.cache).length;
    },
    listall: () => Array.from(STATE.texts.keys()),
};

try {
    send({ type: 'log', message: `[v5] Aggressive CVar description killer. Score threshold: ${CONFIG.min_naturalness_score}` });
    fullScan();
    STATE.scanIntervalId = setInterval(() => {
        try { fullScan(); }
        catch (e) { send({ type: 'error', message: '[v5] scan خطأ: ' + e }); }
    }, CONFIG.scan_interval_ms);
    STATE.ready = true;
    send({ type: 'ready', message: `[v5] جاهز! وُجد ${STATE.texts.size} نص.` });
} catch (error) {
    send({ type: 'error', message: '[v5] init خطأ: ' + error });
}
