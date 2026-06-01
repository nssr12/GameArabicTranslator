using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace I2LanguageInjector
{
    /// <summary>
    /// يحقن ترجمات عربية في I2.Loc.LocalizationManager وقت التشغيل.
    ///
    /// الإستخدام:
    ///   1. ضع arabic_only.json (مولّد من GUI) في:
    ///      <game>/BepInEx/config/I2LanguageInjector/arabic_only.json
    ///   2. شغّل اللعبة — المود يضيف لغة "Arabic" تلقائياً ويبدّل إليها
    ///   3. ArabicFontFixer.dll يكمل العمل بتشكيل الحروف وعكسها بصرياً
    ///
    /// لا نحتاج reference لـ Assembly-CSharp.dll — كل العمل عبر reflection
    /// لتجنّب كسر المود عند تحديث اللعبة.
    /// </summary>
    [BepInPlugin("com.arabicgametranslator.i2injector", "I2 Language Injector", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log;
        internal static Dictionary<string, string> Translations = new Dictionary<string, string>();
        internal static bool Injected = false;
        internal static bool SwitchScheduled = false;

        // I2 types — مُكتشَفة وقت التشغيل
        internal static Type T_LocalizationManager;   // I2.Loc.LocalizationManager
        internal static Type T_LanguageSource;        // I2.Loc.LanguageSourceData  (Unity 2018+)
        internal static Type T_TermData;              // I2.Loc.TermData
        internal static Type T_eTermType;             // I2.Loc.eTermType

        internal static ConfigEntry<string> CfgLanguageName;
        internal static ConfigEntry<string> CfgLanguageCode;
        internal static ConfigEntry<bool>   CfgAutoSwitch;
        internal static ConfigEntry<bool>   CfgVerbose;

        private void Awake()
        {
            Log = Logger;
            CfgLanguageName = Config.Bind("General", "LanguageName", "Arabic",
                "اسم اللغة المعروض في إعدادات اللعبة");
            CfgLanguageCode = Config.Bind("General", "LanguageCode", "ar",
                "كود اللغة (ISO 639-1)");
            CfgAutoSwitch = Config.Bind("General", "AutoSwitchToArabic", true,
                "بدّل اللغة الحالية إلى العربية تلقائياً عند بدء اللعبة");
            CfgVerbose = Config.Bind("Diagnostics", "Verbose", false,
                "اطبع تفاصيل أكثر في log (للتشخيص فقط)");

            try
            {
                LoadTranslationsFromConfig();
            }
            catch (Exception e)
            {
                Log.LogError("فشل تحميل arabic_only.json: " + e);
            }

            if (Translations.Count == 0)
            {
                Log.LogWarning("لا توجد ترجمات للحقن — تأكد من وجود arabic_only.json");
                return;
            }

            try
            {
                var harmony = new Harmony("com.arabicgametranslator.i2injector");
                harmony.PatchAll(typeof(Plugin).Assembly);
                Log.LogInfo($"تم تركيب Harmony patches — {Translations.Count} ترجمة جاهزة");
            }
            catch (Exception e)
            {
                Log.LogError("فشل Harmony.PatchAll: " + e);
            }
        }

        private void LoadTranslationsFromConfig()
        {
            string cfgDir = Path.Combine(Paths.ConfigPath, "I2LanguageInjector");
            string path = Path.Combine(cfgDir, "arabic_only.json");
            if (!File.Exists(path))
            {
                Log.LogWarning($"الملف غير موجود: {path}");
                Directory.CreateDirectory(cfgDir);
                return;
            }
            string raw = File.ReadAllText(path);
            Translations = MiniJson.Parse(raw);
            Log.LogInfo($"حُمِّل {Translations.Count} ترجمة من: {path}");
        }

        // ── يستخدمه Harmony patches للوصول للأنواع ──────────────────────────

        internal static void EnsureTypesResolved()
        {
            if (T_LocalizationManager != null)
                return;
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    Type tlm = asm.GetType("I2.Loc.LocalizationManager", false);
                    if (tlm != null) { T_LocalizationManager = tlm; }

                    Type tls = asm.GetType("I2.Loc.LanguageSourceData", false);
                    if (tls != null) { T_LanguageSource = tls; }

                    Type ttd = asm.GetType("I2.Loc.TermData", false);
                    if (ttd != null) { T_TermData = ttd; }

                    Type tet = asm.GetType("I2.Loc.eTermType", false);
                    if (tet != null) { T_eTermType = tet; }
                }
                catch { }
            }
            if (T_LocalizationManager == null && CfgVerbose != null && CfgVerbose.Value)
                Log.LogWarning("لم يُعثَر على I2.Loc.LocalizationManager بعد");
        }

        internal static int ArabicLanguageIndexFor(object source)
        {
            try
            {
                var mLangs = source.GetType().GetField("mLanguages",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (mLangs == null) return -1;
                var arr = mLangs.GetValue(source) as System.Collections.IList;
                if (arr == null) return -1;
                string code = CfgLanguageCode?.Value ?? "ar";
                string name = CfgLanguageName?.Value ?? "Arabic";
                for (int i = 0; i < arr.Count; i++)
                {
                    object lang = arr[i];
                    if (lang == null) continue;
                    string lCode = lang.GetType().GetField("Code",
                        BindingFlags.Instance | BindingFlags.Public)?.GetValue(lang) as string ?? "";
                    string lName = lang.GetType().GetField("Name",
                        BindingFlags.Instance | BindingFlags.Public)?.GetValue(lang) as string ?? "";
                    if (string.Equals(lCode, code, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(lName, name, StringComparison.OrdinalIgnoreCase))
                        return i;
                }
            }
            catch { }
            return -1;
        }

        /// <summary>
        /// يضيف فتحة "Arabic" داخل كل LanguageSourceData موجود + يحقن الترجمات.
        /// idempotent (آمن للاستدعاء مرات).
        /// </summary>
        internal static void TryInjectIntoAllSources()
        {
            EnsureTypesResolved();
            if (T_LocalizationManager == null) return;

            try
            {
                var sourcesField = T_LocalizationManager.GetField("Sources",
                    BindingFlags.Public | BindingFlags.Static);
                if (sourcesField == null) return;
                var sources = sourcesField.GetValue(null) as System.Collections.IList;
                if (sources == null || sources.Count == 0) return;

                int totalInjected = 0;
                foreach (object src in sources)
                {
                    if (src == null) continue;
                    totalInjected += InjectIntoSource(src);
                }

                if (totalInjected > 0)
                {
                    Injected = true;
                    Log.LogInfo($"حُقنت {totalInjected} ترجمة عربية في {sources.Count} LanguageSource");
                }
            }
            catch (Exception e)
            {
                Log.LogError("TryInjectIntoAllSources: " + e);
            }
        }

        private static int InjectIntoSource(object source)
        {
            try
            {
                int arabicIdx = ArabicLanguageIndexFor(source);

                // أضِف "Arabic" لو غير موجود
                if (arabicIdx < 0)
                {
                    arabicIdx = AddArabicLanguageTo(source);
                    if (arabicIdx < 0) return 0;
                }

                // اعثر على mTerms
                var mTermsField = source.GetType().GetField("mTerms",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (mTermsField == null) return 0;
                var terms = mTermsField.GetValue(source) as System.Collections.IList;
                if (terms == null) return 0;

                int injected = 0;
                foreach (object term in terms)
                {
                    if (term == null) continue;
                    string termId = term.GetType().GetField("Term",
                        BindingFlags.Instance | BindingFlags.Public)?.GetValue(term) as string;
                    if (string.IsNullOrEmpty(termId)) continue;
                    if (!Translations.TryGetValue(termId, out string arabic) || string.IsNullOrEmpty(arabic))
                        continue;

                    var langsField = term.GetType().GetField("Languages",
                        BindingFlags.Instance | BindingFlags.Public);
                    if (langsField == null) continue;
                    var langsArr = langsField.GetValue(term) as string[];
                    if (langsArr == null) continue;

                    // مدّد المصفوفة إذا اللغة العربية فهرس أكبر من طولها
                    if (arabicIdx >= langsArr.Length)
                    {
                        var newArr = new string[arabicIdx + 1];
                        Array.Copy(langsArr, newArr, langsArr.Length);
                        for (int k = langsArr.Length; k < newArr.Length; k++)
                            newArr[k] = "";
                        langsArr = newArr;
                        langsField.SetValue(term, langsArr);
                    }
                    langsArr[arabicIdx] = arabic;
                    injected++;
                }

                // Mark cache dirty
                var updateMethod = source.GetType().GetMethod("UpdateDictionary",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (updateMethod != null)
                {
                    try { updateMethod.Invoke(source, null); } catch { }
                }
                return injected;
            }
            catch (Exception e)
            {
                Log.LogError("InjectIntoSource: " + e);
                return 0;
            }
        }

        private static int AddArabicLanguageTo(object source)
        {
            try
            {
                Type tLang = null;
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    Type t = asm.GetType("I2.Loc.LanguageData", false);
                    if (t != null) { tLang = t; break; }
                }
                if (tLang == null) return -1;

                var newLang = Activator.CreateInstance(tLang);
                tLang.GetField("Name",  BindingFlags.Instance | BindingFlags.Public)?
                    .SetValue(newLang, CfgLanguageName.Value);
                tLang.GetField("Code",  BindingFlags.Instance | BindingFlags.Public)?
                    .SetValue(newLang, CfgLanguageCode.Value);
                // Flags field exists in I2 but isn't critical — افتراضي 0

                var mLangs = source.GetType().GetField("mLanguages",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (mLangs == null) return -1;
                var arr = mLangs.GetValue(source) as System.Collections.IList;
                if (arr == null) return -1;
                arr.Add(newLang);
                return arr.Count - 1;
            }
            catch (Exception e)
            {
                Log.LogError("AddArabicLanguageTo: " + e);
                return -1;
            }
        }

        internal static void TrySwitchToArabic()
        {
            if (!CfgAutoSwitch.Value) return;
            EnsureTypesResolved();
            if (T_LocalizationManager == null) return;

            try
            {
                var currentLangProp = T_LocalizationManager.GetProperty("CurrentLanguage",
                    BindingFlags.Public | BindingFlags.Static);
                if (currentLangProp == null) return;
                string current = currentLangProp.GetValue(null, null) as string ?? "";
                if (string.Equals(current, CfgLanguageName.Value, StringComparison.OrdinalIgnoreCase))
                    return;
                currentLangProp.SetValue(null, CfgLanguageName.Value, null);
                Log.LogInfo($"بُدّلت اللغة من '{current}' إلى '{CfgLanguageName.Value}'");
                SwitchScheduled = false;
            }
            catch (Exception e)
            {
                Log.LogError("TrySwitchToArabic: " + e);
            }
        }
    }

    // ── Harmony patches ─────────────────────────────────────────────────────

    /// <summary>
    /// نلتقط أي استدعاء لـ LocalizationManager.GetTranslation ونحقن قبله.
    /// هذا يضمن أن الترجمات تظهر حتى لو AddSource تأخّر.
    /// </summary>
    [HarmonyPatch]
    public static class Patch_LM_OnLocalize
    {
        static MethodBase TargetMethod()
        {
            Plugin.EnsureTypesResolved();
            if (Plugin.T_LocalizationManager == null) return null;
            // العديد من الإصدارات لها OnLocalize أو LocalizeAll
            var m = Plugin.T_LocalizationManager.GetMethod("LocalizeAll",
                BindingFlags.Public | BindingFlags.Static);
            if (m == null)
            {
                m = Plugin.T_LocalizationManager.GetMethod("UpdateSources",
                    BindingFlags.NonPublic | BindingFlags.Static);
            }
            return m;
        }

        static void Postfix()
        {
            if (Plugin.Translations.Count == 0) return;
            Plugin.TryInjectIntoAllSources();
            if (!Plugin.SwitchScheduled)
            {
                Plugin.SwitchScheduled = true;
                Plugin.TrySwitchToArabic();
            }
        }
    }

    /// <summary>
    /// تطبيق مزدوج: postfix على GetTranslation للحماية لو AddSource لم يُلتقط.
    /// </summary>
    [HarmonyPatch]
    public static class Patch_LM_GetTranslation
    {
        static MethodBase TargetMethod()
        {
            Plugin.EnsureTypesResolved();
            if (Plugin.T_LocalizationManager == null) return null;
            // GetTranslation(string Term, bool FixForRTL = true, int maxLineLengthForRTL = 0, ...)
            // التواقيع تختلف — نأخذ أول overload static
            var methods = Plugin.T_LocalizationManager.GetMethods(
                BindingFlags.Public | BindingFlags.Static)
                .Where(m => m.Name == "GetTranslation")
                .OrderByDescending(m => m.GetParameters().Length)
                .ToArray();
            return methods.FirstOrDefault();
        }

        static void Postfix(string Term, ref string __result)
        {
            if (string.IsNullOrEmpty(__result) || string.IsNullOrEmpty(Term))
                return;
            if (Plugin.Translations.Count == 0) return;
            // فقط إذا اللغة الحالية عربية
            try
            {
                var currentLangProp = Plugin.T_LocalizationManager?.GetProperty("CurrentLanguage",
                    BindingFlags.Public | BindingFlags.Static);
                if (currentLangProp == null) return;
                string cur = currentLangProp.GetValue(null, null) as string ?? "";
                if (!string.Equals(cur, Plugin.CfgLanguageName.Value, StringComparison.OrdinalIgnoreCase))
                    return;
                if (Plugin.Translations.TryGetValue(Term, out string ar) && !string.IsNullOrEmpty(ar))
                {
                    __result = ar;
                }
            }
            catch { }
        }
    }

    // ── MiniJson — مفسّر JSON بسيط لتجنّب اعتمادية على Newtonsoft ──────────

    internal static class MiniJson
    {
        public static Dictionary<string, string> Parse(string json)
        {
            var d = new Dictionary<string, string>();
            if (string.IsNullOrEmpty(json)) return d;
            int i = 0;
            SkipWs(json, ref i);
            if (i >= json.Length || json[i] != '{') return d;
            i++;
            while (i < json.Length)
            {
                SkipWs(json, ref i);
                if (i >= json.Length) break;
                if (json[i] == '}') { i++; break; }
                if (json[i] != '"') { i++; continue; }
                string key = ReadString(json, ref i);
                SkipWs(json, ref i);
                if (i >= json.Length || json[i] != ':') break;
                i++;
                SkipWs(json, ref i);
                if (i >= json.Length || json[i] != '"') break;
                string val = ReadString(json, ref i);
                d[key] = val;
                SkipWs(json, ref i);
                if (i < json.Length && json[i] == ',') i++;
            }
            return d;
        }

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) i++;
        }

        private static string ReadString(string s, ref int i)
        {
            // assumes s[i] == '"'
            i++;
            var sb = new System.Text.StringBuilder();
            while (i < s.Length)
            {
                char c = s[i];
                if (c == '"') { i++; break; }
                if (c == '\\' && i + 1 < s.Length)
                {
                    char n = s[i + 1];
                    switch (n)
                    {
                        case '"':  sb.Append('"');  i += 2; break;
                        case '\\': sb.Append('\\'); i += 2; break;
                        case '/':  sb.Append('/');  i += 2; break;
                        case 'b':  sb.Append('\b'); i += 2; break;
                        case 'f':  sb.Append('\f'); i += 2; break;
                        case 'n':  sb.Append('\n'); i += 2; break;
                        case 'r':  sb.Append('\r'); i += 2; break;
                        case 't':  sb.Append('\t'); i += 2; break;
                        case 'u':
                            if (i + 5 < s.Length)
                            {
                                string hex = s.Substring(i + 2, 4);
                                if (int.TryParse(hex, System.Globalization.NumberStyles.HexNumber,
                                                 System.Globalization.CultureInfo.InvariantCulture,
                                                 out int code))
                                {
                                    sb.Append((char)code);
                                }
                                i += 6;
                            }
                            else i += 2;
                            break;
                        default: sb.Append(n); i += 2; break;
                    }
                    continue;
                }
                sb.Append(c);
                i++;
            }
            return sb.ToString();
        }
    }
}
