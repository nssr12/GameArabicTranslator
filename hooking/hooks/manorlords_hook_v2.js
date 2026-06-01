// Manor Lords Arabic Translator — v2 (محسَّن)
//
// التحسينات عن v1:
//  ✓ scan دوري كل 10 ث (يلتقط نصوص جديدة عند تغيير شاشة)
//  ✓ يُرسل كل نص جديد لـ Python (send: text_found)
//  ✓ يحدّ حجم الترجمة الجديدة بحجم النص الأصلي (لا overflow)
//  ✓ يحفظ كل نصّ مع عنوانه — يحدّث في-المكان عند ورود الترجمة
//  ✓ يستجيب لـ batch translations sync من Python
//  ✓ stats محدَّثة في الذاكرة + قابلة للاستعلام عبر RPC
//
// المعمارية:
//   1) عند التحميل: scan أوّلي + ابدأ الـ periodic scan
//   2) لكل نصّ جديد يُلتقط: send لـ Python فوراً
//   3) Python يُترجم + يُرسل ترجمات batched
//   4) النصوص تُستبدل في الذاكرة (بحدّ الحجم الأصلي)
//
// ⚠ ملاحظات تقنية:
//   - الكتابة فوق النص الأصلي محدودة بحجمه — لو الترجمة العربية أطول، تُقصَّر
//   - للنصوص الطويلة الحلّ الأنسب هو تخصيص ذاكرة جديدة + تحديث pointer (يحتاج
//     معرفة struct اللعبة — نشر التقدمي لاحقاً)

console.log("[ManorLords-v2] Loading…");

// ============== الحالة ==============
const STATE = {
    cache: {},               // english -> arabic
    texts: new Map(),        // english -> { addr, last_seen, replaced }
    stats: {
        scans: 0,
        texts_found: 0,
        cache_hits: 0,
        replaced: 0,
        write_failures: 0,
    },
    scanIntervalId: null,
    gameModule: null,
    ready: false,
};

// ============== الإعدادات ==============
const CONFIG = {
    scan_interval_ms: 10000,         // إعادة scan كل 10 ث
    min_text_length: 3,
    max_text_length: 500,
    chunk_size: 64 * 1024,           // 64KB chunks
    min_region_size: 1024,
    max_region_size: 500 * 1024 * 1024,
    send_new_texts_to_python: true,  // أرسل كل نص جديد لـ Python
};

// ============== فلتر النصوص ==============
function isValidEnglishText(text) {
    if (!text || typeof text !== 'string') return false;
    if (text.length < CONFIG.min_text_length || text.length > CONFIG.max_text_length) return false;
    // عربي بالفعل
    if (/[؀-ۿ]/.test(text)) return false;
    // أحرف تحكّم فقط
    if (/^[\x00-\x1F\x7F-\x9F]+$/.test(text)) return false;
    // أرقام/hex فقط
    if (/^[0-9a-fA-F\s\.\-_:\/\\]+$/.test(text)) return false;
    // مسارات و امتدادات ملفات
    if (text.includes('.dll') || text.includes('.exe') || text.includes('.pak') ||
        text.includes('.uasset') || text.includes('.umap') || text.includes('.json')) return false;
    // أسماء UE داخلية
    if (text.includes('Default__') || text.includes('/Game/') || text.includes('/Engine/') ||
        text.includes('/Script/') || text.includes('BP_')) return false;
    if (text.includes('nullptr') || text.includes('undefined') || text.includes('FString') ||
        text.includes('FName') || text.includes('UObject')) return false;
    if (text.includes('UE4') || text.includes('UE5') || text.includes('Blueprint')) return false;
    // كثافة حروف
    const letters = (text.match(/[a-zA-Z]/g) || []).length;
    if (letters < 2) return false;
    if (letters / text.length < 0.3 && text.length > 5) return false;
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

            // ASCII printable في UTF-16 LE: byte 0 = char, byte 1 = 0
            if (hi === 0 && lo >= 0x20 && lo <= 0x7E) {
                if (!startAddr) startAddr = baseAddr.add(i);
                text += String.fromCharCode(lo);
            } else {
                if (text.length >= CONFIG.min_text_length && isValidEnglishText(text)) {
                    results.push({ text, addr: startAddr });
                }
                text = '';
                startAddr = null;
            }
        }
        if (text.length >= CONFIG.min_text_length && isValidEnglishText(text) && startAddr) {
            results.push({ text, addr: startAddr });
        }
    } catch (e) { /* memory region not readable */ }
    return results;
}

// ============== العثور على module اللعبة ==============
function findGameModule() {
    const modules = Process.enumerateModules();
    // 1) ابحث عن اسم اللعبة الصريح
    for (const m of modules) {
        const n = m.name.toLowerCase();
        if (n.includes('manorlords-win64-shipping') ||
            n.includes('manorlords-wingrts-shipping')) {
            return m;
        }
    }
    // 2) أي -Shipping.exe
    for (const m of modules) {
        if (m.name.toLowerCase().includes('shipping.exe')) return m;
    }
    // 3) الـ main module
    return modules[0];
}

// ============== Scan كامل ==============
function fullScan() {
    STATE.stats.scans++;
    const t0 = Date.now();
    let newTextsFound = 0;

    const ranges = Process.enumerateRanges('rw-');
    let totalScanned = 0;

    for (const range of ranges) {
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

                        // أرسل للـ Python فوراً
                        if (CONFIG.send_new_texts_to_python) {
                            send({
                                type: 'text_found',
                                text: r.text,
                                address: r.addr.toString(),
                            });
                        }
                    } else {
                        // حدّث الـ last_seen + الـ addr (قد يتغير)
                        const item = STATE.texts.get(r.text);
                        item.last_seen = Date.now();
                        item.addr = r.addr;   // أحدث عنوان
                    }
                    totalScanned += sz;
                }
            } catch (e) { /* skip */ }
        }
    }

    const elapsed = Date.now() - t0;
    send({
        type: 'scan_complete',
        message: `[v2] scan #${STATE.stats.scans} في ${elapsed}ms — ${newTextsFound} نص جديد (إجمالي ${STATE.texts.size})`,
        new_texts: newTextsFound,
        total_texts: STATE.texts.size,
        elapsed_ms: elapsed,
    });

    // طبّق الترجمات المتوفّرة (للنصوص الجديدة وللعناوين المُحدَّثة)
    applyTranslations();
}

// ============== استبدال النصوص ==============
function applyTranslations() {
    let count = 0;
    let failures = 0;

    for (const [text, item] of STATE.texts) {
        const ar = STATE.cache[text];
        if (!ar) continue;

        try {
            // قاعدة الأمان: محدود بحجم النص الأصلي (UTF-16 = chars * 2 + null)
            const maxBytes = (text.length + 1) * 2;
            const arBytes = (ar.length + 1) * 2;
            const writeBytes = Math.min(arBytes, maxBytes);

            // اكتب presentation forms أو raw (Python يقرّر)
            // نستخدم writeUtf16String — يكتب مع null terminator
            if (arBytes <= maxBytes) {
                item.addr.writeUtf16String(ar);
            } else {
                // الـ Arabic أطول — نقصّ + null
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
            message: `[v2] استبدل ${count} نص (${failures} فشل)`,
            count, failures,
        });
    }
}

// ============== استلام رسائل من Python ==============
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
        send({ type: 'log', message: `[v2] استلم ${added} ترجمة جديدة (إجمالي cache: ${Object.keys(STATE.cache).length})` });
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
    send({ type: 'log', message: '[v2] متوقّف' });
});

// ============== RPC للاستعلامات المتزامنة ==============
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
        // batch sync — مثل recv('translations_batch') لكن sync
        if (data && data.translations) {
            for (const key of Object.keys(data.translations)) {
                STATE.cache[key] = data.translations[key];
            }
            applyTranslations();
        }
        return Object.keys(STATE.cache).length;
    },
    listrecent: (limit) => {
        // أعد آخر N نصوص (للتشخيص)
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
};

// ============== التهيئة ==============
try {
    STATE.gameModule = findGameModule();
    send({
        type: 'log',
        message: `[v2] module: ${STATE.gameModule.name} | size: ${(STATE.gameModule.size / 1024 / 1024).toFixed(1)} MB`,
    });

    // scan أوّلي
    fullScan();

    // ابدأ الـ periodic scan
    STATE.scanIntervalId = setInterval(() => {
        try {
            fullScan();
        } catch (e) {
            send({ type: 'error', message: '[v2] scan خطأ: ' + e });
        }
    }, CONFIG.scan_interval_ms);

    STATE.ready = true;
    send({
        type: 'ready',
        message: `[v2] جاهز! scan أوّلي وجد ${STATE.texts.size} نص. سيُعاد كل ${CONFIG.scan_interval_ms / 1000} ث.`,
    });
} catch (error) {
    send({ type: 'error', message: '[v2] init خطأ: ' + error });
}
