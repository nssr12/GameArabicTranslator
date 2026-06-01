--[[
  explore.lua — يستكشف ما هي UFunctions الـ text المُستَخدَمة في اللعبة.

  الغرض: تشغيل اللعبة مع هذا المود، التنقّل بين كل الشاشات (قائمة، إعدادات، dialogue، إلخ)،
  ثم فحص ملف log/explore_log.txt لرؤية الـ UFunctions الفعلية للنصوص.

  بعد الاستكشاف، نُلغي تحميل هذا الملف ونعتمد على main.lua مع الـ hooks الصحيحة.

  ⚠ هذا الملف للاستكشاف فقط — مشغّل: عبر main.lua لو ENABLE_EXPLORE=true
--]]

local M = {}

local LOG_DIR = "ue4ss_arabic_logs"
local LOG_PATH = LOG_DIR .. "/explore_log.txt"
local seen_signatures = {}   -- لتجنّب التكرار في الـ log
local log_count = 0

-- إنشاء مجلد الـ log
local function ensure_log_dir()
    -- UE4SS Lua لا يدعم mkdir مباشرة — نحاول الكتابة، لو فشلت نُهمل
    local f = io.open(LOG_PATH, "a")
    if f then
        f:close()
        return true
    end
    return false
end

-- كتابة سطر للـ log (batched في الذاكرة قبل الكتابة)
local log_buffer = {}
local LOG_FLUSH_EVERY = 20

local function log_write(line)
    table.insert(log_buffer, line)
    if #log_buffer >= LOG_FLUSH_EVERY then
        M.flush()
    end
end

function M.flush()
    if #log_buffer == 0 then return end
    local f = io.open(LOG_PATH, "a")
    if f then
        for _, line in ipairs(log_buffer) do
            f:write(line .. "\n")
        end
        f:close()
    end
    log_buffer = {}
end

-- تسجيل دعوة UFunction (مرة واحدة فقط لكل توقيع)
local function log_call(func_name, sample_text)
    local key = func_name .. "|" .. tostring(sample_text or ""):sub(1, 40)
    if seen_signatures[key] then return end
    seen_signatures[key] = true
    log_count = log_count + 1
    local line = string.format(
        "[%d] %s | text=%q",
        log_count, func_name, tostring(sample_text or "<nil>"):sub(1, 100)
    )
    log_write(line)
end

-- محاولة استخراج النص من معاملات Hook
-- UE4SS callbacks: (self, param1, param2, ...)
-- لـ SetText: عادة (self, FText InText)
local function extract_text(param)
    if param == nil then return nil end
    local ok, str = pcall(function()
        -- FText و FString لهما طريقة :ToString أو :type
        if type(param) == "userdata" then
            local pt = param:type()
            if pt == "FText" or pt == "TextProperty" then
                return param:ToString()
            elseif pt == "FString" or pt == "StrProperty" then
                return param:ToString()
            elseif pt == "FName" or pt == "NameProperty" then
                return param:ToString()
            end
            -- محاولة عامة
            if param.ToString then return param:ToString() end
        elseif type(param) == "string" then
            return param
        end
        return nil
    end)
    if ok then return str end
    return nil
end

-- قائمة الـ UFunctions المعروفة لعرض النصوص في UE
local HOOKS_TO_TRY = {
    -- UMG Widgets
    "/Script/UMG.TextBlock:SetText",
    "/Script/UMG.MultiLineEditableText:SetText",
    "/Script/UMG.MultiLineEditableTextBox:SetText",
    "/Script/UMG.EditableText:SetText",
    "/Script/UMG.EditableTextBox:SetText",
    "/Script/UMG.RichTextBlock:SetText",
    "/Script/UMG.Button:OnClicked",  -- لاختبار
    -- Slate (لو فيه)
    "/Script/SlateCore.STextBlock:SetText",
}

function M.install_hooks()
    if not ensure_log_dir() then
        print("[ArabicExplore] WARN: تعذّر فتح log file — سيُسجَّل للـ console فقط")
    end
    log_write("=== ArabicExplore session started ===")
    log_write("Time: " .. os.date("%Y-%m-%d %H:%M:%S"))
    log_write("Hooks to install: " .. #HOOKS_TO_TRY)
    log_write("")

    local installed = 0
    for _, fn_name in ipairs(HOOKS_TO_TRY) do
        local ok, err = pcall(function()
            RegisterHook(fn_name, function(self, ...)
                local args = {...}
                local txt = nil
                for i, a in ipairs(args) do
                    txt = extract_text(a)
                    if txt and #txt > 0 then break end
                end
                log_call(fn_name, txt)
            end)
            installed = installed + 1
            log_write("[hook] ✓ " .. fn_name)
        end)
        if not ok then
            log_write("[hook] ✗ " .. fn_name .. " — " .. tostring(err))
        end
    end

    print("[ArabicExplore] Installed " .. installed .. "/" .. #HOOKS_TO_TRY .. " hooks")
    M.flush()
end

-- اطبع الإحصاءات كل دقيقة + flush
LoopAsync(60000, function()
    M.flush()
    print(string.format(
        "[ArabicExplore] %d unique text signatures logged so far → %s",
        log_count, LOG_PATH
    ))
    return false   -- استمر بالـ loop
end)

return M
