// Manor Lords Arabic Translator — v6 (Diff-based capture)
//
// الفكرة الجوهرية:
//   - نُبقي filters v5 (تُقلّل الضوضاء بنسبة 90%+)
//   - نُضيف نظام snapshots: المستخدم يُنشئ لقطة قبل فعل (مثل فتح Settings)،
//     ثم لقطة بعد. الفرق = نصوص محمَّلة لتلك الشاشة فقط.
//   - يتجاهل تلقائياً كل نصوص UE/plugin المحمَّلة دائماً (موجودة في كل snapshot)
//
// RPC جديدة:
//   snapshot(label)            — احفظ كل النصوص المتراكمة الآن تحت label
//   getsnapshot(label)         — اقرأ snapshot
//   diffsnapshots(from, to)    — أعد النصوص في to لكنها ليست في from
//   listsnapshots()            — أعد كل أسماء snapshots
//   clearsnapshots()           — احذف كل snapshots
//   clearaccumulated()         — احذف STATE.texts (لتبدأ من الصفر بين الإجراءات)
//
// التدفّق المثالي للمستخدم:
//   1. شغّل اللعبة، اترك القائمة الرئيسية ظاهرة
//   2. > s main             ← snapshot للقائمة الرئيسية
//   3. اضغط Settings في اللعبة
//   4. انتظر scan دوري (~10ث)
//   5. > s settings         ← snapshot لشاشة Settings
//   6. > d main settings    ← يُظهر فقط نصوص Settings الجديدة (مثلاً: "Graphics", "Audio", "Controls")

console.log("[ManorLords-v6-diff] Loading…");

const STATE = {
    cache: {},
    texts: new Map(),                  // كل النصوص المتراكمة (للـ scan الدوري)
    snapshots: {},                     // { label: [text1, text2, ...] }
    stats: {
        scans: 0,
        candidates_total: 0,
        filtered_short: 0,
        filtered_arabic: 0,
        filtered_metasound: 0,
        filtered_asset_path: 0,
        filtered_audio_device: 0,
        filtered_cvar_ref: 0,
        filtered_tech_term: 0,
        filtered_option_list: 0,
        filtered_desc_prefix: 0,
        filtered_path: 0,
        filtered_ue_internal: 0,
        filtered_score: 0,
        texts_found: 0,
        replaced: 0,
        write_failures: 0,
    },
    scanIntervalId: null,
};

const CONFIG = {
    scan_interval_ms: 5000,             // أسرع — لأن المستخدم تفاعلي
    min_text_length: 4,
    max_text_length: 800,
    chunk_size: 64 * 1024,
    min_region_size: 4096,
    max_region_size: 200 * 1024 * 1024,
    send_new_texts_to_python: false,    // **مغلق** — لا نُريد flood الـ Python
    skip_file_backed: true,
    min_naturalness_score: 5,
};

// ============== فلاتر (نسخة v5 المختصرة) ==============
function isMetaSoundString(text) {
    if (/_v\d+$/.test(text)) return true;
    if (/_\d+\.\d+$/.test(text)) return true;
    if (/^(External_|Variable_|Variable \(|Output_Output\.|Input_Input\.|Literal_Literal\.|Template_UE\.|Crossfade\.|TriggerRoute\.|TriggerAccumulator\.|TriggerAny\.|TriggerCompare\.|BandSplitter\.|AudioMixer\.|VariableAccessor\.|VariableMutator\.|VariableDeferredAccessor\.|InitVariable\.|Array\.|Convert\.|MapRange\.|AbsoluteValue\.|Print Log\.|SampleAndHold\.|ADSR Envelope\.|AD Envelope\.|Receive\.|Send\.|Output\.|Input\.|Literal\.)/.test(text)) return true;
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
        if (/(audio|realtek|nvidia|speakers|microphone|headphones|hdmi|hyperx|voicemeeter|dualsense|bluetooth)/i.test(text)) return true;
    }
    return false;
}
function containsCVarReference(text) {
    return /\b[a-z][a-z0-9]*\.[A-Z][a-zA-Z0-9]+(\.[A-Z][a-zA-Z0-9]+)*\b/.test(text);
}
const TECH_TERMS = ["CVar","cvar","PSO","PSOs","GBuffer","BVH","RHI","DXR","RDG","LRU","MSAA","VSM","DFAO","SSAO","TSR","TAA","VRAM","AABB","RGP","GPU","shader","Shader","Shaders","clipmap","Clipmap","raytrac","RayTrac","raster","Raster","scalability","Scalability","atlas","Atlas","voxel","Voxel","framebuffer","Framebuffer","rendertarget","RenderTarget","render thread","Render Thread","command buffer","Command Buffer","compute shader","Compute Shader","vertex shader","Vertex Shader","pixel shader","Pixel Shader","Substrate","subsurface","octree","Octree","frustum","Frustum","occlusion","Occlusion","Nanite","NaNite","Lumen","lumen","MetaSound","Metasound","PhysX","Chaos","kinematic","Kinematic","demosaic","tessellation","Tessellation","anisotrop","Anisotrop","thread group","Thread Group","memory pool","Memory Pool","buffer pool","Buffer Pool","instance buffer","Instance Buffer","DLSS","FSR","XeSS","Reflex","Streamline","actor channel","Actor Channel","subsystem","Subsystem","asset registry","Asset Registry","blueprint","Blueprint","FName","FString","FText","UObject","AActor"];
function containsTechTerm(text) {
    for (const term of TECH_TERMS) if (text.includes(term)) return true;
    return false;
}
function isOptionList(text) {
    if (/^\s*\d+\s*[:\-\(]/.test(text)) return true;
    if (/^\s*[<>]\s*=?\s*\d+/.test(text)) return true;
    if (text.includes("(default)") || text.includes("[default]")) return true;
    if (/\(default\s*=\s*/.test(text)) return true;
    if (/^[\s]*-?\d+\s*:\s*/.test(text)) return true;
    return false;
}
const DESC_PREFIXES_V5 = ["When ","If ","Note","Render ","Force ","Forces ","Larger ","Higher ","Lower ","Bias ","Causes ","Uses ","Use ","This ","These ","Those ","Will ","Would ","May ","Must ","Should ","Probably ","Typical ","Default ","Defaults ","Override ","Overrides ","Specifies ","Sets ","Set ","Enable ","Enables ","Disable ","Disables ","Allow ","Allows ","Toggle ","Toggles ","Whether ","Controls ","Determines ","Define ","Defines ","Skip ","Skips ","World space ","Screen space ","View space ","Object space ","Number of ","Maximum ","Minimum ","Min ","Max ","Texture ","Mesh ","Material ","Geometry ","Geometric","Performs ","Perform ","Includes ","Include ","Exclude ","Excludes ","Run ","Runs ","Process ","Processes ","Cache ","Caches ","Apply ","Applies ","Add ","Adds ","Remove ","Removes ","Get ","Gets ","Find ","Finds ","Returns ","Return ","Create ","Creates ","Destroy ","Destroys ","Update ","Updates ","Read ","Reads ","Write ","Writes ","Output ","Outputs ","Input ","Inputs ","Configure ","Configures ","Convert ","Converts ","Validate ","Validates ","Verify ","Verifies ","Wait ","Waits ","Block ","Blocks ","Time ","Frame ","Multiplier ","Threshold ","Scale ","Scales ","Initial ","Final ","Current ","Previous ","Next ","Selects ","Select ","Choose ","Chooses ","Sequencer ","Console ","Editor ","Engine ","Platform ","Adjust ","Adjusts ","Adjusting ","Setting ","Settings ","Avoid ","Avoids ","Prevent ","Prevents ","Computes ","Compute ","Calculate ","Calculates ","Provides ","Provide ","Handle ","Handles ","Handling ","0 ","1 ","2 ","3 ","4 ","5 ","<",">","=","["];
function isDescriptionPrefix(text) {
    if (text.length < 25) return false;
    for (const p of DESC_PREFIXES_V5) if (text.startsWith(p)) return true;
    return false;
}
function isLongTechExplain(text) {
    if (text.length < 80) return false;
    if (text.includes(":") && /\d/.test(text)) return true;
    if (text.includes("(") && text.includes(")") && /\d/.test(text) && text.length > 120) return true;
    return false;
}
function computeNaturalness(text) {
    let score = 0;
    const spaces = (text.match(/ /g) || []).length;
    score += spaces * 2;
    if (/[a-z] [A-Z]/.test(text)) score += 3;
    if (/[a-z] [a-z]/.test(text)) score += 2;
    if (/[.,!?](\s|$)/.test(text)) score += 2;
    const commonWords = /\b(the|and|of|to|in|is|a|you|your|for|with|on|are|that|this|by|or|from|be|at|as|an|will|can|all|when|what|how|do|not|but|have|has|been|new|game|menu|settings|options|continue|quit|exit)\b/gi;
    score += (text.match(commonWords) || []).length * 2;
    if (/[À-ſ]/.test(text)) score += 2;
    if (/[؀-ۿ]/.test(text)) score -= 100;
    if (text.length >= 4 && text.length <= 80) score += 1;
    if (text.length >= 8 && text.length <= 50) score += 2;
    if (/^[A-Z][a-z]/.test(text)) score += 1;
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
    if (text.length < CONFIG.min_text_length || text.length > CONFIG.max_text_length) { STATE.stats.filtered_short++; return false; }
    if (/[؀-ۿ]/.test(text)) { STATE.stats.filtered_arabic++; return false; }
    if (containsCVarReference(text)) { STATE.stats.filtered_cvar_ref++; return false; }
    if (containsTechTerm(text)) { STATE.stats.filtered_tech_term++; return false; }
    if (isOptionList(text)) { STATE.stats.filtered_option_list++; return false; }
    if (isLongTechExplain(text)) { STATE.stats.filtered_desc_prefix++; return false; }
    if (isMetaSoundString(text)) { STATE.stats.filtered_metasound++; return false; }
    if (isAssetPath(text)) { STATE.stats.filtered_asset_path++; return false; }
    if (isAudioDeviceName(text)) { STATE.stats.filtered_audio_device++; return false; }
    if (text.includes("\\") || /^[A-Z]:[\/\\]/.test(text)) { STATE.stats.filtered_path++; return false; }
    if (isDescriptionPrefix(text)) { STATE.stats.filtered_desc_prefix++; return false; }
    if (/(Default__|FString|UObject|FName|BP_|TArray<|TMap<|TSet<)/.test(text)) { STATE.stats.filtered_ue_internal++; return false; }
    if (computeNaturalness(text) < CONFIG.min_naturalness_score) { STATE.stats.filtered_score++; return false; }
    return true;
}

// ============== Scan ==============
function scanUTF16Chunk(baseAddr, size) {
    const results = [];
    try {
        const chunk = baseAddr.readByteArray(size);
        const view = new Uint8Array(chunk);
        let text = '';
        let startAddr = null;
        for (let i = 0; i < view.length - 1; i += 2) {
            const code = view[i] | (view[i + 1] << 8);
            const ok = (code >= 0x20 && code <= 0x7E) || (code >= 0xA0 && code <= 0x24F) || (code >= 0x0590 && code <= 0x06FF);
            if (ok) {
                if (!startAddr) startAddr = baseAddr.add(i);
                text += String.fromCharCode(code);
            } else {
                if (text.length >= CONFIG.min_text_length) {
                    STATE.stats.candidates_total++;
                    if (isValidGameText(text)) results.push({ text, addr: startAddr });
                }
                text = ''; startAddr = null;
            }
        }
        if (text.length >= CONFIG.min_text_length && startAddr) {
            STATE.stats.candidates_total++;
            if (isValidGameText(text)) results.push({ text, addr: startAddr });
        }
    } catch (e) {}
    return results;
}

function fullScan() {
    STATE.stats.scans++;
    const t0 = Date.now();
    let newTextsFound = 0;
    const ranges = Process.enumerateRanges('rw-');
    for (const range of ranges) {
        if (CONFIG.skip_file_backed && range.file) continue;
        if (range.size < CONFIG.min_region_size || range.size > CONFIG.max_region_size) continue;
        for (let offset = 0; offset < range.size; offset += CONFIG.chunk_size) {
            try {
                const sz = Math.min(CONFIG.chunk_size, range.size - offset);
                const addr = range.base.add(offset);
                const results = scanUTF16Chunk(addr, sz);
                for (const r of results) {
                    if (!STATE.texts.has(r.text)) {
                        STATE.texts.set(r.text, { addr: r.addr, last_seen: Date.now(), replaced: false });
                        STATE.stats.texts_found++;
                        newTextsFound++;
                    } else {
                        const item = STATE.texts.get(r.text);
                        item.last_seen = Date.now();
                        item.addr = r.addr;
                    }
                }
            } catch (e) {}
        }
    }
    const elapsed = Date.now() - t0;
    send({
        type: 'scan_complete',
        message: `[v6] scan #${STATE.stats.scans} في ${elapsed}ms — ${newTextsFound} جديد (إجمالي ${STATE.texts.size})`,
    });
    applyTranslations();
}

function applyTranslations() {
    let count = 0, failures = 0;
    for (const [text, item] of STATE.texts) {
        const ar = STATE.cache[text];
        if (!ar || item.replaced) continue;
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
        send({ type: 'replaced', message: `[v6] استبدل ${count} (${failures} فشل)` });
    }
}

recv('translation', (msg) => {
    if (msg.original && msg.translated) {
        STATE.cache[msg.original] = msg.translated;
        applyTranslations();
    }
});
recv('translations_batch', (msg) => {
    if (msg.translations) {
        let added = 0;
        for (const key of Object.keys(msg.translations)) {
            if (!STATE.cache[key]) { STATE.cache[key] = msg.translations[key]; added++; }
        }
        send({ type: 'log', message: `[v6] استلم ${added} ترجمة` });
        applyTranslations();
    }
});

// ============== RPC للـ Diff workflow ==============
rpc.exports = {
    // إحصاءات
    getstats: () => ({
        ...STATE.stats,
        tracked_texts: STATE.texts.size,
        snapshot_count: Object.keys(STATE.snapshots).length,
        snapshots: Object.keys(STATE.snapshots).map(k => ({ label: k, size: STATE.snapshots[k].length })),
    }),

    // scan فوري
    rescannow: () => { fullScan(); return STATE.texts.size; },

    // ============ Snapshot API ============
    // أنشئ snapshot بنفس النصوص المتراكمة الآن
    snapshot: (label) => {
        if (!label) return { ok: false, error: "label required" };
        const texts = Array.from(STATE.texts.keys());
        STATE.snapshots[label] = texts;
        send({ type: 'log', message: `[v6] snapshot '${label}': ${texts.length} نص` });
        return { ok: true, label: label, size: texts.length };
    },

    // أعد كل النصوص في snapshot معيّن
    getsnapshot: (label) => {
        if (!STATE.snapshots[label]) return { ok: false, error: "label not found" };
        return { ok: true, texts: STATE.snapshots[label] };
    },

    // الفرق: النصوص في `to` لكنها ليست في `from`
    diffsnapshots: (fromLabel, toLabel) => {
        if (!STATE.snapshots[fromLabel]) return { ok: false, error: `'${fromLabel}' not found` };
        if (!STATE.snapshots[toLabel]) return { ok: false, error: `'${toLabel}' not found` };
        const fromSet = new Set(STATE.snapshots[fromLabel]);
        const diff = STATE.snapshots[toLabel].filter(t => !fromSet.has(t));
        return {
            ok: true,
            from: fromLabel,
            to: toLabel,
            from_size: STATE.snapshots[fromLabel].length,
            to_size: STATE.snapshots[toLabel].length,
            diff_size: diff.length,
            texts: diff,
        };
    },

    // قائمة كل الـ snapshots
    listsnapshots: () => {
        return Object.keys(STATE.snapshots).map(k => ({ label: k, size: STATE.snapshots[k].length }));
    },

    // احذف snapshot معيّن
    delsnapshot: (label) => {
        if (!STATE.snapshots[label]) return { ok: false, error: "not found" };
        delete STATE.snapshots[label];
        return { ok: true };
    },

    // احذف كل snapshots
    clearsnapshots: () => {
        const n = Object.keys(STATE.snapshots).length;
        STATE.snapshots = {};
        return { ok: true, cleared: n };
    },

    // امسح النصوص المتراكمة (للبدء من الصفر بين الإجراءات)
    clearaccumulated: () => {
        const n = STATE.texts.size;
        STATE.texts.clear();
        return { ok: true, cleared: n };
    },

    pingbatch: (data) => {
        if (data && data.translations) {
            for (const key of Object.keys(data.translations)) STATE.cache[key] = data.translations[key];
            applyTranslations();
        }
        return Object.keys(STATE.cache).length;
    },
};

try {
    send({ type: 'log', message: `[v6-diff] Diff-mode hook loaded. Use snapshot/diff RPC commands.` });
    // **مهم**: نُؤجّل scan الأوّلي بـ setTimeout كي يرجع script.load() فوراً.
    // scan كامل الـ heap يأخذ 10-30ث، يتجاوز Frida load timeout.
    setTimeout(() => {
        try {
            fullScan();
            send({ type: 'ready', message: `[v6-diff] جاهز! وُجد ${STATE.texts.size} نص. scan كل ${CONFIG.scan_interval_ms / 1000}ث.` });
        } catch (e) {
            send({ type: 'error', message: '[v6] initial scan خطأ: ' + e });
        }
    }, 100);
    STATE.scanIntervalId = setInterval(() => {
        try { fullScan(); } catch (e) { send({ type: 'error', message: '[v6] scan خطأ: ' + e }); }
    }, CONFIG.scan_interval_ms);
} catch (error) {
    send({ type: 'error', message: '[v6-diff] init خطأ: ' + error });
}
