using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using BepInEx;
using HarmonyLib;
using TMPro;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;

namespace ArabicGameTranslator
{
    [BepInPlugin("com.arabicgametranslator.fontfixer", "Arabic Font Fixer", "3.1.8")]
    public class ArabicFontFixer : BaseUnityPlugin
    {
        private static readonly string[] OsFontNames = { "Tahoma", "Arial", "Segoe UI" };
        private const string ProxyUrl       = "http://127.0.0.1:5001/";
        private const int    PriorityMaxLen = 150;
        private const int    NormalChunkSize = 5;

        // static — تبقى محفوظة حتى لو MonoBehaviour دُمِّر
        private static Font          _osFont;
        private static TMP_FontAsset _tmpFallback;
        internal static bool         _applied;

        private static readonly Dictionary<string, string> _staticTr =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private static readonly HashSet<string> _pendingSet    = new HashSet<string>(StringComparer.Ordinal);
        private static readonly Queue<string>   _priorityQueue = new Queue<string>();
        private static readonly HashSet<string> _prioritySet   = new HashSet<string>(StringComparer.Ordinal);
        private static readonly object          _pendingLock   = new object();
        private static Thread _worker;

        private static volatile bool _newTranslationsAvailable = false;

        private static readonly Dictionary<int, TextAlignmentOptions> _origTmpAlign = new Dictionary<int, TextAlignmentOptions>();
        private static readonly Dictionary<int, TextAnchor>           _origUiAlign  = new Dictionary<int, TextAnchor>();

        // Logger مكشوف للـ FontFixerRuntime
        internal BepInEx.Logging.ManualLogSource Log => Logger;

        // Logger ثابت — يستخدمه الـ hooks بعدما اللعبة تدمّر MonoBehaviour
        // (مرجع C# نقي، لا يتأثر بـ Unity "fake null" حتى لو GameObject مدمَّر)
        internal static BepInEx.Logging.ManualLogSource StaticLog;

        // direct file logging — يتجاوز أي buffering في BepInEx logger
        private static string _diagPath;
        internal static void Diag(string msg)
        {
            try
            {
                if (_diagPath == null) return;
                File.AppendAllText(_diagPath, DateTime.Now.ToString("HH:mm:ss.fff") + " " + msg + "\n");
            }
            catch { }
        }

        // ملاحظة: FontFixerRuntime القديم أُزيل لأن اللعبة (Farthest Frontier) تدمّر
        // GameObject الخاص بنا بعد 2-3 ثوان، فلا Update ولا Start يعمل عليه.
        // الحل: كل العمل يتم في Harmony hooks (static) عبر EnsureFontFromHook().

        private void Awake()
        {
            Instance = this;
            StaticLog = Logger;   // نسخة static من Logger — تنجو من تدمير MonoBehaviour
            // diag file
            _diagPath = Path.Combine(Paths.BepInExRootPath ?? ".", "arabicfontfixer_diag.log");
            try { File.WriteAllText(_diagPath, "ArabicFontFixer v2.0 diag started " + DateTime.Now + "\n"); } catch { }
            Diag("Awake() begin");

            StaticLog?.LogInfo("[ArabicFontFixer] Starting v3.2.4 (tag-aware reverse + comma breaks)…");
            try { File.AppendAllText(_diagPath, "=== Starting v3.2.4 (tag-aware reverse + comma breaks) ===\n"); } catch { }
            LoadStaticTranslations();
            StartTranslationsWatcher();
            EnsureLiveReloadDriver();
            var harmony = new Harmony("com.arabicgametranslator.fontfixer");
            PatchTranslationHooks(harmony);

            Diag("Awake() done — all subsequent work happens in Harmony hooks (static).");
            StaticLog?.LogInfo("[ArabicFontFixer] Awake() done — hooks installed.");
        }

        // ── Live reload driver — GameObject مستقل مع DontDestroyOnLoad ───────
        // ضروري لأن BepInEx Plugin's Update() لا تشتغل في Farthest Frontier
        // (GameObject الـ Plugin يُدمَّر عند تغيير المشهد). الـ GameObject هذا
        // محمي بـ DontDestroyOnLoad → يظل حياً لكل عمر اللعبة، ويستدعي
        // ProcessReloadRequest كل frame.

        internal static GameObject _liveReloadGo;

        private static void EnsureLiveReloadDriver()
        {
            try
            {
                if (_liveReloadGo != null) return;
                _liveReloadGo = new GameObject("AFF_LiveReloadDriver");
                GameObject.DontDestroyOnLoad(_liveReloadGo);
                _liveReloadGo.hideFlags = HideFlags.HideAndDontSave;
                _liveReloadGo.AddComponent<LiveReloadDriver>();
                StaticLog?.LogInfo("[ArabicFontFixer] LiveReloadDriver mounted (DontDestroyOnLoad).");
            }
            catch (Exception ex)
            {
                StaticLog?.LogWarning("[ArabicFontFixer] EnsureLiveReloadDriver: " + ex.Message);
            }
        }

        // ── Static translations ───────────────────────────────────────────────

        // مطابقة تطبيع نص الـ proxy تماماً:
        //   text_key = " ".join(text.replace("\\n", " ").replace("\n", " ").split())
        // Python .split() بدون args يقسم بكل أنواع whitespace ويزيل الفراغات.
        // نطبّق نفس المنطق في C#: نستبدل "\\n" literal + كل whitespace → space ثم نضغط.
        internal static string NormalizeKey(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            // استبدل "\\n" literal (سلسلة من حرفين: backslash + n) بمسافة
            // — XUnity أحياناً يمرّر النص بهذه الصيغة
            string s = text.Replace("\\n", " ");
            // ابن StringBuilder يحوّل كل whitespace → space ويضغط المتعدّد
            var sb = new StringBuilder(s.Length);
            bool inSpace = false;
            bool any = false;
            foreach (var ch in s)
            {
                if (char.IsWhiteSpace(ch))
                {
                    if (any && !inSpace)
                    {
                        sb.Append(' ');
                        inSpace = true;
                    }
                }
                else
                {
                    sb.Append(ch);
                    inSpace = false;
                    any = true;
                }
            }
            // أزل أي مسافة لاحقة (لو النص انتهى بـ whitespace)
            int end = sb.Length;
            while (end > 0 && sb[end - 1] == ' ') end--;
            if (end != sb.Length) sb.Length = end;
            return sb.ToString();
        }

        // marker للنصوص غير القابلة للترجمة (AI يردّها كما هي، أسماء، إلخ).
        // الـ proxy يصدّرها من failed_translations كـ `key=__SKIP__` في translations.txt.
        // الـ DLL يحوّلها لـ self-key (`_staticTr[key] = key`) → Translate يعرف "لا ترجمة".
        private const string SKIP_MARKER = "__SKIP__";

        // يجد فاصل key=value الحقيقي (أول '=' غير مسبوق بـ '\').
        // مطابق لـ Python parser في engine/static_translations.py.
        // نصوص مثل "<color\=#FF0000>text=ترجمة" يجب أن تُقسَم عند '=' الثاني، ليس الأول.
        private static int FindKeyValueSeparator(string line)
        {
            for (int i = 0; i < line.Length; i++)
            {
                if (line[i] == '=' && (i == 0 || line[i - 1] != '\\'))
                    return i;
            }
            return -1;
        }

        // يخزّن الترجمة بمفتاحين (الأصلي + المُطبَّع) إن اختلفا. يُستدعى تحت _pendingLock.
        private static void StoreWithNormalizedKey(string key, string val)
        {
            // marker: حوّل __SKIP__ لـ self-key (نفس النص) — يعالجها Translate كـ "لا ترجمة"
            if (val == SKIP_MARKER) val = key;
            _staticTr[key] = val;
            var norm = NormalizeKey(key);
            if (!string.Equals(norm, key, StringComparison.Ordinal) && !_staticTr.ContainsKey(norm))
            {
                // للمفتاح المُطبَّع، نخزّن self-key المُطبَّع (وليس self-key الأصلي)
                _staticTr[norm] = (val == key) ? norm : val;
            }
        }

        private void LoadStaticTranslations()
        {
            var path = Path.Combine(Paths.ConfigPath, "ArabicGameTranslator", "translations.txt");
            if (!File.Exists(path))
            {
                StaticLog?.LogInfo("[ArabicFontFixer] No translations.txt — static translation disabled.");
                return;
            }
            try
            {
                var lines = File.ReadAllLines(path, Encoding.UTF8);
                int count = 0;
                foreach (var line in lines)
                {
                    if (string.IsNullOrEmpty(line) || line[0] == '#') continue;
                    var sep = FindKeyValueSeparator(line);
                    if (sep <= 0) continue;
                    var key = line.Substring(0, sep).Replace("\\=", "=").Replace("\\n", "\n");
                    var val = line.Substring(sep + 1).Replace("\\n", "\n");
                    if (key.Length > 0 && val.Length > 0) { StoreWithNormalizedKey(key, val); count++; }
                }
                StaticLog?.LogInfo($"[ArabicFontFixer] Loaded {count} static translations (total entries incl. normalized: {_staticTr.Count}).");
            }
            catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] LoadStaticTranslations: " + ex.Message); }
        }

        // ── Live reload عند تعديل translations.txt من خارج اللعبة ────────────
        // يراقب الملف عبر FileSystemWatcher. عند تغيّر mtime:
        //   1) يُعاد تحميل _staticTr (يحدّث/يضيف من غير حذف ما هو موجود — نسخة آمنة)
        //   2) يُستدعى ApplyToLiveText على Unity main thread → النصوص الظاهرة الآن تتحدّث

        private FileSystemWatcher _txtWatcher;
        private static volatile bool _reloadRequested = false;
        private static DateTime _lastReloadTime = DateTime.MinValue;

        private void StartTranslationsWatcher()
        {
            try
            {
                var dir = Path.Combine(Paths.ConfigPath, "ArabicGameTranslator");
                if (!Directory.Exists(dir))
                {
                    try { Directory.CreateDirectory(dir); } catch { }
                }
                _txtWatcher = new FileSystemWatcher(dir, "translations.txt")
                {
                    NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.Size | NotifyFilters.CreationTime,
                    EnableRaisingEvents = true,
                };
                FileSystemEventHandler handler = (s, e) =>
                {
                    // debounce: تجاهل أحداث متعدّدة خلال 800ms
                    var now = DateTime.UtcNow;
                    if ((now - _lastReloadTime).TotalMilliseconds < 800) return;
                    _lastReloadTime = now;
                    _reloadRequested = true;
                    Diag("translations.txt changed → reload scheduled");
                };
                _txtWatcher.Changed += handler;
                _txtWatcher.Created += handler;
                _txtWatcher.Renamed += (s, e) => { _reloadRequested = true; };
                StaticLog?.LogInfo("[ArabicFontFixer] Watching translations.txt for live reload.");
            }
            catch (Exception ex)
            {
                StaticLog?.LogWarning("[ArabicFontFixer] StartTranslationsWatcher: " + ex.Message);
            }
        }

        // يُستدعى كل frame من LiveReloadDriver (DontDestroyOnLoad).
        // ينفّذ الـ reload فقط لو الـ flag مرفوع → خفيف جداً في الحالة العادية.
        internal static void ProcessReloadRequest()
        {
            if (!_reloadRequested) return;
            _reloadRequested = false;
            try
            {
                var path = Path.Combine(Paths.ConfigPath, "ArabicGameTranslator", "translations.txt");
                if (!File.Exists(path)) return;

                // قراءة مع FileShare.ReadWrite + retry لتجنّب sharing violation
                // (الكاتب قد يكون لم يقفل بعد عند triggered الـ event)
                string[] lines = null;
                Exception lastEx = null;
                for (int attempt = 0; attempt < 5; attempt++)
                {
                    try
                    {
                        System.Threading.Thread.Sleep(150);
                        using (var fs = new FileStream(path, FileMode.Open,
                                                       FileAccess.Read, FileShare.ReadWrite))
                        using (var sr = new StreamReader(fs, Encoding.UTF8))
                        {
                            var content = sr.ReadToEnd();
                            lines = content.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
                        }
                        break;
                    }
                    catch (IOException ex) { lastEx = ex; }
                    catch (UnauthorizedAccessException ex) { lastEx = ex; }
                }
                if (lines == null)
                {
                    StaticLog?.LogWarning("[ArabicFontFixer] Reload failed after 5 retries: " +
                                          (lastEx?.Message ?? "unknown"));
                    return;
                }
                int added = 0, updated = 0;
                lock (_pendingLock)
                {
                    foreach (var line in lines)
                    {
                        if (string.IsNullOrEmpty(line) || line[0] == '#') continue;
                        var sep = FindKeyValueSeparator(line);
                        if (sep <= 0) continue;
                        var key = line.Substring(0, sep).Replace("\\=", "=").Replace("\\n", "\n");
                        var val = line.Substring(sep + 1).Replace("\\n", "\n");
                        if (key.Length == 0 || val.Length == 0) continue;
                        bool exists = _staticTr.TryGetValue(key, out var cur);
                        if (exists && cur == val) continue;
                        StoreWithNormalizedKey(key, val);
                        if (exists) updated++; else added++;
                    }
                }
                StaticLog?.LogInfo($"[ArabicFontFixer] Live reload: +{added} new, ~{updated} updated, total={_staticTr.Count}");
                try { ApplyToLiveText(); }
                catch (Exception e) { Diag("ApplyToLiveText after reload: " + e.Message); }
            }
            catch (Exception ex)
            {
                StaticLog?.LogWarning("[ArabicFontFixer] ProcessReloadRequest: " + ex.Message);
            }
        }

        // diag: يُستدعى من LiveReloadDriver كل ~10 ث لإثبات أن الـ driver حي
        private static int _heartbeatCount = 0;
        internal static void DriverHeartbeat()
        {
            _heartbeatCount++;
            if (_heartbeatCount == 1)
                Diag("LiveReloadDriver heartbeat #1 — driver is alive");
            else if (_heartbeatCount == 30)
                Diag("LiveReloadDriver heartbeat #30 (~5 min uptime)");
        }

        // Buffer مشترك لـ RTLSupport (يُعاد استخدامه لتقليل allocations)
        [ThreadStatic] private static RTLTMPro.FastStringBuilder _shapeIn;
        [ThreadStatic] private static RTLTMPro.FastStringBuilder _shapeOut;

        // يلتقط تاقات HTML/TMP (<...>) وكذلك مقاطع LTR (حروف لاتينية/أرقام)
        private static readonly Regex TagOrLtrRunRegex = new Regex(
            @"(<[^>]*>)|([A-Za-z0-9]+)",
            RegexOptions.Compiled
        );

        // التاقات فقط — للـ tag-aware reversal
        private static readonly Regex TagOnlyRegex = new Regex(
            @"<[^>]*>",
            RegexOptions.Compiled
        );

        // يقلب الأقواس () [] {} لتظهر بمواضعها الصحيحة بعد عكس TMP
        private static string SwapBracketsForRtl(string s)
        {
            var sb = new StringBuilder(s.Length);
            foreach (char ch in s)
            {
                switch (ch)
                {
                    case '(': sb.Append(')'); break;
                    case ')': sb.Append('('); break;
                    case '[': sb.Append(']'); break;
                    case ']': sb.Append('['); break;
                    case '{': sb.Append('}'); break;
                    case '}': sb.Append('{'); break;
                    default:  sb.Append(ch); break;
                }
            }
            return sb.ToString();
        }

        // ⭐ v3.1.5: نعكس النص بصرياً يدوياً (per-line) ونحافظ على LTR runs بترتيبها.
        // السبب: TMP في Farthest Frontier لا يعكس بشكل موثوق رغم isRTL=true (تولتيبات).
        // النهج:
        //   1. نُشكّل العربي (logical → presentation forms)
        //   2. نعكس كل سطر بصرياً (chars reversed within \n boundaries)
        //   3. نُعيد ترتيب LTR runs (إنجليزي/أرقام) بحيث تُقرأ LTR في الناتج
        //   4. نقلب الأقواس () [] {} (mirroring يدوي)
        //   5. isRTL = false (TMP يعرض الناتج كما هو)
        // التولتيبات الـ multi-line بـ \n explicit تظهر بترتيب سطور صحيح ✓
        // التولتيبات الـ auto-wrap قد تظهر بترتيب سطور معكوس (تنازل مقبول).
        private static bool IsLtrChar(char c)
        {
            return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
        }

        private static char MirrorBracket(char c)
        {
            switch (c)
            {
                case '(': return ')';
                case ')': return '(';
                case '[': return ']';
                case ']': return '[';
                case '{': return '}';
                case '}': return '{';
                default:  return c;
            }
        }

        // يعكس مقطع نصّي (بلا تاقات) بصرياً مع الحفاظ على اتجاه LTR runs ومرايا الأقواس
        private static string ReverseTextSegment(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            char[] chars = text.ToCharArray();
            Array.Reverse(chars);
            int i = 0;
            while (i < chars.Length)
            {
                if (IsLtrChar(chars[i]))
                {
                    int start = i;
                    while (i < chars.Length && IsLtrChar(chars[i])) i++;
                    if (i - start > 1) Array.Reverse(chars, start, i - start);
                }
                else i++;
            }
            for (int j = 0; j < chars.Length; j++)
                chars[j] = MirrorBracket(chars[j]);
            return new string(chars);
        }

        // يعكس سطراً واحداً مع وعي بالتاقات:
        //   - التاقات تبقى verbatim
        //   - أزواج (<X attrs>...</X>) تتبادل أدوارها بعد عكس ترتيب المقاطع
        //     (التاق الـ"مفتوح" الأصلي يُصبح في موضع الإغلاق فيكتب كإغلاق،
        //      والمغلق الأصلي يكتب في موضع الفتح بمحتوى الفتح + attributes)
        //   - النصوص بين/خارج التاقات تُعكس بصرياً (chars + LTR + brackets)
        private static string ReverseLineForVisualRtl(string line)
        {
            if (string.IsNullOrEmpty(line)) return line;
            var tagMatches = TagOnlyRegex.Matches(line);
            if (tagMatches.Count == 0)
                return ReverseTextSegment(line);

            // pair opening/closing tags
            var pairs = new Dictionary<int, int>();
            var stack = new Stack<int>();
            for (int i = 0; i < tagMatches.Count; i++)
            {
                string tag = tagMatches[i].Value;
                if (tag.StartsWith("</"))
                {
                    if (stack.Count > 0)
                    {
                        int openIdx = stack.Pop();
                        pairs[openIdx] = i;
                        pairs[i] = openIdx;
                    }
                }
                else if (!tag.EndsWith("/>") && !tag.StartsWith("<!--"))
                {
                    stack.Push(i);
                }
            }

            // tokenize into parts
            var parts = new List<(bool isTag, string content, int tagIdx)>();
            int pos = 0;
            for (int i = 0; i < tagMatches.Count; i++)
            {
                var m = tagMatches[i];
                if (m.Index > pos)
                    parts.Add((false, line.Substring(pos, m.Index - pos), -1));
                parts.Add((true, m.Value, i));
                pos = m.Index + m.Length;
            }
            if (pos < line.Length)
                parts.Add((false, line.Substring(pos), -1));

            // reverse part order
            parts.Reverse();

            // emit
            var sb = new StringBuilder(line.Length);
            foreach (var part in parts)
            {
                if (part.isTag)
                {
                    // إذا كان جزءاً من زوج، استخدم محتوى التاق الـ paired
                    // (فتح يصبح إغلاق وبالعكس مع الحفاظ على الـ attributes الأصلية)
                    if (pairs.TryGetValue(part.tagIdx, out int pairedIdx))
                        sb.Append(tagMatches[pairedIdx].Value);
                    else
                        sb.Append(part.content);
                }
                else
                {
                    sb.Append(ReverseTextSegment(part.content));
                }
            }
            return sb.ToString();
        }

        // نُحضّر النص للعرض LTR-rendered RTL display:
        // نشكّل ثم نعكس كل سطر بصرياً
        private static string ReverseShapedTextForRtlDisplay(string shaped)
        {
            if (string.IsNullOrEmpty(shaped)) return shaped;
            string[] lines = shaped.Split('\n');
            for (int i = 0; i < lines.Length; i++)
                lines[i] = ReverseLineForVisualRtl(lines[i]);
            return string.Join("\n", lines);
        }

        // يكشف هل النص يحتوي بالفعل على Arabic Presentation Forms (U+FB50-FDFF أو U+FE70-FEFF)
        // → في هذه الحالة لا نُعيد shaping (يُعتبر مُشكَّلاً مسبقاً)
        internal static bool IsAlreadyShaped(string s)
        {
            if (string.IsNullOrEmpty(s)) return false;
            foreach (char c in s)
            {
                if ((c >= 0xFB50 && c <= 0xFDFF) || (c >= 0xFE70 && c <= 0xFEFF))
                    return true;
            }
            return false;
        }

        // ⭐ Shape فقط (initial/medial/final/isolated glyphs + Lam-Alef ligatures)
        // بدون عكس — يُبقي النص في الترتيب المنطقي → TMP مع isRightToLeftText=true
        // يتولّى الـ bidi والـ word-wrap بشكل صحيح (السطور تبقى بترتيبها).
        internal static string ApplyArabicShaping(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            if (!ContainsArabic(text)) return text;
            try
            {
                if (_shapeIn == null) _shapeIn = new RTLTMPro.FastStringBuilder(2048);
                if (_shapeOut == null) _shapeOut = new RTLTMPro.FastStringBuilder(2048);
                _shapeIn.SetValue(text);
                RTLTMPro.TashkeelFixer.RemoveTashkeel(_shapeIn);
                _shapeOut.Clear();
                // GlyphFixer.Fix يكتب logical-order مع presentation forms
                // (LigatureFixer الذي يعكس النص لا يُستدعى)
                RTLTMPro.GlyphFixer.Fix(_shapeIn, _shapeOut, preserveNumbers: true, farsi: false, fixTextTags: false);
                RTLTMPro.TashkeelFixer.RestoreTashkeel(_shapeOut);
                // GlyphFixer يحقن 0xFFFF كـ placeholder عند دمج Lam-Alef → نحذفها
                var sb = new StringBuilder(_shapeOut.Length);
                for (int i = 0; i < _shapeOut.Length; i++)
                {
                    int c = _shapeOut.Get(i);
                    if (c != 0xFFFF) sb.Append((char)c);
                }
                return sb.ToString();
            }
            catch (Exception e)
            {
                if (StaticLog != null) StaticLog.LogWarning("[ArabicFontFixer] Shaping failed: " + e.Message);
                return text;
            }
        }

        // diag للنصوص الطويلة (>= 30 حرف) التي تفشل في lookup — نطبع أول 20
        // فلتر طول لتجنّب spam من أسماء قصيرة مثل "Pioneer".
        private static int _diagLongMissCount = 0;

        internal static string Translate(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            // idempotency: نص مُشكَّل سلفاً = مرّ مسبقاً على Translate (نتركه)
            if (IsAlreadyShaped(text)) return text;
            if (_staticTr.TryGetValue(text, out var ar))
            {
                // marker لـ "لا ترجمة متاحة" (نخزّن النص نفسه): نُعيد النص كما هو فوراً
                // بدون استدعاء PrepareForRtlDisplay (مضيعة للموارد على نص لاتيني).
                return string.Equals(ar, text, StringComparison.Ordinal) ? text : PrepareForRtlDisplay(ar);
            }
            // fallback: جرّب المفتاح المُطبَّع. الـ proxy يطبّع newlines/whitespace قبل
            // التخزين في SQLite → translations.txt المُصدَّر بدون newlines. اللعبة قد ترسل
            // النص بـ newlines الأصلية → no match بدون التطبيع. نخزّن النتيجة بالمفتاح
            // الأصلي للسرعة في المرّات القادمة.
            var normText = NormalizeKey(text);
            if (!string.Equals(normText, text, StringComparison.Ordinal)
                && _staticTr.TryGetValue(normText, out ar))
            {
                lock (_pendingLock) { _staticTr[text] = ar; }
                return string.Equals(ar, text, StringComparison.Ordinal) ? text : PrepareForRtlDisplay(ar);
            }
            // diag: نصوص طويلة فاشلة (tooltips) — نسجّل كامل النص (مع escape) ومفتاح مُطبَّع
            if (_diagLongMissCount < 20 && text.Length >= 30 && NeedsTranslation(text) && !ContainsArabic(text))
            {
                _diagLongMissCount++;
                Diag($"LONG-MISS #{_diagLongMissCount} len={text.Length}");
                Diag($"  orig={EscapeForDiag(text)}");
                if (!string.Equals(normText, text, StringComparison.Ordinal))
                    Diag($"  norm={EscapeForDiag(normText)}");
            }
            if (ContainsArabic(text)) return PrepareForRtlDisplay(text);
            if (!NeedsTranslation(text)) return text;
            if (text.Length <= 4000)
                QueueForProxy(text, text.Length <= PriorityMaxLen);
            return text;
        }

        // يحوّل whitespace خفي لـ literal escapes في الـ log (\n, \r, \t)
        // لإظهار الفرق بين النص الذي تستلمه اللعبة والمفتاح في translations.txt.
        private static string EscapeForDiag(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            var sb = new StringBuilder(s.Length + 8);
            sb.Append('[');
            foreach (var ch in s)
            {
                if (ch == '\n') sb.Append("\\n");
                else if (ch == '\r') sb.Append("\\r");
                else if (ch == '\t') sb.Append("\\t");
                else if (ch < 32 || ch == 127) sb.Append("\\x").Append(((int)ch).ToString("x2"));
                else sb.Append(ch);
            }
            sb.Append(']');
            return sb.ToString();
        }

        // shape + insert \n عند نهاية الجمل + manual visual reversal per line
        // النص الناتج جاهز لـ TMP مع isRightToLeftText=false:
        //   TMP يعرض LTR كما هو، السطور (المعكوسة) تظهر بترتيبها الصحيح من فوق لتحت.
        private static string PrepareForRtlDisplay(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            // ⚠ ملاحظة: translations.txt يحوي نصوصاً بالفعل مُشكَّلة (presentation forms)
            // بترتيب منطقي. ApplyArabicShaping ذكيّ بحيث لا يُعيد التشكيل لو موجود.
            // لكن العكس البصري (Reverse) ضروري دائماً. لذا لا نستخدم idempotency هنا.
            string shaped = ApplyArabicShaping(text);
            shaped = InsertLineBreaksAtSentenceEnds(shaped);
            return ReverseShapedTextForRtlDisplay(shaped);
        }

        // عرض أقصى للسطر (أحرف) قبل الكسر اليدوي. أصغر من أضيق صندوق نص متوقّع
        // → يمنع TMP من تطبيق auto-wrap (الذي يعكس ترتيب الأسطر رأسياً مع النص المعكوس).
        // قابل للضبط حسب حجم خط اللعبة وعرض الصناديق.
        // 30: صناديق tooltips الضيّقة في Farthest Frontier تتّسع لـ ~33 حرفاً —
        // نُبقي العرض تحتها بهامش أمان كي لا يطبّق TMP auto-wrap (الذي يُيتّم الكلمات).
        private const int MaxVisualLineLen = 30;

        // يكسر النص لأسطر قصيرة لا تحتاج auto-wrap من TMP:
        //   1) يحترم أي \n موجود (يعالج كل سطر مستقلاً)
        //   2) يلفّ أي سطر يتجاوز MaxVisualLineLen عند حدود الكلمات فقط
        // ⚠ لا نكسر عند الفواصل/النقاط بعد الآن: طول السطر (MaxVisualLineLen) يتكفّل
        //    باللفّ. الكسر عند علامات الترقيم كان يُنتج أسطراً قصيرة متقطّعة بلا داعٍ.
        // السبب الأصلي للّفّ: نعكس كل سطر يدوياً per-line → لو TMP طبّق auto-wrap على
        // نص معكوس، ينقلب ترتيب الأسطر من فوق لتحت. ضمان كل سطر أقصر من العرض = لا عكس.
        private static string InsertLineBreaksAtSentenceEnds(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            // سطر واحد قصير لا يحتاج معالجة
            if (text.IndexOf('\n') < 0 && text.Length <= MaxVisualLineLen) return text;

            var outLines = new List<string>();
            foreach (var rawLine in text.Split('\n'))
                WrapWords(rawLine, MaxVisualLineLen, outLines);
            return string.Join("\n", outLines);
        }

        // يلفّ مقطعاً عند حدود الكلمات بحيث لا يتجاوز أي سطر maxLen، ويضيف الأسطر للنتيجة.
        private static void WrapWords(string segment, int maxLen, List<string> outLines)
        {
            if (segment == null) return;
            if (segment.Length <= maxLen) { outLines.Add(segment); return; }
            var words = segment.Split(' ');
            var cur = new StringBuilder();
            foreach (var w in words)
            {
                if (cur.Length == 0)
                    cur.Append(w);
                else if (cur.Length + 1 + w.Length > maxLen)
                {
                    outLines.Add(cur.ToString());
                    cur.Clear();
                    cur.Append(w);
                }
                else
                    cur.Append(' ').Append(w);
            }
            if (cur.Length > 0) outLines.Add(cur.ToString());
        }

        /// <summary>
        /// يعكس الأرقام في النص العربي مسبقاً — تعويض عن سلوك TMP الذي يعكس كل
        /// شيء عند isRightToLeftText=true (بما فيها أرقام يجب أن تبقى LTR).
        /// "60 دقيقة" → "06 دقيقة" → TMP يعكس الكل → النتيجة المرئية الصحيحة "60 دقيقة"
        /// </summary>
        private static string PreReverseDigitsForRTL(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            if (!ContainsArabic(s)) return s;     // الأرقام في النصوص الإنجليزية تبقى كما هي

            var result = new StringBuilder(s.Length);
            int i = 0;
            while (i < s.Length)
            {
                char c = s[i];
                if (c >= '0' && c <= '9')
                {
                    // اجمع رقم متعدّد الخانات ثم اعكسه
                    int start = i;
                    while (i < s.Length && s[i] >= '0' && s[i] <= '9') i++;
                    for (int j = i - 1; j >= start; j--) result.Append(s[j]);
                }
                else
                {
                    result.Append(c);
                    i++;
                }
            }
            return result.ToString();
        }

        // ── Proxy fallback ────────────────────────────────────────────────────

        private static void QueueForProxy(string text, bool priority = false)
        {
            lock (_pendingLock)
            {
                if (_prioritySet.Contains(text)) return;
                if (priority)
                {
                    _pendingSet.Remove(text);
                    _prioritySet.Add(text);
                    _priorityQueue.Enqueue(text);
                }
                else
                {
                    if (_pendingSet.Contains(text)) return;
                    _pendingSet.Add(text);
                }
            }
            EnsureWorkerRunning();
        }

        private static void EnsureWorkerRunning()
        {
            if (_worker != null && _worker.IsAlive) return;
            _worker = new Thread(WorkerLoop) { IsBackground = true, Name = "ArabicProxyWorker" };
            _worker.Start();
        }

        private static void WorkerLoop()
        {
            while (true)
            {
                List<string> priorityBatch;
                List<string> normalChunk;

                lock (_pendingLock)
                {
                    if (_priorityQueue.Count == 0 && _pendingSet.Count == 0) return;

                    priorityBatch = new List<string>();
                    while (_priorityQueue.Count > 0)
                    {
                        var t = _priorityQueue.Dequeue();
                        _prioritySet.Remove(t);
                        if (!_staticTr.ContainsKey(t)) priorityBatch.Add(t);
                    }

                    normalChunk = new List<string>(NormalChunkSize);
                    var toRemove = new List<string>(NormalChunkSize);
                    foreach (var t in _pendingSet)
                    {
                        if (_staticTr.ContainsKey(t)) { toRemove.Add(t); continue; }
                        normalChunk.Add(t); toRemove.Add(t);
                        if (normalChunk.Count >= NormalChunkSize) break;
                    }
                    foreach (var t in toRemove) _pendingSet.Remove(t);
                }

                foreach (var text in priorityBatch) { TranslateAndStore(text); Thread.Sleep(30); }
                foreach (var text in normalChunk)   { TranslateAndStore(text); Thread.Sleep(30); }
            }
        }

        private static void TranslateAndStore(string text)
        {
            try
            {
                var encoded = Uri.EscapeDataString(text);
                var req     = (HttpWebRequest)WebRequest.Create(ProxyUrl + "?text=" + encoded);
                req.Timeout = 5000; req.Method = "GET";
                using var resp   = (HttpWebResponse)req.GetResponse();
                using var reader = new StreamReader(resp.GetResponseStream(), Encoding.UTF8);
                var result = reader.ReadToEnd().Trim();
                if (!string.IsNullOrEmpty(result))
                {
                    if (result != text)
                    {
                        // ترجمة فعلية
                        lock (_pendingLock) { StoreWithNormalizedKey(text, result); }
                        _newTranslationsAvailable = true;
                    }
                    else
                    {
                        // marker: البروكسي ردّ نفس النص (failed/unchanged/skip)
                        // → نخزّنه كي لا نُعيد محاولة الـ queue كل hover.
                        lock (_pendingLock) { StoreWithNormalizedKey(text, text); }
                    }
                }
            }
            catch { }
        }

        // ── Harmony hooks ─────────────────────────────────────────────────────

        private void PatchTranslationHooks(Harmony harmony) { PatchI2(harmony); PatchTMP(harmony); }

        private void PatchI2(Harmony harmony)
        {
            try
            {
                Type lmType = null;
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                { lmType = asm.GetType("I2.Loc.LocalizationManager"); if (lmType != null) break; }
                if (lmType == null) { StaticLog?.LogInfo("[ArabicFontFixer] I2.Loc not found — skipped."); return; }
                MethodInfo target = null;
                foreach (var m in lmType.GetMethods(BindingFlags.Static | BindingFlags.Public))
                    if (m.Name == "GetTranslation" && m.ReturnType == typeof(string)) { target = m; break; }
                if (target == null) return;
                harmony.Patch(target, postfix: new HarmonyMethod(
                    typeof(Hooks).GetMethod("I2_GetTranslation_Postfix", BindingFlags.Static | BindingFlags.Public)));
                StaticLog?.LogInfo("[ArabicFontFixer] Hooked I2.Loc.");
            }
            catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] PatchI2: " + ex.Message); }
        }

        private void PatchTMP(Harmony harmony)
        {
            try
            {
                Type tmpType = null;
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                { tmpType = asm.GetType("TMPro.TMP_Text"); if (tmpType != null) break; }
                if (tmpType == null) return;

                // 1) Hook property setter: text = "..."
                var setter = tmpType.GetProperty("text", BindingFlags.Instance | BindingFlags.Public)?.GetSetMethod();
                if (setter != null)
                {
                    harmony.Patch(setter, prefix: new HarmonyMethod(
                        typeof(Hooks).GetMethod("TMP_SetText_Prefix", BindingFlags.Static | BindingFlags.Public)));
                    StaticLog?.LogInfo("[ArabicFontFixer] Hooked TMP_Text.set_text.");
                }

                // 2) Hook SetText overloads — postfix على الكل (يُلتقط أي مسار يضع نصاً)
                //    prefix إضافي على overloads الـ string لترجمة قبل البناء
                int hooks = 0;
                int postfixOnly = 0;
                var postfixMethod = typeof(Hooks).GetMethod("TMP_SetText_Postfix",
                    BindingFlags.Static | BindingFlags.Public);
                foreach (var m in tmpType.GetMethods(BindingFlags.Instance | BindingFlags.Public))
                {
                    if (m.Name != "SetText") continue;
                    var ps = m.GetParameters();
                    // SetText(string text)
                    if (ps.Length == 1 && ps[0].ParameterType == typeof(string))
                    {
                        try
                        {
                            harmony.Patch(m,
                                prefix: new HarmonyMethod(typeof(Hooks).GetMethod("TMP_SetTextString_Prefix", BindingFlags.Static | BindingFlags.Public)),
                                postfix: new HarmonyMethod(postfixMethod));
                            hooks++;
                        }
                        catch { }
                    }
                    // SetText(string text, bool syncTextInputBox) — اسم البراميتر sourceText في TMP الجديد
                    else if (ps.Length == 2 && ps[0].ParameterType == typeof(string) && ps[1].ParameterType == typeof(bool))
                    {
                        try
                        {
                            harmony.Patch(m,
                                prefix: new HarmonyMethod(typeof(Hooks).GetMethod("TMP_SetTextStringBool_Prefix", BindingFlags.Static | BindingFlags.Public)),
                                postfix: new HarmonyMethod(postfixMethod));
                            hooks++;
                        }
                        catch { }
                    }
                    else
                    {
                        // أي overload آخر (StringBuilder, char[], string+args) — postfix فقط
                        // يكشف العربي الخام عبر __instance.text بعد التعيين
                        try
                        {
                            harmony.Patch(m, postfix: new HarmonyMethod(postfixMethod));
                            postfixOnly++;
                        }
                        catch { }
                    }
                }
                if (hooks > 0 || postfixOnly > 0)
                    StaticLog?.LogInfo("[ArabicFontFixer] Hooked SetText: " + hooks + " full + " + postfixOnly + " postfix-only");

                // أضف postfix أيضاً لـ property setter
                if (setter != null)
                {
                    try
                    {
                        harmony.Patch(setter, postfix: new HarmonyMethod(postfixMethod));
                        StaticLog?.LogInfo("[ArabicFontFixer] Added postfix to TMP_Text.set_text.");
                    }
                    catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] set_text postfix failed: " + ex.Message); }
                }

                // 3) Hook UnityEngine.UI.Text.text setter (legacy) — fallback لو tooltips تستخدمها
                try
                {
                    var uiTextType = typeof(UnityEngine.UI.Text);
                    var uiSetter = uiTextType.GetProperty("text", BindingFlags.Instance | BindingFlags.Public)?.GetSetMethod();
                    if (uiSetter != null)
                    {
                        harmony.Patch(uiSetter, prefix: new HarmonyMethod(
                            typeof(Hooks).GetMethod("UIText_SetText_Prefix", BindingFlags.Static | BindingFlags.Public)));
                        StaticLog?.LogInfo("[ArabicFontFixer] Hooked UnityEngine.UI.Text.set_text.");
                    }
                }
                catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] UI.Text hook failed: " + ex.Message); }
            }
            catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] PatchTMP: " + ex.Message); }
        }

        // مرجع ثابت للـ Plugin instance — نستخدمه في hooks (static context)
        // ضروري لأن GameObject الخاص بنا قد يُدمَّر من اللعبة (Farthest Frontier)
        // → نعتمد على hooks الثابتة بدلاً من MonoBehaviour
        internal static ArabicFontFixer Instance;

        // عدّاد لتقليل عدد استدعاءات EnsureFont (تتكلف إذا فُعّلت كل set_text)
        private static int _ensureFontCallCount = 0;
        private static int _ensureFontInterval = 30;   // كل 30 استدعاء (أقل ضغط)

        // ── Load pre-built TMP Arabic font from AssetBundle ──────────────────────
        // الـ Bundle جاهز يبني في Unity Editor، نشحنه في
        //   BepInEx/config/ArabicGameTranslator/fonts/arabic_font.bundle
        private static bool _bundleTried = false;
        private static bool TryLoadArabicBundle()
        {
            if (_bundleTried) return _applied;
            _bundleTried = true;
            try
            {
                var bundlePath = Path.Combine(Paths.ConfigPath, "ArabicGameTranslator", "fonts", "arabic_font.bundle");
                Diag("TryLoadArabicBundle: checking " + bundlePath);
                if (!File.Exists(bundlePath))
                {
                    Diag("TryLoadArabicBundle: bundle NOT found");
                    return false;
                }
                StaticLog?.LogInfo("[ArabicFontFixer] Found arabic_font.bundle — loading…");

                var bundle = AssetBundle.LoadFromFile(bundlePath);
                if (bundle == null)
                {
                    Diag("TryLoadArabicBundle: AssetBundle.LoadFromFile returned null");
                    StaticLog?.LogWarning("[ArabicFontFixer] Failed to load AssetBundle from " + bundlePath);
                    return false;
                }

                // تعرّف على أسماء الـ assets داخل الـ bundle
                var names = bundle.GetAllAssetNames();
                Diag("TryLoadArabicBundle: bundle has " + names.Length + " assets");
                foreach (var n in names) Diag("  - " + n);

                // ابحث عن TMP_FontAsset في الـ bundle
                TMP_FontAsset arabicFont = null;
                foreach (var name in names)
                {
                    var asset = bundle.LoadAsset(name);
                    if (asset is TMP_FontAsset font)
                    {
                        arabicFont = font;
                        Diag("TryLoadArabicBundle: loaded TMP_FontAsset '" + font.name + "' from '" + name + "'");
                        break;
                    }
                }

                if (arabicFont == null)
                {
                    StaticLog?.LogWarning("[ArabicFontFixer] Bundle loaded but no TMP_FontAsset found inside.");
                    return false;
                }

                // سجّل الخط في TMP_Settings.fallbackFontAssets عبر reflection
                try
                {
                    var listProp = typeof(TMP_Settings).GetProperty("fallbackFontAssets",
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
                    if (listProp != null && listProp.CanRead)
                    {
                        var list = listProp.GetValue(null, null) as List<TMP_FontAsset>;
                        if (list != null && !list.Contains(arabicFont))
                        {
                            list.Add(arabicFont);
                            StaticLog?.LogInfo("[ArabicFontFixer] Arabic font added to TMP_Settings.fallbackFontAssets");
                        }
                    }
                }
                catch (Exception e) { StaticLog?.LogWarning("[ArabicFontFixer] fallbackFontAssets via reflection failed: " + e.Message); }

                _tmpFallback = arabicFont;

                // ⭐ مهم: استبدل shader الـ material بـ shader من خط موجود في اللعبة
                // (الـ shader في الـ bundle يشير إلى GUID لن يتطابق مع shaders اللعبة
                //  → Unity يعرض magenta. نحلّ هذا باستعارة shader من خط اللعبة)
                try
                {
                    var gameFonts = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
                    Shader gameShader = null;
                    foreach (var f in gameFonts)
                    {
                        if (f == null || ReferenceEquals(f, arabicFont)) continue;
                        if (f.material != null && f.material.shader != null)
                        {
                            gameShader = f.material.shader;
                            Diag("Found working shader from game font: '" + f.name + "' shader='" + gameShader.name + "'");
                            break;
                        }
                    }
                    if (gameShader != null && arabicFont.material != null)
                    {
                        // احفظ المرجع للـ atlas texture قبل تغيير الـ material
                        var atlas = arabicFont.atlasTexture;
                        arabicFont.material.shader = gameShader;
                        // أعد ربط الـ texture بعد تغيير shader (بعض الـ shaders يستخدمون _MainTex)
                        if (atlas != null)
                        {
                            arabicFont.material.SetTexture("_MainTex", atlas);
                        }
                        Diag("Shader replaced on Arabic font material");
                        StaticLog?.LogInfo("[ArabicFontFixer] Shader fixed: replaced bundle shader with game's '" + gameShader.name + "'");
                    }
                    else
                    {
                        Diag("Could NOT find replacement shader (gameShader=" + (gameShader != null ? "ok" : "null")
                            + ", arabicFont.material=" + (arabicFont.material != null ? "ok" : "null") + ")");
                    }
                }
                catch (Exception ex) { Diag("Shader replacement threw: " + ex.Message); }

                _applied = true;
                StaticLog?.LogInfo("[ArabicFontFixer] ✓ Arabic font ready: " + arabicFont.name);
                Diag("Arabic font LOADED from bundle: " + arabicFont.name);

                // verbose diagnostics — هل الـ atlas + glyphs موجودة فعلاً؟
                try
                {
                    var atlas = arabicFont.atlasTexture;
                    int charCount = (arabicFont.characterTable != null) ? arabicFont.characterTable.Count : -1;
                    int glyphCount = (arabicFont.glyphTable != null) ? arabicFont.glyphTable.Count : -1;
                    Diag("Font diagnostics: atlas=" + (atlas != null ? (atlas.width + "x" + atlas.height) : "NULL")
                        + ", chars=" + charCount + ", glyphs=" + glyphCount
                        + ", atlasPop=" + arabicFont.atlasPopulationMode);
                    StaticLog?.LogInfo("[ArabicFontFixer] Font diagnostics: atlas="
                        + (atlas != null ? (atlas.width + "x" + atlas.height) : "NULL")
                        + ", chars=" + charCount + ", glyphs=" + glyphCount);
                    // اطبع عينة من الـ characters
                    if (arabicFont.characterTable != null && arabicFont.characterTable.Count > 0)
                    {
                        var first = arabicFont.characterTable[0];
                        var sample = "first char unicode=" + first.unicode + " (" + (char)first.unicode + ")";
                        if (arabicFont.characterTable.Count > 100)
                        {
                            var c100 = arabicFont.characterTable[100];
                            sample += ", char100 unicode=" + c100.unicode;
                        }
                        Diag(sample);
                    }
                }
                catch (Exception e) { Diag("Font diagnostics threw: " + e.Message); }

                return true;
            }
            catch (Exception e)
            {
                StaticLog?.LogWarning("[ArabicFontFixer] TryLoadArabicBundle exception: " + e.GetType().Name + ": " + e.Message);
                return false;
            }
        }

        private static int _ensureEntryCount = 0;
        private static void EnsureFontFromHook()
        {
            // ⭐ live reload — Update() ما تشتغل لو GameObject مات (Farthest Frontier)
            // لذا نفحص الـ flag من داخل الـ hooks اللي تُستدعى بانتظام
            if (_reloadRequested) ProcessReloadRequest();

            // محاولة 0: تحميل bundle قبل أي شيء آخر (مرة واحدة فقط)
            if (!_applied && !_bundleTried)
            {
                if (TryLoadArabicBundle())
                {
                    Diag("EnsureFontFromHook: bundle loaded, applying to live texts");
                    try { ApplyToLiveText(); } catch (Exception e) { Diag("ApplyToLiveText: " + e.Message); }
                }
            }
            // diag قبل أي شيء — يثبت لو الدالة تُستدعى أصلاً
            _ensureEntryCount++;
            if (_ensureEntryCount == 1)
                Diag("EnsureFontFromHook ENTERED first time. _applied=" + _applied);
            else if (_ensureEntryCount == 50)
                Diag("EnsureFontFromHook entered 50x. _applied=" + _applied);

            try
            {
                if (_applied)
                {
                    // ⭐ لا نستدعي ApplyToLiveText الدوري — الـ prefix/postfix تطبّق الخط
                    // مباشرة على كل نص يُكتب. المسح الدوري Resources.FindObjectsOfTypeAll
                    // كان السبب الرئيسي للّاق (O(N) على كل أوبجكتس الذاكرة).
                    return;
                }
                // الخط لم يُنشأ بعد — حاول كل 10 استدعاءات
                _ensureFontCallCount++;
                if (_ensureFontCallCount == 1 || _ensureFontCallCount % 10 == 0)
                {
                    Diag("EnsureFontFromHook: trying TryCreateFont (call " + _ensureFontCallCount + ")");
                    if (TryCreateFont())
                    {
                        Diag("EnsureFontFromHook: font CREATED!");
                        StaticLog?.LogInfo("[ArabicFontFixer] Font created via hook (call " + _ensureFontCallCount + ")");
                    }
                    else
                    {
                        Diag("EnsureFontFromHook: TryCreateFont returned false");
                    }
                }
            }
            catch (Exception ex) { Diag("EnsureFontFromHook OUTER exception: " + ex.GetType().Name + ": " + ex.Message); }
        }

        // عدّاد مكشوف لـ hooks — يثبت إذا الـ hooks تُستدعى أصلاً
        private static int _i2HookCount = 0;
        private static int _tmpHookCount = 0;

        public static class Hooks
        {
            public static void I2_GetTranslation_Postfix(ref string __result)
            {
                _i2HookCount++;
                if (_i2HookCount == 1) Diag("I2.GetTranslation hook FIRED (first time)");
                else if (_i2HookCount == 50) Diag("I2.GetTranslation hook fired 50 times");
                if (__result != null) __result = Translate(__result);
                EnsureFontFromHook();
            }

            // طبّق فوراً على المكوّن الحالي — font + RTL — كي tooltips تظهر صحيحة بدون انتظار ApplyToLiveText
            private static void ApplyImmediate(TMP_Text instance, string value)
            {
                if (instance == null || value == null) return;
                if (!ContainsArabic(value)) return;
                try
                {
                    if (_tmpFallback != null && !ReferenceEquals(instance.font, _tmpFallback))
                        instance.font = _tmpFallback;
                }
                catch { }
                // ⭐ v3.1.5: نعكس بأنفسنا → isRTL=false (TMP يعرض LTR كما هو)
                try { if (instance.isRightToLeftText) instance.isRightToLeftText = false; } catch { }
                try
                {
                    // محاذاة RTL
                    switch (instance.alignment)
                    {
                        case TextAlignmentOptions.TopLeft:
                        case TextAlignmentOptions.BottomLeft:
                        case TextAlignmentOptions.Bottom:
                        case TextAlignmentOptions.BottomRight:
                            instance.alignment = TextAlignmentOptions.TopRight;
                            break;
                    }
                }
                catch { }
            }

            public static void TMP_SetText_Prefix(TMP_Text __instance, ref string value)
            {
                _tmpHookCount++;
                if (_tmpHookCount == 1) Diag("TMP_Text.set_text hook FIRED (first time)");
                else if (_tmpHookCount == 50) Diag("TMP_Text.set_text hook fired 50 times");
                else if (_tmpHookCount == 500) Diag("TMP_Text.set_text hook fired 500 times");
                if (value != null) value = Translate(value);
                ApplyImmediate(__instance, value);
                EnsureFontFromHook();
            }

            // SetText(string text) — مستخدم في tooltips
            public static void TMP_SetTextString_Prefix(TMP_Text __instance, ref string text)
            {
                if (text != null) text = Translate(text);
                ApplyImmediate(__instance, text);
                EnsureFontFromHook();
            }

            // SetText(string sourceText, bool syncTextInputBox)
            // ⭐ اسم البراميتر = sourceText (وليس text) في Unity 2022.3 TMP
            public static void TMP_SetTextStringBool_Prefix(TMP_Text __instance, ref string sourceText)
            {
                if (sourceText != null) sourceText = Translate(sourceText);
                ApplyImmediate(__instance, sourceText);
                EnsureFontFromHook();
            }

            // UnityEngine.UI.Text.text setter (legacy UI)
            public static void UIText_SetText_Prefix(ref string value)
            {
                if (value != null) value = Translate(value);
                EnsureFontFromHook();
            }

            // POSTFIX: يُستدعى بعد ما TMP يكمّل ضبط النص وبناء mesh أوّلي
            // هنا نُطبّق font + RTL + نكتشف نصوصاً عربية خام تجاوزت الـ prefix
            // (مثلاً عبر SetText(StringBuilder) أو غيرها) ونعالجها مباشرة
            private static int _postfixCallCount = 0;
            private static int _postfixArabicCount = 0;
            private static int _postfixShapedCount = 0;
            private static int _postfixRawCaughtCount = 0;
            // guard لمنع حلقة postfix → text= → prefix/postfix → text=
            [ThreadStatic] private static bool _inPostfixFix;
            public static void TMP_SetText_Postfix(TMP_Text __instance)
            {
                if (__instance == null || _inPostfixFix) return;
                _postfixCallCount++;
                try
                {
                    var current = __instance.text;
                    if (string.IsNullOrEmpty(current)) return;
                    bool hasArabic = ContainsArabic(current);
                    if (!hasArabic) return;
                    _postfixArabicCount++;

                    // diag إحصائي كل 50 نص عربي
                    if (_postfixArabicCount % 50 == 1)
                    {
                        bool shaped = IsAlreadyShaped(current);
                        Diag("Postfix Arabic #" + _postfixArabicCount + " (len=" + current.Length
                            + " shaped=" + shaped + " isRTL=" + __instance.isRightToLeftText
                            + " font=" + (__instance.font != null ? __instance.font.name : "null") + ")");
                        Diag("  preview: " + (current.Length > 60 ? current.Substring(0, 60) + "…" : current));
                    }

                    bool changed = false;

                    // ⭐ كشف نص عربي خام تجاوز الـ prefix (SetText(StringBuilder)/SetCharArray/إلخ):
                    // ContainsArabic=true && !IsAlreadyShaped → نُعيد التعيين عبر text=
                    bool isShaped = IsAlreadyShaped(current);
                    if (isShaped) _postfixShapedCount++;
                    if (!isShaped)
                    {
                        _postfixRawCaughtCount++;
                        string fixedText = PrepareForRtlDisplay(current);
                        if (!string.Equals(fixedText, current, StringComparison.Ordinal))
                        {
                            _inPostfixFix = true;
                            try
                            {
                                if (_postfixRawCaughtCount <= 10)
                                    Diag("Postfix caught raw Arabic #" + _postfixRawCaughtCount
                                        + " (len=" + current.Length + ") → re-setting shaped (newLen=" + fixedText.Length + ")");
                                __instance.text = fixedText;
                                current = fixedText;
                                changed = true;
                            }
                            catch (Exception ex)
                            {
                                if (_postfixRawCaughtCount < 10) Diag("Postfix reset failed: " + ex.Message);
                            }
                            finally { _inPostfixFix = false; }
                        }
                    }

                    // 1) الخط العربي
                    if (_tmpFallback != null && !ReferenceEquals(__instance.font, _tmpFallback))
                    {
                        try { __instance.font = _tmpFallback; changed = true; } catch { }
                    }
                    // ⭐ v3.1.5: نعكس بأنفسنا → isRTL=false (TMP يعرض LTR كما هو)
                    if (__instance.isRightToLeftText)
                    {
                        try { __instance.isRightToLeftText = false; changed = true; } catch { }
                    }
                    // 3) محاذاة RTL
                    switch (__instance.alignment)
                    {
                        case TextAlignmentOptions.TopLeft:
                        case TextAlignmentOptions.BottomLeft:
                        case TextAlignmentOptions.Bottom:
                        case TextAlignmentOptions.BottomRight:
                            __instance.alignment = TextAlignmentOptions.TopRight;
                            changed = true;
                            break;
                    }
                    if (changed)
                    {
                        try { __instance.havePropertiesChanged = true; __instance.ForceMeshUpdate(true, true); } catch { }
                    }
                }
                catch (Exception ex)
                {
                    if (_postfixCallCount < 10) Diag("Postfix exception: " + ex.Message);
                }
            }
        }

        // ── Main loop ────────────────────────────────────────────────────────
        // (ApplyLoop/IEnumerator القديمة أُزيلت — استُبدلت بـ FontFixerRuntime.Update)

        // مسح النصوص وإرسالها للبروكسي حتى قبل جاهزية الخط
        internal static void QueueUnknownTexts()
        {
            try
            {
                var tmpTexts = Resources.FindObjectsOfTypeAll<TMP_Text>();
                foreach (var text in tmpTexts)
                {
                    if (text == null) continue;
                    var current = text.text;
                    if (string.IsNullOrEmpty(current) || ContainsArabic(current)) continue;
                    // حد كبير للنصوص الطويلة (شاشات تعليمات/مساعدة فيها sprite tags كثيرة):
            // نص واحد قد يبلغ 1500+ حرف بعد توسيع <sprite="..." name="..."> لكل أيقونة
            if (current.Length > 4000 || !NeedsTranslation(current)) continue;
                    lock (_pendingLock) { if (_staticTr.ContainsKey(current)) continue; }
                    bool isVisible = text.isActiveAndEnabled && text.gameObject.activeInHierarchy;
                    QueueForProxy(current, isVisible && current.Length <= PriorityMaxLen);
                }
            }
            catch { }
        }

        // ── Font creation ─────────────────────────────────────────────────────

        private static int _fontFailLogCount = 0;
        internal static bool TryCreateFont()
        {
            if (_applied) return true;
            try
            {
                _osFont = Font.CreateDynamicFontFromOSFont(OsFontNames, 36);
                if (_osFont == null)
                {
                    if (_fontFailLogCount < 3)
                    {
                        StaticLog?.LogWarning("[ArabicFontFixer] Font.CreateDynamicFontFromOSFont returned null. "
                            + "OS fonts tried: " + string.Join(", ", OsFontNames));
                        _fontFailLogCount++;
                    }
                    return false;
                }

                // نستخدم الـ signature الموجود في TMP القديم/الحديث
                _tmpFallback = TryCreateTmpFontVerbose();

                if (_tmpFallback == null)
                {
                    if (_fontFailLogCount < 3)
                    {
                        StaticLog?.LogWarning("[ArabicFontFixer] TMP font creation returned null. "
                            + "_osFont=" + (_osFont != null ? _osFont.name : "null"));
                        _fontFailLogCount++;
                    }
                    // مقاربة بديلة: أضف العربي للخطوط الموجودة في اللعبة
                    if (TryAddArabicToExistingFonts())
                    {
                        _applied = true;
                        StaticLog?.LogInfo("[ArabicFontFixer] Arabic chars added to existing TMP fonts (alt approach).");
                        return true;
                    }
                    return false;
                }

                _tmpFallback.name = "ArabicFontFixer_Fallback";
                try { _tmpFallback.atlasPopulationMode = AtlasPopulationMode.Dynamic; } catch { }

                const string arabicChars =
                    "ابتثجحخدذرزسشصضطظعغفقكلمنهويئىةآأإؤءءآأإؤء" +
                    "0123456789 .,!?،؛؟:؛()[]{}%-+/*=_\"'<>\\@#&^~`|";
                try { _tmpFallback.TryAddCharacters(arabicChars); } catch { }

                // الـ fallback العام في TMP_Settings — قد يكون readonly في بعض النسخ
                // → نتعامل عبر reflection للحصول على getter ثم Add() على القائمة
                try
                {
                    var listProp = typeof(TMP_Settings).GetProperty("fallbackFontAssets",
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
                    if (listProp != null && listProp.CanRead)
                    {
                        var list = listProp.GetValue(null, null) as List<TMP_FontAsset>;
                        if (list != null && !list.Contains(_tmpFallback))
                        {
                            list.Add(_tmpFallback);
                            StaticLog?.LogInfo("[ArabicFontFixer] Added to TMP_Settings.fallbackFontAssets");
                        }
                    }
                }
                catch (Exception e)
                {
                    StaticLog?.LogWarning("[ArabicFontFixer] fallbackFontAssets via reflection failed: " + e.Message);
                }

                _applied = true;
                StaticLog?.LogInfo("[ArabicFontFixer] Registered fallback: " + _tmpFallback.name);
                return true;
            }
            catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] TryCreateFont: " + ex.Message); return false; }
        }

        private static TMP_FontAsset TryCreateTmpFontVerbose()
        {
            bool firstFail = (_fontFailLogCount == 0);

            // 1) جرّب الـ signature الكامل (8 args)
            if (_osFont != null)
            {
                try
                {
                    var a = TMP_FontAsset.CreateFontAsset(_osFont, 90, 9,
                        GlyphRenderMode.SDFAA, 1024, 1024, AtlasPopulationMode.Dynamic, true);
                    if (a != null) { StaticLog?.LogInfo("[ArabicFontFixer] TMP_FontAsset created (8-arg)."); return a; }
                    if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 8-arg CreateFontAsset returned NULL (no exception).");
                }
                catch (Exception e) { if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 8-arg threw: " + e.GetType().Name + ": " + e.Message); }
            }

            // 2) جرّب 6-arg signature عبر reflection
            if (_osFont != null)
            {
                try
                {
                    var mi6 = typeof(TMP_FontAsset).GetMethod("CreateFontAsset",
                        new[] { typeof(Font), typeof(int), typeof(int), typeof(GlyphRenderMode), typeof(int), typeof(int) });
                    if (mi6 != null)
                    {
                        var a = mi6.Invoke(null, new object[] { _osFont, 90, 9, GlyphRenderMode.SDFAA, 1024, 1024 }) as TMP_FontAsset;
                        if (a != null) { StaticLog?.LogInfo("[ArabicFontFixer] TMP_FontAsset created (6-arg)."); return a; }
                        if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 6-arg CreateFontAsset returned NULL.");
                    }
                    else if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 6-arg overload not found.");
                }
                catch (Exception e) { if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 6-arg threw: " + e.Message); }
            }

            // 3) جرّب 4-arg signature (Font, int, int, GlyphRenderMode)
            if (_osFont != null)
            {
                try
                {
                    var mi4 = typeof(TMP_FontAsset).GetMethod("CreateFontAsset",
                        new[] { typeof(Font), typeof(int), typeof(int), typeof(GlyphRenderMode) });
                    if (mi4 != null)
                    {
                        var a = mi4.Invoke(null, new object[] { _osFont, 90, 9, GlyphRenderMode.SDFAA }) as TMP_FontAsset;
                        if (a != null) { StaticLog?.LogInfo("[ArabicFontFixer] TMP_FontAsset created (4-arg)."); return a; }
                    }
                }
                catch (Exception e) { if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] 4-arg threw: " + e.Message); }
            }

            // 4) جرّب أحجام أصغر (atlas غير ضخم)
            if (_osFont != null)
            {
                try
                {
                    var a = TMP_FontAsset.CreateFontAsset(_osFont, 36, 5,
                        GlyphRenderMode.SDFAA, 512, 512, AtlasPopulationMode.Dynamic, true);
                    if (a != null) { StaticLog?.LogInfo("[ArabicFontFixer] TMP_FontAsset created (small atlas)."); return a; }
                }
                catch (Exception e) { if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] small-atlas threw: " + e.Message); }
            }

            // 5) Modern API (TMP 3.0+)
            foreach (var name in OsFontNames)
            {
                try
                {
                    var mi = typeof(TMP_FontAsset).GetMethod("CreateFontAsset",
                        new[] { typeof(string), typeof(string), typeof(int) });
                    if (mi != null)
                    {
                        var asset = mi.Invoke(null, new object[] { name, "Regular", 90 }) as TMP_FontAsset;
                        if (asset != null) { StaticLog?.LogInfo("[ArabicFontFixer] TMP_FontAsset modern via reflection: " + name); return asset; }
                    }
                    else if (firstFail && name == OsFontNames[0])
                        StaticLog?.LogWarning("[ArabicFontFixer] Modern API not available.");
                }
                catch (Exception e) { if (firstFail) StaticLog?.LogWarning("[ArabicFontFixer] Modern reflection '" + name + "' threw: " + e.Message); }
            }

            return null;
        }

        // مقاربة بديلة — لو فشل خلق TMP_FontAsset جديد، نضيف عربي للخطوط الموجودة
        private static bool _altApproachTried = false;
        private static bool TryAddArabicToExistingFonts()
        {
            if (_altApproachTried) return false;
            _altApproachTried = true;
            try
            {
                var fonts = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
                StaticLog?.LogInfo("[ArabicFontFixer] Alt: found " + fonts.Length + " existing TMP_FontAsset(s):");
                // اطبع أسماء كل الخطوط — قد يكون فيها خط عربي/Noto/...
                foreach (var f in fonts)
                {
                    if (f == null) continue;
                    try
                    {
                        var src = (f.sourceFontFile != null) ? f.sourceFontFile.name : "<no-source>";
                        StaticLog?.LogInfo("[ArabicFontFixer]   • '" + f.name
                            + "' (atlas=" + f.atlasPopulationMode
                            + ", source=" + src + ")");
                    }
                    catch { StaticLog?.LogInfo("[ArabicFontFixer]   • '" + f.name + "' (info failed)"); }
                }

                int added = 0;
                const string arabicChars = "ابتثجحخدذرزسشصضطظعغفقكلمنهويئىةآأإؤءء0123456789 .,!?،؛؟:()[]{}";
                foreach (var f in fonts)
                {
                    if (f == null) continue;
                    try
                    {
                        // 1) بدّل sourceFontFile للـ Tahoma عبر reflection (read-only property)
                        if (_osFont != null)
                        {
                            try
                            {
                                var srcProp = typeof(TMP_FontAsset).GetField("m_SourceFontFile",
                                    System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                                if (srcProp != null) srcProp.SetValue(f, _osFont);
                            }
                            catch (Exception e) { StaticLog?.LogWarning("[ArabicFontFixer] Alt: set m_SourceFontFile on '" + f.name + "' failed: " + e.Message); }
                        }
                        // 2) اجعل atlas dynamic
                        try { f.atlasPopulationMode = AtlasPopulationMode.Dynamic; } catch { }
                        // 3) جرّب إضافة Arabic chars
                        if (f.TryAddCharacters(arabicChars))
                        {
                            added++;
                            StaticLog?.LogInfo("[ArabicFontFixer] Alt: ✓ added Arabic to '" + f.name + "'");
                        }
                    }
                    catch (Exception e) { StaticLog?.LogWarning("[ArabicFontFixer] Alt: TryAddCharacters '" + f.name + "' failed: " + e.Message); }
                }
                StaticLog?.LogInfo("[ArabicFontFixer] Alt: added Arabic to " + added + "/" + fonts.Length + " fonts");
                return added > 0;
            }
            catch (Exception e) { StaticLog?.LogWarning("[ArabicFontFixer] Alt approach threw: " + e.Message); return false; }
        }

        // (TryCreateTmpModern / TryCreateTmpLegacy القديمة استُبدلت بـ TryCreateTmpFontVerbose أعلاه)

        // ── Apply to live objects ─────────────────────────────────────────────

        private static int _applyCallCount = 0;
        internal static void ApplyToLiveText()
        {
            if (!_applied) return;
            _applyCallCount++;
            try
            {
                // Update per-font fallback tables — مع defensive checks لـ Unity fake-null
                var allFonts = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
                int added = 0, skipped = 0;
                foreach (var font in allFonts)
                {
                    try
                    {
                        if (font == null) { skipped++; continue; }
                        if (ReferenceEquals(font, _tmpFallback)) continue;
                        var table = font.fallbackFontAssetTable;
                        if (table == null)
                        {
                            // setter قد يكون read-only في هذه النسخة من TMP — جرّب reflection
                            try
                            {
                                var fld = typeof(TMP_FontAsset).GetField("m_FallbackFontAssetTable",
                                    System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                                if (fld != null)
                                {
                                    table = new List<TMP_FontAsset>();
                                    fld.SetValue(font, table);
                                }
                            }
                            catch { skipped++; continue; }
                            if (table == null) { skipped++; continue; }
                        }
                        if (!table.Contains(_tmpFallback))
                        {
                            table.Add(_tmpFallback);
                            added++;
                        }
                    }
                    catch (Exception ex) { skipped++; if (_applyCallCount == 1) Diag("ApplyToLive font skip: " + ex.Message); }
                }
                if (_applyCallCount == 1)
                    Diag("ApplyToLiveText: added Arabic to " + added + " fonts, skipped " + skipped);

                // ⭐ reverse map (ar_displayed → en) لاستبدال الترجمات الظاهرة عند live reload
                // TMP يعرض النص بعد PrepareForRtlDisplay، فنبني الـ map على هذه الصيغة.
                Dictionary<string, string> reverseMap = null;
                lock (_pendingLock)
                {
                    if (_staticTr.Count > 0)
                    {
                        reverseMap = new Dictionary<string, string>(_staticTr.Count);
                        foreach (var kv in _staticTr)
                        {
                            try
                            {
                                var displayed = PrepareForRtlDisplay(kv.Value);
                                reverseMap[displayed] = kv.Key;
                            }
                            catch { }
                        }
                    }
                }

                var tmpTexts = Resources.FindObjectsOfTypeAll<TMP_Text>();
                foreach (var text in tmpTexts)
                {
                    try
                    {
                        if (text == null) continue;
                        var current   = text.text;
                        var hasArabic = ContainsArabic(current);

                        if (!hasArabic && !string.IsNullOrEmpty(current))
                        {
                            string ar;
                            lock (_pendingLock) { _staticTr.TryGetValue(current, out ar); }
                            if (ar != null)
                            {
                                text.text = PrepareForRtlDisplay(ar);
                                hasArabic = true;
                                try { text.havePropertiesChanged = true; text.ForceMeshUpdate(true, true); } catch { }
                            }
                            else if (current.Length <= 4000 && NeedsTranslation(current))
                            {
                                bool isVisible = text.isActiveAndEnabled && text.gameObject.activeInHierarchy;
                                QueueForProxy(current, isVisible && current.Length <= PriorityMaxLen);
                            }
                        }
                        // ⭐ النص الحالي عربي — قد يكون ترجمة قديمة قبل live reload
                        // ابحث عن الـ english الأصلي عبر reverseMap، ثم طبّق الترجمة الجديدة
                        else if (hasArabic && reverseMap != null)
                        {
                            if (reverseMap.TryGetValue(current, out var enKey))
                            {
                                string newAr;
                                lock (_pendingLock) { _staticTr.TryGetValue(enKey, out newAr); }
                                if (newAr != null)
                                {
                                    var newDisplay = PrepareForRtlDisplay(newAr);
                                    if (!string.Equals(current, newDisplay, StringComparison.Ordinal))
                                    {
                                        text.text = newDisplay;
                                        try { text.havePropertiesChanged = true; text.ForceMeshUpdate(true, true); } catch { }
                                    }
                                }
                            }
                        }

                        if (hasArabic)
                        {
                            var id = text.GetInstanceID();
                            if (!_origTmpAlign.ContainsKey(id))
                                _origTmpAlign[id] = text.alignment;
                            ApplyRtlAlignment(text);
                            // ⭐ اضبط text.font مباشرة على الخط العربي
                            try
                            {
                                if (_tmpFallback != null && !ReferenceEquals(text.font, _tmpFallback))
                                    text.font = _tmpFallback;
                            }
                            catch { }
                            // ⭐ v3.1.5: نعكس بأنفسنا → isRTL=false
                            try
                            {
                                if (text.isRightToLeftText) text.isRightToLeftText = false;
                            }
                            catch { }
                            try { text.havePropertiesChanged = true; text.ForceMeshUpdate(true, true); } catch { }
                        }
                        else
                        {
                            var id = text.GetInstanceID();
                            if (_origTmpAlign.TryGetValue(id, out var orig) && text.alignment != orig)
                            {
                                text.alignment = orig;
                                try { text.havePropertiesChanged = true; text.ForceMeshUpdate(true, true); } catch { }
                            }
                        }
                    }
                    catch (Exception inner) { if (_applyCallCount == 1) Diag("TMP_Text skip: " + inner.Message); }
                }

                if (_osFont != null)
                {
                    var uiTexts = Resources.FindObjectsOfTypeAll<Text>();
                    foreach (var text in uiTexts)
                    {
                        try
                        {
                            if (text == null) continue;
                            var current   = text.text;
                            var hasArabic = ContainsArabic(current);
                            if (!hasArabic && !string.IsNullOrEmpty(current))
                            {
                                string ar;
                                lock (_pendingLock) { _staticTr.TryGetValue(current, out ar); }
                                if (ar != null) { text.text = ar; hasArabic = true; }
                            }
                            if (hasArabic)
                            {
                                if (text.font != _osFont) text.font = _osFont;
                                var id = text.GetInstanceID();
                                if (!_origUiAlign.ContainsKey(id)) _origUiAlign[id] = text.alignment;
                                ApplyRtlAlignment(text);
                            }
                            else
                            {
                                var id = text.GetInstanceID();
                                if (_origUiAlign.TryGetValue(id, out var orig) && text.alignment != orig)
                                    text.alignment = orig;
                            }
                        }
                        catch (Exception inner) { if (_applyCallCount == 1) Diag("UI Text skip: " + inner.Message); }
                    }
                }
            }
            catch (Exception ex) { StaticLog?.LogWarning("[ArabicFontFixer] ApplyToLiveText: " + ex.Message); }
        }

        // ── RTL alignment ─────────────────────────────────────────────────────
        // ملاحظة: نتجنّب قلب Left → Right لأن النصوص العربية الطويلة (مثل
        // "حساسية الحركة" أو "إجبار استخدام لوحة المفاتيح") تتداخل مع controls
        // على اليمين (sliders, toggles). نُبقي Left على Left لتظهر يساراً بدون تداخل.
        // TMP مع isRightToLeftText=true يقرأ RTL داخل الحدود اليسارية بشكل طبيعي.

        private static void ApplyRtlAlignment(TMP_Text text)
        {
            switch (text.alignment)
            {
                case TextAlignmentOptions.TopLeft:      text.alignment = TextAlignmentOptions.TopRight;      break;
                case TextAlignmentOptions.BottomLeft:   text.alignment = TextAlignmentOptions.TopRight;      break;
                case TextAlignmentOptions.Bottom:       text.alignment = TextAlignmentOptions.TopRight;      break;
                case TextAlignmentOptions.BottomRight:  text.alignment = TextAlignmentOptions.TopRight;      break;
                // Left/MidlineLeft/BaselineLeft/CaplineLeft تبقى كما هي
            }
        }

        private static void ApplyRtlAlignment(Text text)
        {
            // UI Text القديم: لا نقلب alignment لتجنّب التداخل
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private static bool NeedsTranslation(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return false;
            var t = text.Trim();
            if (t.Length < 3) return false;
            bool hasLetter = false;
            foreach (var ch in t)
            {
                if ((ch >= '　' && ch <= '鿿') || (ch >= 'Ѐ' && ch <= 'ӿ') ||
                    (ch >= '぀' && ch <= 'ヿ') || (ch >= '가' && ch <= '힯'))
                    return false;
                if (char.IsLetter(ch)) hasLetter = true;
            }
            return hasLetter;
        }

        private static bool ContainsArabic(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            foreach (var ch in text)
            {
                if ((ch >= '؀' && ch <= 'ۿ') || (ch >= 'ݐ' && ch <= 'ݿ') ||
                    (ch >= 'ࢠ' && ch <= 'ࣿ') || (ch >= 'ﭐ' && ch <= '﷿') ||
                    (ch >= 'ﹰ' && ch <= '﻿'))
                    return true;
            }
            return false;
        }
    }

    /// <summary>
    /// MonoBehaviour مستقل يعمل في GameObject محمي بـ DontDestroyOnLoad.
    /// مهمته الوحيدة: استدعاء ProcessReloadRequest كل frame.
    ///
    /// لماذا منفصل عن Plugin: BepInEx Plugin GameObject قد يُدمَّر في بعض الألعاب
    /// (Farthest Frontier مثلاً) → Update() لا تشتغل. هذا الـ GameObject محمي
    /// مما يضمن استمرار النبض كل frame طوال عمر اللعبة.
    /// </summary>
    public class LiveReloadDriver : MonoBehaviour
    {
        private int _tick = 0;
        private void Update()
        {
            ArabicFontFixer.ProcessReloadRequest();
            // diag كل ~600 frame (10 ث تقريباً) لتأكيد أن الـ driver حي
            if (++_tick == 600)
            {
                _tick = 0;
                ArabicFontFixer.DriverHeartbeat();
            }
        }
    }
}
