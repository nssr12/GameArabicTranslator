--[[
  UE4 Arabic Translator — Lua mod for UE4SS

  المعمارية:
    1) يحمّل dict/translations.txt مرة واحدة عند البدء (في الذاكرة)
    2) يهوك UFunctions النصوص (TextBlock:SetText إلخ.)
    3) عند كل دعوة: يبحث في dict — لو موجود يستبدل، لو لا يسجّل في missing.txt

  ✨ صفر lag:
    - lookup في hash table = O(1)
    - لا قرص I/O في حلقة العرض
    - missing.txt يُكتب batched كل 5 ثوانٍ بـ async coroutine

  ⚙ التفعيل: ضع هذا المجلد كاملاً في:
       <Game>/Binaries/Win64/Mods/UE4ArabicTranslator/
     وأضف لـ Mods/mods.txt:
       UE4ArabicTranslator : 1
--]]

-- ========== الإعدادات ==========
local CONFIG = {
    enable_explore = false,    -- لو true: يُحمَّل explore.lua لاستكشاف الـ hooks
    log_replacements = false,  -- لو true: يطبع كل استبدال (للديباغ)
    missing_flush_sec = 5.0,   -- كم ثانية بين كل دفعة كتابة لـ missing.txt
    -- مسار الـ mod (تلقائي إذا اللعبة وضعتنا في Mods/UE4ArabicTranslator/Scripts/)
    -- نستخدم os.getenv أو path relative
}

-- ========== الذاكرة ==========
local TRANSLATIONS = {}     -- map: english_text -> arabic_text
local MISSING_PENDING = {}  -- queue: نصوص جديدة لم نجد لها ترجمة
local MISSING_SEEN = {}     -- set: لتجنّب تكرار نفس النص في missing.txt
local STATS = {
    hits = 0,        -- نصوص ترجمت من dict
    misses = 0,      -- نصوص جديدة (سُجِّلت في missing)
    calls = 0,       -- إجمالي دعوات SetText
}

-- ========== مسارات الملفات ==========
-- UE4SS يضع الـ working dir في Binaries/Win64/, الـ mod في Mods/<ModName>/Scripts/
-- نستخدم مسارات نسبية للوصول لـ dict/
local DICT_PATH    = "Mods/UE4ArabicTranslator/dict/translations.txt"
local MISSING_PATH = "Mods/UE4ArabicTranslator/dict/missing.txt"

-- ========== تحميل القاموس ==========
local function load_dict()
    local f = io.open(DICT_PATH, "r")
    if not f then
        print("[ArabicTranslator] dict/translations.txt غير موجود — لا ترجمات محمّلة")
        return 0
    end
    local count = 0
    for line in f:lines() do
        -- صيغة: english=arabic
        -- نتجاهل أسطر التعليق (#) والفارغة
        if #line > 0 and line:sub(1, 1) ~= "#" then
            -- ابحث عن أول = غير مسبوق بـ \
            local eq_pos = nil
            local i = 1
            while i <= #line do
                local c = line:sub(i, i)
                if c == "=" and (i == 1 or line:sub(i - 1, i - 1) ~= "\\") then
                    eq_pos = i
                    break
                end
                i = i + 1
            end
            if eq_pos and eq_pos > 1 then
                local key = line:sub(1, eq_pos - 1):gsub("\\=", "="):gsub("\\n", "\n")
                local val = line:sub(eq_pos + 1):gsub("\\n", "\n")
                if #key > 0 and #val > 0 then
                    TRANSLATIONS[key] = val
                    count = count + 1
                end
            end
        end
    end
    f:close()
    return count
end

-- ========== كتابة missing.txt (batched) ==========
local function flush_missing()
    if #MISSING_PENDING == 0 then return end
    local f = io.open(MISSING_PATH, "a")
    if not f then
        -- نُبقي القائمة في الذاكرة، نحاول لاحقاً
        return
    end
    for _, txt in ipairs(MISSING_PENDING) do
        -- تخزين كـ key= (بدون قيمة) لينسجم مع صيغة translations.txt
        local safe = txt:gsub("=", "\\="):gsub("\n", "\\n")
        f:write(safe .. "=\n")
    end
    f:close()
    MISSING_PENDING = {}
end

-- ========== استخراج النص من FText/FString ==========
local function get_text_string(param)
    if param == nil then return nil end
    local t = type(param)
    if t == "string" then return param end
    if t ~= "userdata" then return nil end

    local ok, s = pcall(function()
        local pt = param:type()
        if pt == "FText" or pt == "TextProperty" then
            return param:ToString()
        elseif pt == "FString" or pt == "StrProperty" then
            return param:ToString()
        end
        -- محاولة عامة
        if param.ToString then return param:ToString() end
        return nil
    end)
    if ok and s and type(s) == "string" then return s end
    return nil
end

-- ========== كتابة النص الجديد على FText/FString ==========
local function set_text_string(param, new_value)
    if param == nil or new_value == nil then return false end
    if type(param) ~= "userdata" then return false end

    local ok = pcall(function()
        -- معظم wrappers في UE4SS تدعم :set() أو إنشاء FText جديد
        local pt = param:type()
        if pt == "FText" or pt == "TextProperty" then
            -- FText:Set أو :SetText
            if param.set then
                param:set(new_value)
            elseif param.SetText then
                param:SetText(new_value)
            end
        elseif pt == "FString" or pt == "StrProperty" then
            if param.set then param:set(new_value) end
        end
    end)
    return ok
end

-- ========== Hook callback عام ==========
-- يُستدعى عند كل دعوة SetText. الـ params الفعلية تختلف حسب الدالة.
local function make_text_replacer(hook_name)
    return function(self, ...)
        STATS.calls = STATS.calls + 1
        local args = {...}
        for i, a in ipairs(args) do
            local txt = get_text_string(a)
            if txt and #txt > 0 then
                local arabic = TRANSLATIONS[txt]
                if arabic then
                    -- استبدل بالعربي
                    if set_text_string(a, arabic) then
                        STATS.hits = STATS.hits + 1
                        if CONFIG.log_replacements then
                            print(string.format(
                                "[ArabicTr] %s | %s → %s",
                                hook_name, txt:sub(1, 30), arabic:sub(1, 30)
                            ))
                        end
                    end
                else
                    -- جديد — سجّل في missing
                    if not MISSING_SEEN[txt] and #txt >= 3 and #txt <= 2000 then
                        MISSING_SEEN[txt] = true
                        table.insert(MISSING_PENDING, txt)
                        STATS.misses = STATS.misses + 1
                    end
                end
                break   -- نتعامل مع أول معامل نصّي فقط
            end
        end
    end
end

-- ========== تركيب الـ hooks ==========
-- ⚠ هذه القائمة الافتراضية. تُحدَّث بعد تشغيل explore.lua على اللعبة الفعلية
-- وفحص ue4ss_arabic_logs/explore_log.txt لمعرفة الـ UFunctions الفعلية.
local HOOK_TARGETS = {
    "/Script/UMG.TextBlock:SetText",
    "/Script/UMG.MultiLineEditableText:SetText",
    "/Script/UMG.MultiLineEditableTextBox:SetText",
    "/Script/UMG.EditableText:SetText",
    "/Script/UMG.EditableTextBox:SetText",
    "/Script/UMG.RichTextBlock:SetText",
}

local function install_hooks()
    local ok_count = 0
    for _, fn_name in ipairs(HOOK_TARGETS) do
        local ok, err = pcall(function()
            RegisterHook(fn_name, make_text_replacer(fn_name))
            ok_count = ok_count + 1
        end)
        if not ok then
            print("[ArabicTr] WARN: hook فشل لـ " .. fn_name .. " — " .. tostring(err))
        end
    end
    print(string.format("[ArabicTr] hooks مُركَّبة: %d/%d", ok_count, #HOOK_TARGETS))
end

-- ========== Async loop لـ flush + إحصاءات ==========
local function start_flush_loop()
    LoopAsync(math.floor(CONFIG.missing_flush_sec * 1000), function()
        flush_missing()
        if STATS.calls > 0 then
            print(string.format(
                "[ArabicTr] stats: calls=%d  hits=%d  misses=%d  dict=%d",
                STATS.calls, STATS.hits, STATS.misses, #MISSING_PENDING + table.maxn(MISSING_SEEN or {})
            ))
        end
        return false   -- استمر
    end)
end

-- ========== التهيئة ==========
print("[ArabicTr] UE4 Arabic Translator starting...")
local dict_size = load_dict()
print(string.format("[ArabicTr] dict تحميل: %d ترجمة", dict_size))

install_hooks()
start_flush_loop()

-- لو استكشاف مُفعَّل، حمّل explore.lua أيضاً
if CONFIG.enable_explore then
    local ok, mod = pcall(require, "explore")
    if ok and mod and mod.install_hooks then
        mod.install_hooks()
        print("[ArabicTr] explore.lua مُحمَّل — log سيُكتب في ue4ss_arabic_logs/")
    end
end

print("[ArabicTr] جاهز ✓")
