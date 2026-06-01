// Manor Lords Arabic Translator — v3 (heap-only + smart filters)
//
// المشكلة في v2:
//   scan كامل الذاكرة → 99% نصوص محرّك Unreal، CVars، Windows DLL strings.
//   نصوص اللعبة الفعلية (مثل "New Game") مدفونة بين ملايين السلاسل التافهة.
//
// التحسينات الجوهرية في v3:
//   1) **Heap-only scan**: نتجاهل أي memory range مرتبط بملف (.dll, .exe, mapped).
//      نصوص UI الديناميكية تعيش في heap (range.file == null).
//      هذا الفلتر وحده يحذف ~95% من الضوضاء.
//
//   2) **Filter patterns CVar**: r./p./a./fx./t./s./bp./net./au./wp./...
//   3) **Filter C++ identifiers**: contains :: / starts with g_ m_ s_ / FCamelCase
//   4) **Filter Windows paths**: \\, C:, /Game/, /Engine/, /Script/, ...
//   5) **Filter env vars**: contains = early
//   6) **Filter CVar descriptions**: starts with "Enables ", "Sets ", "Whether to ", ...
//   7) **Stats** عن أسباب الاستبعاد (لتشخيص الفلاتر)
//
// النتيجة المتوقّعة: تقليل من ~10K نص ملتقط إلى ~200-500 نص فعلاً من اللعبة.

console.log("[ManorLords-v3] Loading…");

const STATE = {
    cache: {},
    texts: new Map(),
    stats: {
        scans: 0,
        ranges_scanned: 0,
        ranges_skipped_file_backed: 0,
        ranges_skipped_size: 0,
        ranges_skipped_protection: 0,
        candidates_total: 0,
        filtered_short: 0,
        filtered_arabic: 0,
        filtered_control: 0,
        filtered_numeric: 0,
        filtered_cvar: 0,
        filtered_path: 0,
        filtered_envvar: 0,
        filtered_cpp_ident: 0,
        filtered_ue_internal: 0,
        filtered_desc_prefix: 0,
        filtered_low_alpha: 0,
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
    max_text_length: 500,
    chunk_size: 64 * 1024,
    min_region_size: 4096,
    max_region_size: 200 * 1024 * 1024,
    send_new_texts_to_python: true,
    skip_file_backed: true,  // **المفتاح الأهم**: نتجاهل DLL/EXE/Mapped
};

// ============== أنماط CVar للاستبعاد ==============
// لو النص يبدأ بأحد هذه + نقطة → CVar
const CVAR_PREFIXES = [
    "r.", "p.", "a.", "fx.", "t.", "s.", "bp.", "net.", "au.", "wp.",
    "d3d12.", "RHI.", "gc.", "demo.", "mass.", "np2.", "gpu.", "Niagara.",
    "TaskGraph.", "Engine.", "Sequencer.", "Slate.", "AssetRegistry.",
    "MovieScene.", "AnimGraph.", "BehaviorTree.", "AISystem.", "Constraints.",
    "Localization.", "WindowsApplication.", "AudioThread.", "Streamline.",
    "HairStrands.", "Substrate.", "Visibility.", "Foliage.", "Landscape.",
    "PluginManager.", "Material.", "Display.", "Movie.", "RenderInterp.",
    "ai.", "cac.", "compat.", "con.", "core.", "cook.", "geometry.",
    "grass.", "health.", "http.", "input.", "io.", "Iris.", "landscape.",
    "Lumen.", "Mass.", "mi.", "mr.", "MallocBinned.", "MallocBinned2.",
    "OpenGL.", "OSS.", "OSSNull.", "PlayerController.", "pak.", "pakcache.",
    "ref.", "Replay.", "Shader.", "StateTree.", "Streaming.", "tick.",
    "Translator.", "UE.", "voice.", "vm.", "vr.", "WindowsCursor.", "xr.",
    "ShaderPipelineCache.", "PhysicsField.", "ProgramBinaryCache.",
    "Photography.", "EnhancedInput.", "Concurrency.", "BuildPatch.",
    "Chaos.", "Cloth.", "FieldSystemEngine.", "TypedElements.",
    "ChaosClothing.", "MeshDrawCommands.", "ProfilerType.", "RenderDoc.",
    "BehaviorTree.", "TextureLoader.", "AnalyticsET.", "ImageWriteQueue.",
    "g.", "Niagara_", "DebugViewModeHelpers.", "Compat.",
    "fc.", "vis.", "wg.", "lod.", "framegrabber.", "BuildPatchFileConstructor.",
    "ImgMedia.", "BuildPatchServicesLocal.", "ChaosCloth.", "ClusterUnion.",
    "MessageBus.", "MorphTarget.", "BuildPatch.", "DPI.", "GeometryCollection.",
    "GameFeaturePlugin.", "GameplayMediaEncoder.", "GameplayTags.",
    "HighlightRecorder.", "InstancedStruct.", "LevelStreaming.",
    "OpenXR.", "Replay.", "ScriptableTools.", "Sequencer.", "TimeoutManager.",
    "WorldlessGetAudioTimeBehavior.", "rhi.", "mmio.", "splines.",
    "stats.", "log.", "memory.", "save.", "Niagara.", "AssetManager.",
    "AnimationSharingManager.", "AnimNext.", "Time.", "Sound.",
    "PluginManager.", "AudioMixer.", "blueprint.", "Render.", "n.",
];

const PATH_INDICATORS = [
    "C:\\", "D:\\", "E:\\", "C:/", "D:/", "E:/",
    "\\Windows", "\\WINDOWS", "\\Registry", "\\Device",
    "/Game/", "/Engine/", "/Script/", "/Plugins/", "/Content/",
    ".dll", ".DLL", ".exe", ".EXE", ".pak", ".uasset", ".umap",
    ".json", ".ini", ".ushaderbytecode", ".ushaderpipelines",
    ".sys", ".log", ".cfg", ".uplugin", ".cs", ".cpp", ".h",
    "\\Sessions\\", "\\AppData\\", "\\Local\\",
];

const UE_INTERNAL_PATTERNS = [
    "Default__", "BP_", "FString", "FName", "UObject",
    "UE4", "UE5", "Blueprint", "nullptr", "undefined",
    "TArray<", "TMap<", "TSet<", "TSharedPtr",
    "ENGINE_API", "CORE_API", "F_", "U_", "A_",
    "_GEN_VARIABLE", "_C\0", "__INIT__",
];

// CVar description prefixes — جمل تبدأ بهذه = شرح CVar
const DESC_PREFIXES = [
    "Enable ", "Enables ", "Enabling ", "Disable ", "Disables ", "Disabling ",
    "Set ", "Sets ", "Setting ", "Whether ", "Controls ", "Controlling ",
    "If true", "If false", "If enabled", "If disabled", "If non-zero",
    "If 1", "If 0", "If 2", "If > 0", "If set",
    "Toggles ", "Toggle ", "Allows ", "Allow ", "Allowing ",
    "Used to ", "Helps ", "Used for ", "Used in ",
    "Forces ", "Force ", "Forcing ", "Skip ", "Skips ", "Skipping ",
    "Number of ", "Maximum ", "Max ", "Minimum ", "Min ",
    "Sets the ", "Returns ", "Return ", "Specifies ",
    "Configure ", "Configures ", "Configuring ", "Print ", "Prints ",
    "Defines ", "Define ", "Default ", "Determines ",
    "Make ", "Makes ", "Limit ", "Limits ", "Limiting ",
    "The ", "When ", "While ", "Whether to ", "Should ", "Switch ",
    "0:", "1:", "2:", "3:", "0 ", "1 ", "2 ",
    "Threshold ", "Override ", "Overrides ", "Override the ",
    "Pause ", "Resume ", "Trigger ", "Triggers ",
    "Add ", "Adds ", "Adding ", "Remove ", "Removes ", "Removing ",
    "Get ", "Gets ", "Getting ", "Has ", "Cannot ", "Can not ",
    "Show ", "Shows ", "Showing ", "Hide ", "Hides ", "Hiding ",
    "Apply ", "Apples ", "Applying ", "Reset ", "Resets ", "Resetting ",
    "Send ", "Sends ", "Sending ", "Receive ", "Receives ",
    "Save ", "Saves ", "Saving ", "Load ", "Loads ", "Loading ",
];

// ============== الفلاتر ==============
function isCVarPattern(text) {
    for (const p of CVAR_PREFIXES) {
        if (text.startsWith(p)) {
            // النصوص الحقيقية لن تكون قصيرة + بنقطة + camelCase
            // CVar مثل r.Lumen.SomeFeature
            const tail = text.substring(p.length);
            if (/^[A-Za-z][A-Za-z0-9._]*$/.test(tail)) return true;
        }
    }
    return false;
}

function isPathLike(text) {
    for (const p of PATH_INDICATORS) {
        if (text.includes(p)) return true;
    }
    if (/^[A-Z]:[/\\]/.test(text)) return true;  // C:/ or C:\
    return false;
}

function isEnvVar(text) {
    // VAR_NAME=value
    if (/^[A-Z][A-Z0-9_]{1,}=/.test(text)) return true;
    return false;
}

function isCppIdentifier(text) {
    if (text.includes("::")) return true;
    if (/^[gms]_[A-Z]/.test(text)) return true;  // g_Foo, m_Bar, s_Baz
    // فقط CamelCase بدون مسافات + يبدأ بـ F/U/A (UE convention)
    if (/^[FUEA][A-Z][A-Za-z0-9]+$/.test(text) && text.length < 40) return true;
    return false;
}

function isUEInternal(text) {
    for (const p of UE_INTERNAL_PATTERNS) {
        if (text.includes(p)) return true;
    }
    return false;
}

function isDescriptionPrefix(text) {
    // CVar descriptions الطويلة دائماً تبدأ بكلمة معيّنة
    if (text.length < 30) return false;  // الوصف عادةً طويل
    for (const p of DESC_PREFIXES) {
        if (text.startsWith(p)) return true;
    }
    return false;
}

function isValidGameText(text) {
    if (!text || typeof text !== 'string') return false;

    // الحد الأدنى/الأقصى للطول
    if (text.length < CONFIG.min_text_length) { STATE.stats.filtered_short++; return false; }
    if (text.length > CONFIG.max_text_length) { STATE.stats.filtered_short++; return false; }

    // عربي بالفعل (ترجمة سابقة)
    if (/[؀-ۿ]/.test(text)) { STATE.stats.filtered_arabic++; return false; }

    // أحرف تحكّم فقط
    if (/^[\x00-\x1F\x7F-\x9F]+$/.test(text)) { STATE.stats.filtered_control++; return false; }

    // أرقام/hex فقط
    if (/^[0-9a-fA-F\s\.\-_:\/\\]+$/.test(text)) { STATE.stats.filtered_numeric++; return false; }

    // CVar
    if (isCVarPattern(text)) { STATE.stats.filtered_cvar++; return false; }

    // مسارات
    if (isPathLike(text)) { STATE.stats.filtered_path++; return false; }

    // متغيرات بيئة
    if (isEnvVar(text)) { STATE.stats.filtered_envvar++; return false; }

    // معرّفات C++
    if (isCppIdentifier(text)) { STATE.stats.filtered_cpp_ident++; return false; }

    // أنماط UE داخلية
    if (isUEInternal(text)) { STATE.stats.filtered_ue_internal++; return false; }

    // شروحات CVars
    if (isDescriptionPrefix(text)) { STATE.stats.filtered_desc_prefix++; return false; }

    // كثافة حروف منخفضة (لازم 30%+ حروف لاتينية)
    const letters = (text.match(/[a-zA-Z]/g) || []).length;
    if (letters < 3) { STATE.stats.filtered_low_alpha++; return false; }
    if (letters / text.length < 0.4) { STATE.stats.filtered_low_alpha++; return false; }

    return true;
}

// ============== استخراج UTF-16 من chunk ==============
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

            if (hi === 0 && lo >= 0x20 && lo <= 0x7E) {
                if (!startAddr) startAddr = baseAddr.add(i);
                text += String.fromCharCode(lo);
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
        // **الفلتر الأقوى**: نتجاهل أي range مرتبط بملف
        if (CONFIG.skip_file_backed && range.file) {
            STATE.stats.ranges_skipped_file_backed++;
            continue;
        }

        if (range.size < CONFIG.min_region_size ||
            range.size > CONFIG.max_region_size) {
            STATE.stats.ranges_skipped_size++;
            continue;
        }

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
        message: `[v3] scan #${STATE.stats.scans} في ${elapsed}ms — ${newTextsFound} نص جديد (إجمالي ${STATE.texts.size})`,
        new_texts: newTextsFound,
        total_texts: STATE.texts.size,
        elapsed_ms: elapsed,
        ranges_scanned: STATE.stats.ranges_scanned,
        ranges_skipped: STATE.stats.ranges_skipped_file_backed,
    });

    applyTranslations();
}

// ============== استبدال النصوص ==============
function applyTranslations() {
    let count = 0;
    let failures = 0;

    for (const [text, item] of STATE.texts) {
        const ar = STATE.cache[text];
        if (!ar) continue;
        if (item.replaced) continue;  // مرة واحدة فقط

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
            message: `[v3] استبدل ${count} نص (${failures} فشل)`,
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
        send({ type: 'log', message: `[v3] استلم ${added} ترجمة جديدة (إجمالي cache: ${Object.keys(STATE.cache).length})` });
        applyTranslations();
    }
});

recv('rescan_now', () => {
    fullScan();
});

recv('shutdown', () => {
    if (STATE.scanIntervalId) {
        clearInterval(STATE.scanIntervalId);
        STATE.scanIntervalId = null;
    }
    send({ type: 'log', message: '[v3] متوقّف' });
});

// ============== RPC ==============
rpc.exports = {
    getstats: () => ({
        ...STATE.stats,
        cache_size: Object.keys(STATE.cache).length,
        tracked_texts: STATE.texts.size,
    }),
    rescannow: () => {
        fullScan();
        return 'OK';
    },
    pingbatch: (data) => {
        if (data && data.translations) {
            for (const key of Object.keys(data.translations)) {
                STATE.cache[key] = data.translations[key];
            }
            applyTranslations();
        }
        return Object.keys(STATE.cache).length;
    },
    listrecent: (limit) => {
        const arr = Array.from(STATE.texts.entries())
            .sort((a, b) => b[1].last_seen - a[1].last_seen)
            .slice(0, limit || 20)
            .map(([text, item]) => ({
                text: text.substring(0, 100),
                replaced: item.replaced,
                addr: item.addr.toString(),
            }));
        return arr;
    },
    listall: () => {
        // أعد كل النصوص — للتشخيص
        return Array.from(STATE.texts.keys());
    },
};

// ============== التهيئة ==============
try {
    send({
        type: 'log',
        message: `[v3] heap-only scan جاهز. سيتجاوز DLL/EXE/Mapped تلقائياً.`,
    });

    fullScan();

    STATE.scanIntervalId = setInterval(() => {
        try {
            fullScan();
        } catch (e) {
            send({ type: 'error', message: '[v3] scan خطأ: ' + e });
        }
    }, CONFIG.scan_interval_ms);

    STATE.ready = true;
    send({
        type: 'ready',
        message: `[v3] جاهز! scan أوّلي وجد ${STATE.texts.size} نص. سيُعاد كل ${CONFIG.scan_interval_ms / 1000} ث.`,
    });
} catch (error) {
    send({ type: 'error', message: '[v3] init خطأ: ' + error });
}
