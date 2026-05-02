using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Unity.Mono;
using HarmonyLib;
using TMPro;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ArabicGameTranslatorMVP.Flotsam
{
    [BepInPlugin("com.arabicgametranslator.flotsam.runtime", "Flotsam Arabic Runtime", "0.1.0")]
    public class FlotsamArabicRuntime : BaseUnityPlugin
    {
        private static readonly Regex FormattingTagRegex = new Regex(
            @"</?(b|i|size|color|material|font|mark|alpha|cspace|font-weight)[^>]*>",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );
        private static readonly Regex ReversedFormattingMarkerRegex = new Regex(
            @">(\/)?(b|i|size|color|material|font|mark|alpha|cspace|font-weight)([^<]*)<",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );
        private static readonly Regex SpriteTagRegex = new Regex(
            @"<sprite[^>]*>",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );
        private static readonly Regex ReversedSpriteTagRegex = new Regex(
            @">[^<]*(etirps|sprite)[^<]*<",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );
        private static readonly Regex ReversedBraceTokenRegex = new Regex(
            @"\}([A-Z0-9_]+)\{",
            RegexOptions.Compiled
        );
        private static readonly Regex ReversedBracketBraceTokenRegex = new Regex(
            @"\}\]([A-Z0-9_]+)\[\{",
            RegexOptions.Compiled
        );
        private static readonly Regex BraceTokenRegex = new Regex(
            @"\{([A-Z0-9_]+)\}",
            RegexOptions.Compiled
        );
        private static readonly Regex BracketBraceTokenRegex = new Regex(
            @"\{\[([A-Z0-9_]+)\]\}",
            RegexOptions.Compiled
        );
        private static readonly Regex DirectionalControlCharsRegex = new Regex(
            "[\u200e\u200f\u202a-\u202e\u2066-\u2069]",
            RegexOptions.Compiled
        );

        private ConfigEntry<string> _translationsPath;
        private ConfigEntry<bool> _forceArabicLanguage;
        private Dictionary<string, string> _translations = new Dictionary<string, string>();
        private bool _applied;
        private bool _fontFallbackApplied;
        private Font _osArabicFont;
        private TMP_FontAsset _arabicTmpFallback;
        private bool _fontOverrideCoroutineStarted;
        private string _lastObservedLanguage;
        private Coroutine _languageRefreshCoroutine;
        private readonly Dictionary<int, TmpTextState> _tmpTextStates = new Dictionary<int, TmpTextState>();
        private readonly Dictionary<int, UiTextState> _uiTextStates = new Dictionary<int, UiTextState>();
        private Harmony _harmony;
        private static FlotsamArabicRuntime _instance;

        private sealed class TmpTextState
        {
            public TMP_FontAsset Font;
            public TextAlignmentOptions Alignment;
        }

        private sealed class UiTextState
        {
            public Font Font;
            public TextAnchor Alignment;
        }

        private void Awake()
        {
            _instance = this;
            var defaultPath = Path.Combine(Paths.ConfigPath, "ArabicGameTranslator", "flotsam_i2_translated_only.json");
            _translationsPath = Config.Bind("General", "TranslationsPath", defaultPath, "Path to the translated-only Flotsam JSON file.");
            _forceArabicLanguage = Config.Bind(
                "General",
                "ForceArabicLanguage",
                false,
                "When true, the runtime forces the game language to Arabic on startup. When false, it only adds/updates the Arabic slot and respects the user's selected language."
            );
            LoadTranslations();
            InstallTextHooks();
            SceneManager.sceneLoaded += OnSceneLoaded;
            StartCoroutine(ApplyWhenReady());
            StartCoroutine(WatchLanguageChanges());
        }

        private void OnDestroy()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;

            if (_harmony != null)
            {
                _harmony.UnpatchSelf();
                _harmony = null;
            }

            if (ReferenceEquals(_instance, this))
            {
                _instance = null;
            }
        }

        private void LoadTranslations()
        {
            try
            {
                var path = _translationsPath.Value;
                if (!File.Exists(path))
                {
                    Logger.LogWarning("Translations file not found: " + path);
                    return;
                }

                var rawJson = File.ReadAllText(path);
                TranslationPayload payload = null;
                
                // Try entries format first
                try { payload = JsonConvert.DeserializeObject<TranslationPayload>(rawJson); } catch {}
                
                // If entries is empty, try I2Languages full format
                if (payload == null || payload.entries == null || payload.entries.Count == 0)
                {
                    try
                    {
                        var i2Data = JObject.Parse(rawJson);
                        var mSource = i2Data["mSource"];
                        var mTerms = mSource?["mTerms"];
                        var termsArray = mTerms?["Array"];
                        if (termsArray != null)
                        {
                            payload = new TranslationPayload { entries = new List<TranslationEntry>() };
                            foreach (var term in termsArray)
                            {
                                var key = term["Term"]?.ToString();
                                var langs = term["Languages"]?["Array"];
                                if (langs == null || string.IsNullOrWhiteSpace(key)) continue;

                                var langArray = langs.ToObject<string[]>();
                                if (langArray != null && langArray.Length > 15 && !string.IsNullOrWhiteSpace(langArray[15]))
                                {
                                    payload.entries.Add(new TranslationEntry { key = key, Arabic = langArray[15] });
                                }
                            }
                            Logger.LogInfo("Loaded from I2Languages format: " + payload.entries.Count + " Arabic entries");
                        }
                    }
                    catch {}
                }
                
                if (payload == null || payload.entries == null)
                {
                    Logger.LogWarning("Translations payload is empty.");
                    return;
                }

                var duplicateCount = 0;
                var translations = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var entry in payload.entries.Where(x => x != null && !string.IsNullOrWhiteSpace(x.key) && !string.IsNullOrWhiteSpace(x.Arabic)))
                {
                    if (translations.ContainsKey(entry.key))
                    {
                        duplicateCount++;
                    }

                    translations[entry.key] = entry.Arabic;
                }

                _translations = translations;

                Logger.LogInfo("Loaded Arabic translations: " + _translations.Count);
                if (duplicateCount > 0)
                {
                    Logger.LogWarning("Duplicate translation keys found and collapsed: " + duplicateCount);
                }
            }
            catch (Exception ex)
            {
                Logger.LogError("Failed to load translations: " + ex);
            }
        }

        private IEnumerator ApplyWhenReady()
        {
            for (var i = 0; i < 120; i++)
            {
                if (!_applied && TryApplyTranslations())
                {
                    _applied = true;
                    TryApplyArabicFontFallback();
                    StartFontOverrideLoop();
                }

                yield return new WaitForSeconds(1f);
            }

            Logger.LogWarning("Timed out waiting for Flotsam localization manager.");
        }

        private IEnumerator WatchLanguageChanges()
        {
            while (true)
            {
                try
                {
                    var localizationManagerType = FindType("I2.Loc.LocalizationManager");
                    if (localizationManagerType != null)
                    {
                        var currentLanguage = localizationManagerType.GetProperty("CurrentLanguage", BindingFlags.Public | BindingFlags.Static);
                        var current = currentLanguage != null ? currentLanguage.GetValue(null, null) as string : null;
                        if (!string.IsNullOrWhiteSpace(current) && !string.Equals(current, _lastObservedLanguage, StringComparison.Ordinal))
                        {
                            _lastObservedLanguage = current;
                            TriggerRefresh(localizationManagerType);
                            ApplyArabicFallbackToLiveText();
                            StartLanguageRefreshBurst(current);
                            Logger.LogInfo("Observed language change -> " + current);
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogWarning("Language watch failed: " + ex.Message);
                }

                yield return new WaitForSeconds(0.5f);
            }
        }

        private bool TryApplyTranslations()
        {
            if (_translations.Count == 0)
            {
                return false;
            }

            var localizationManagerType = FindType("I2.Loc.LocalizationManager");
            if (localizationManagerType == null)
            {
                return false;
            }

            var sources = GetSources(localizationManagerType);
            if (sources == null || sources.Count == 0)
            {
                return false;
            }

            var patchedTerms = 0;
            foreach (var source in sources)
            {
                patchedTerms += PatchSource(source);
            }

            if (patchedTerms == 0)
            {
                Logger.LogWarning("Localization manager found, but no terms were patched.");
                return false;
            }

            if (_forceArabicLanguage.Value)
            {
                SetLanguageToArabic(localizationManagerType);
            }

            var currentLanguage = localizationManagerType.GetProperty("CurrentLanguage", BindingFlags.Public | BindingFlags.Static);
            _lastObservedLanguage = currentLanguage != null ? currentLanguage.GetValue(null, null) as string : null;
            TriggerRefresh(localizationManagerType);
            TryApplyArabicFontFallback();
            StartFontOverrideLoop();
            Logger.LogInfo("Applied Arabic translations to terms: " + patchedTerms);
            return true;
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            StartCoroutine(RefreshAfterSceneLoad(scene.name));
        }

        private IEnumerator RefreshAfterSceneLoad(string sceneName)
        {
            yield return new WaitForSeconds(0.2f);
            TryRefreshLocalization("scene:" + sceneName);
            yield return new WaitForSeconds(0.8f);
            TryRefreshLocalization("scene-late:" + sceneName);
        }

        private void TryRefreshLocalization(string reason)
        {
            try
            {
                var localizationManagerType = FindType("I2.Loc.LocalizationManager");
                if (localizationManagerType == null)
                {
                    return;
                }

                TriggerRefresh(localizationManagerType);
                ApplyArabicFallbackToLiveText();
                Logger.LogInfo("Triggered localization refresh (" + reason + ").");
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Refresh trigger failed (" + reason + "): " + ex.Message);
            }
        }

        private void StartLanguageRefreshBurst(string language)
        {
            if (_languageRefreshCoroutine != null)
            {
                StopCoroutine(_languageRefreshCoroutine);
            }

            _languageRefreshCoroutine = StartCoroutine(RefreshAfterLanguageChange(language));
        }

        private IEnumerator RefreshAfterLanguageChange(string language)
        {
            yield return new WaitForSeconds(0.05f);
            TryRefreshLocalization("language:" + language + ":fast");
            yield return new WaitForSeconds(0.25f);
            TryRefreshLocalization("language:" + language + ":mid");
            yield return new WaitForSeconds(0.75f);
            TryRefreshLocalization("language:" + language + ":late");
            _languageRefreshCoroutine = null;
        }

        private void StartFontOverrideLoop()
        {
            if (_fontOverrideCoroutineStarted)
            {
                return;
            }

            _fontOverrideCoroutineStarted = true;
            StartCoroutine(FontOverrideLoop());
        }

        private void InstallTextHooks()
        {
            try
            {
                _harmony = new Harmony("com.arabicgametranslator.flotsam.runtime.textpatch");

                var tmpTextSetter = AccessTools.PropertySetter(typeof(TMP_Text), "text");
                if (tmpTextSetter != null)
                {
                    _harmony.Patch(
                        tmpTextSetter,
                        prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "SanitizeTextSetterPrefix")
                    );
                }

                var uiTextSetter = AccessTools.PropertySetter(typeof(Text), "text");
                if (uiTextSetter != null)
                {
                    _harmony.Patch(
                        uiTextSetter,
                        prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "SanitizeTextSetterPrefix")
                    );
                }

                foreach (var method in AccessTools.GetDeclaredMethods(typeof(TMP_Text)).Where(m => m.Name == "SetText"))
                {
                    var parameters = method.GetParameters();
                    if (parameters.Length > 0 && parameters[0].ParameterType == typeof(string))
                    {
                        _harmony.Patch(
                            method,
                            prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "SanitizeSetTextPrefix")
                        );
                    }
                }

                var localizedTextType = FindType("PajamaLlama.Plugins.I2Language.LocalizedText");
                if (localizedTextType != null)
                {
                    var updateTextMethod = AccessTools.Method(localizedTextType, "UpdateText", Type.EmptyTypes, null);
                    if (updateTextMethod != null)
                    {
                        _harmony.Patch(
                            updateTextMethod,
                            postfix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "LocalizedTextUpdateTextPostfix")
                        );
                    }
                }

                var textFieldType = FindTypeByShortName("TextField");
                if (textFieldType != null)
                {
                    foreach (var method in AccessTools.GetDeclaredMethods(textFieldType).Where(m => m.Name == "SetText"))
                    {
                        var parameters = method.GetParameters();
                        if (parameters.Length > 0 && parameters[0].ParameterType == typeof(string))
                        {
                            _harmony.Patch(
                                method,
                                prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "TextFieldSetTextPrefix"),
                                postfix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "TextFieldSetTextPostfix")
                            );
                        }
                    }
                }

                var recipeItemDisplayType = FindTypeByShortName("RecipeItemDisplay");
                if (recipeItemDisplayType != null)
                {
                    foreach (var method in AccessTools.GetDeclaredMethods(recipeItemDisplayType).Where(m => m.Name == "Initialize"))
                    {
                        var parameters = method.GetParameters();
                        if (parameters.Length == 4 &&
                            parameters[0].ParameterType.Name == "Recipe" &&
                            parameters[1].ParameterType.Name == "ItemProperties" &&
                            parameters[2].ParameterType == typeof(bool) &&
                            parameters[3].ParameterType == typeof(string))
                        {
                            _harmony.Patch(
                                method,
                                prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "RecipeItemDisplayInitializePrefix"),
                                postfix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "RecipeItemDisplayInitializePostfix")
                            );
                        }
                    }
                }

                var localizationManagerType = FindType("I2.Loc.LocalizationManager");
                if (localizationManagerType != null)
                {
                    var applyRTLfixMethod = AccessTools.Method(localizationManagerType, "ApplyRTLfix",
                        new Type[] { typeof(string), typeof(int), typeof(bool) });
                    if (applyRTLfixMethod != null)
                    {
                        _harmony.Patch(
                            applyRTLfixMethod,
                            prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "ApplyRTLfixPrefix"),
                            postfix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "ApplyRTLfixPostfix")
                        );
                        Logger.LogInfo("Hooked LocalizationManager.ApplyRTLfix for token protection.");
                    }
                }

                Logger.LogInfo("Installed direct TMP/UI text hooks.");
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not install direct text hooks: " + ex);
            }
        }

        private void TryApplyArabicFontFallback()
        {
            if (_fontFallbackApplied)
            {
                return;
            }

            try
            {
                _osArabicFont = Font.CreateDynamicFontFromOSFont(new[] { "Tahoma", "Arial", "Segoe UI" }, 36);
                if (_osArabicFont == null)
                {
                    Logger.LogWarning("Could not create Arabic OS font fallback.");
                    return;
                }

                _arabicTmpFallback = CreateDynamicTmpFontAsset(_osArabicFont);
                if (_arabicTmpFallback == null)
                {
                    Logger.LogWarning("Could not create TMP fallback asset.");
                    return;
                }

                _arabicTmpFallback.name = "ArabicRuntimeFallback";
                _arabicTmpFallback.atlasPopulationMode = AtlasPopulationMode.Dynamic;
                _arabicTmpFallback.TryAddCharacters("ابتثجحخدذرزسشصضطظعغفقكلمنهويئىةآأإؤءءآأإؤء0123456789،؛؟!()[]{}<>%+-=*/.:_ ");

                if (TMP_Settings.fallbackFontAssets == null)
                {
                    TMP_Settings.fallbackFontAssets = new System.Collections.Generic.List<TMP_FontAsset>();
                }

                if (!TMP_Settings.fallbackFontAssets.Contains(_arabicTmpFallback))
                {
                    TMP_Settings.fallbackFontAssets.Add(_arabicTmpFallback);
                }

                var allFonts = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
                foreach (var font in allFonts)
                {
                    if (font == null) continue;
                    if (font.fallbackFontAssetTable == null)
                    {
                        font.fallbackFontAssetTable = new System.Collections.Generic.List<TMP_FontAsset>();
                    }
                    if (!font.fallbackFontAssetTable.Contains(_arabicTmpFallback))
                    {
                        font.fallbackFontAssetTable.Add(_arabicTmpFallback);
                    }
                }

                ApplyArabicFallbackToLiveText();
                _fontFallbackApplied = true;
                Logger.LogInfo("Arabic TMP fallback font applied.");
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not apply Arabic TMP fallback font: " + ex);
            }
        }

        private TMP_FontAsset CreateDynamicTmpFontAsset(Font font)
        {
            string[] familyNames = { "Tahoma", "Arial", "Segoe UI" };

            foreach (var familyName in familyNames)
            {
                try
                {
                    var assetFromFamily = TMP_FontAsset.CreateFontAsset(familyName, "Regular", 90);
                    if (assetFromFamily != null)
                    {
                        assetFromFamily.atlasPopulationMode = AtlasPopulationMode.DynamicOS;
                        Logger.LogInfo("Created TMP font asset from OS family: " + familyName);
                        return assetFromFamily;
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogWarning("CreateFontAsset family overload failed for " + familyName + ": " + ex.Message);
                }
            }

            try
            {
                var asset = TMP_FontAsset.CreateFontAsset(
                    font, 90, 9, GlyphRenderMode.SDFAA, 1024, 1024, AtlasPopulationMode.Dynamic, true
                );
                if (asset != null)
                {
                    Logger.LogInfo("Created TMP font asset from UnityEngine.Font dynamic overload.");
                    return asset;
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning("CreateFontAsset overload failed: " + ex.Message);
            }

            try
            {
                var basicAsset = TMP_FontAsset.CreateFontAsset(font);
                if (basicAsset != null)
                {
                    Logger.LogInfo("Created TMP font asset from UnityEngine.Font simple overload.");
                }
                return basicAsset;
            }
            catch (Exception ex)
            {
                Logger.LogWarning("CreateFontAsset simple overload failed: " + ex.Message);
                return null;
            }
        }

        private IEnumerator FontOverrideLoop()
        {
            for (var i = 0; i < 120; i++)
            {
                ApplyArabicFallbackToLiveText();
                if (i < 50)
                {
                    yield return new WaitForSeconds(0.1f);
                }
                else
                {
                    yield return new WaitForSeconds(0.5f);
                }
            }
        }

        private void ApplyArabicFallbackToLiveText()
        {
            try
            {
                var arabicActive = IsArabicLanguageActive();
                var tmpTexts = Resources.FindObjectsOfTypeAll<TMP_Text>();
                var tmpUpdated = 0;
                var tmpRestored = 0;
                foreach (var text in tmpTexts)
                {
                    if (text == null)
                    {
                        continue;
                    }

                    CaptureOriginalState(text);

                    if (arabicActive && _arabicTmpFallback != null)
                    {
                        var sanitizedText = SanitizeVisibleText(text.text);
                        if (!string.Equals(sanitizedText, text.text, StringComparison.Ordinal))
                        {
                            text.text = sanitizedText;
                        }

                        ApplyArabicLayout(text);

                        if (text.font != _arabicTmpFallback)
                        {
                            text.font = _arabicTmpFallback;
                            tmpUpdated++;
                        }
                    }
                    else
                    {
                        if (RestoreOriginalState(text))
                        {
                            tmpRestored++;
                        }
                    }

                    text.havePropertiesChanged = true;
                    text.ForceMeshUpdate(true, true);
                }

                var uiTexts = Resources.FindObjectsOfTypeAll<Text>();
                var uiUpdated = 0;
                var uiRestored = 0;
                foreach (var text in uiTexts)
                {
                    if (text == null)
                    {
                        continue;
                    }

                    CaptureOriginalState(text);

                    if (arabicActive && _osArabicFont != null)
                    {
                        var sanitizedUiText = SanitizeVisibleText(text.text);
                        if (!string.Equals(sanitizedUiText, text.text, StringComparison.Ordinal))
                        {
                            text.text = sanitizedUiText;
                        }

                        ApplyArabicLayout(text);

                        if (text.font != _osArabicFont)
                        {
                            text.font = _osArabicFont;
                            uiUpdated++;
                        }
                    }
                    else
                    {
                        if (RestoreOriginalState(text))
                        {
                            uiRestored++;
                        }
                    }
                }

                if (tmpUpdated > 0 || uiUpdated > 0 || tmpRestored > 0 || uiRestored > 0)
                {
                    Logger.LogInfo(
                        (arabicActive ? "Applied Arabic font override to TMP/UI texts: " : "Restored original TMP/UI fonts: ")
                        + tmpUpdated + "/" + uiUpdated
                        + " | restored " + tmpRestored + "/" + uiRestored
                    );
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not apply fallback to live text objects: " + ex.Message);
            }
        }

        private void CaptureOriginalState(TMP_Text text)
        {
            if (text == null)
            {
                return;
            }

            var id = text.GetInstanceID();
            if (_tmpTextStates.ContainsKey(id))
            {
                return;
            }

            _tmpTextStates[id] = new TmpTextState
            {
                Font = text.font,
                Alignment = text.alignment
            };
        }

        private void CaptureOriginalState(Text text)
        {
            if (text == null)
            {
                return;
            }

            var id = text.GetInstanceID();
            if (_uiTextStates.ContainsKey(id))
            {
                return;
            }

            _uiTextStates[id] = new UiTextState
            {
                Font = text.font,
                Alignment = text.alignment
            };
        }

        private bool RestoreOriginalState(TMP_Text text)
        {
            if (text == null)
            {
                return false;
            }

            TmpTextState state;
            if (!_tmpTextStates.TryGetValue(text.GetInstanceID(), out state) || state == null)
            {
                return false;
            }

            var changed = false;
            if (text.font != state.Font)
            {
                text.font = state.Font;
                changed = true;
            }

            if (text.alignment != state.Alignment)
            {
                text.alignment = state.Alignment;
                changed = true;
            }

            if (changed)
            {
                text.havePropertiesChanged = true;
                text.ForceMeshUpdate(true, true);
            }

            return changed;
        }

        private bool RestoreOriginalState(Text text)
        {
            if (text == null)
            {
                return false;
            }

            UiTextState state;
            if (!_uiTextStates.TryGetValue(text.GetInstanceID(), out state) || state == null)
            {
                return false;
            }

            var changed = false;
            if (text.font != state.Font)
            {
                text.font = state.Font;
                changed = true;
            }

            if (text.alignment != state.Alignment)
            {
                text.alignment = state.Alignment;
                changed = true;
            }

            return changed;
        }

        private int PatchSource(object source)
        {
            var languagesList = GetMemberValue(source, "mLanguages") as IList;
            var termsList = GetMemberValue(source, "mTerms") as IList;
            if (languagesList == null || termsList == null)
            {
                return 0;
            }

            var arabicIndex = EnsureArabicLanguage(languagesList, termsList);
            if (arabicIndex < 0)
            {
                return 0;
            }

            var patched = 0;
            foreach (var term in termsList)
            {
                var key = GetMemberValue(term, "Term") as string;
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                string arabic;
                if (!_translations.TryGetValue(key, out arabic))
                {
                    continue;
                }

                var languages = GetMemberValue(term, "Languages") as string[];
                if (languages == null)
                {
                    continue;
                }

                if (languages.Length <= arabicIndex)
                {
                    Array.Resize(ref languages, arabicIndex + 1);
                    SetMemberValue(term, "Languages", languages);
                }

                languages[arabicIndex] = PrepareArabicText(arabic);
                patched++;
            }

            return patched;
        }

        private int EnsureArabicLanguage(IList languagesList, IList termsList)
        {
            for (var i = 0; i < languagesList.Count; i++)
            {
                var item = languagesList[i];
                var name = (GetMemberValue(item, "Name") as string) ?? string.Empty;
                var code = (GetMemberValue(item, "Code") as string) ?? string.Empty;
                if (string.Equals(name, "Arabic", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(code, "ar", StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }
            }

            if (languagesList.Count == 0)
            {
                return -1;
            }

            var languageType = languagesList[0].GetType();
            object newLanguage;
            try
            {
                newLanguage = Activator.CreateInstance(languageType);
            }
            catch (Exception ex)
            {
                Logger.LogError("Failed to create Arabic language entry: " + ex);
                return -1;
            }

            SetMemberValue(newLanguage, "Name", "Arabic");
            SetMemberValue(newLanguage, "Code", "ar");
            languagesList.Add(newLanguage);

            var newIndex = languagesList.Count - 1;
            foreach (var term in termsList)
            {
                var languages = GetMemberValue(term, "Languages") as string[];
                if (languages == null)
                {
                    continue;
                }

                if (languages.Length <= newIndex)
                {
                    Array.Resize(ref languages, newIndex + 1);
                    SetMemberValue(term, "Languages", languages);
                }
            }

            Logger.LogInfo("Added Arabic language slot at index " + newIndex);
            return newIndex;
        }

        private void SetLanguageToArabic(Type localizationManagerType)
        {
            try
            {
                var currentLanguage = localizationManagerType.GetProperty("CurrentLanguage", BindingFlags.Public | BindingFlags.Static);
                if (currentLanguage != null && currentLanguage.CanWrite)
                {
                    currentLanguage.SetValue(null, "Arabic", null);
                }

                var setLanguageAndCode = localizationManagerType.GetMethod("SetLanguageAndCode", BindingFlags.Public | BindingFlags.Static);
                if (setLanguageAndCode != null)
                {
                    var parameters = setLanguageAndCode.GetParameters();
                    if (parameters.Length >= 2)
                    {
                        var args = new object[parameters.Length];
                        args[0] = "Arabic";
                        args[1] = "ar";
                        for (var i = 2; i < args.Length; i++)
                        {
                            args[i] = parameters[i].HasDefaultValue ? parameters[i].DefaultValue : null;
                        }

                        setLanguageAndCode.Invoke(null, args);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not force Arabic as current language: " + ex.Message);
            }
        }

        private void TriggerRefresh(Type localizationManagerType)
        {
            try
            {
                var updateSources = localizationManagerType.GetMethod("UpdateSources", BindingFlags.Public | BindingFlags.Static);
                if (updateSources != null)
                {
                    updateSources.Invoke(null, null);
                }

                var localizeAll = localizationManagerType.GetMethod("LocalizeAll", BindingFlags.Public | BindingFlags.Static);
                if (localizeAll != null)
                {
                    var parameters = localizeAll.GetParameters();
                    object[] args = parameters.Length == 1 ? new object[] { true } : null;
                    localizeAll.Invoke(null, args);
                }

                RelocalizeLiveComponents();
                RefreshKnownUiPresenters();
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not trigger localization refresh: " + ex.Message);
            }
        }

        private void RelocalizeLiveComponents()
        {
            try
            {
                var localizeType = FindType("I2.Loc.Localize");
                if (localizeType == null)
                {
                    return;
                }

                var localizeObjects = Resources.FindObjectsOfTypeAll(localizeType);
                var onLocalize = localizeType.GetMethod("OnLocalize", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
                var onLocalizeBool = localizeType.GetMethod("OnLocalize", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(bool) }, null);
                var localizeMethod = localizeType.GetMethod("Localize", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
                var localizeBool = localizeType.GetMethod("Localize", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(bool) }, null);

                var refreshed = 0;
                foreach (var obj in localizeObjects)
                {
                    if (obj == null)
                    {
                        continue;
                    }

                    try
                    {
                        if (onLocalizeBool != null)
                        {
                            onLocalizeBool.Invoke(obj, new object[] { true });
                        }
                        else if (onLocalize != null)
                        {
                            onLocalize.Invoke(obj, null);
                        }
                        else if (localizeBool != null)
                        {
                            localizeBool.Invoke(obj, new object[] { true });
                        }
                        else if (localizeMethod != null)
                        {
                            localizeMethod.Invoke(obj, null);
                        }
                        else
                        {
                            continue;
                        }

                        refreshed++;
                    }
                    catch
                    {
                    }
                }

                if (refreshed > 0)
                {
                    Logger.LogInfo("Relocalized live I2 components: " + refreshed);
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not relocalize live I2 components: " + ex.Message);
            }
        }

        private void RefreshKnownUiPresenters()
        {
            try
            {
                var refreshed = 0;
                refreshed += InvokeOnLiveObjectsByTypeName(
                    "Scr_UIConstructionMenu",
                    "RedrawUI",
                    "RebuildPanel",
                    "UpdatePanel",
                    "UpdatePanels",
                    "Refresh",
                    "RefreshUI"
                );
                refreshed += InvokeOnLiveObjectsByTypeName(
                    "LocalizedText",
                    "UpdateText",
                    "OnLocalize",
                    "Localize",
                    "ApplyLocalizationParams",
                    "Refresh",
                    "RefreshUI"
                );

                if (refreshed > 0)
                {
                    Logger.LogInfo("Refreshed known UI presenters: " + refreshed);
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Could not refresh known UI presenters: " + ex.Message);
            }
        }

        private int InvokeOnLiveObjectsByTypeName(string typeName, params string[] methodNames)
        {
            var type = FindTypeByShortName(typeName);
            if (type == null)
            {
                return 0;
            }

            var objects = Resources.FindObjectsOfTypeAll(type);
            var invoked = 0;
            foreach (var obj in objects)
            {
                if (obj == null)
                {
                    continue;
                }

                foreach (var methodName in methodNames)
                {
                    var method = type.GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
                    if (method == null)
                    {
                        continue;
                    }

                    try
                    {
                        method.Invoke(obj, null);
                        invoked++;
                        break;
                    }
                    catch
                    {
                    }
                }
            }

            return invoked;
        }

        private static string PrepareArabicText(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return value;
            }

            var normalized = value
                .Replace("\\r\\n", "\n")
                .Replace("\\n", "\n")
                .Replace("\\t", "\t");

            normalized = normalized.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&quot;", "\"");
            normalized = FormattingTagRegex.Replace(normalized, string.Empty);
            normalized = DirectionalControlCharsRegex.Replace(normalized, string.Empty);
            normalized = ReversedBracketBraceTokenRegex.Replace(
                normalized,
                match => "{[" + new string(match.Groups[1].Value.Reverse().ToArray()) + "]}"
            );
            normalized = ReversedBraceTokenRegex.Replace(normalized, "{$1}");
            normalized = NormalizeBraceTokens(normalized);
            normalized = NormalizeBracketBraceTokens(normalized);

            return normalized.Trim();
        }

        private static readonly Regex BidiCorruptedBracketTokenRegex = new Regex(
            @"\{([A-Z]+)\]:\[([0-9]+)\}",
            RegexOptions.Compiled
        );

        private static string SanitizeVisibleText(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return value;
            }

            if (IsArabicLanguageActive())
            {
                return FixCorruptedTokens(value);
            }

            var cleaned = value;
            cleaned = FormattingTagRegex.Replace(cleaned, string.Empty);
            cleaned = ReversedFormattingMarkerRegex.Replace(cleaned, string.Empty);
            cleaned = SpriteTagRegex.Replace(cleaned, string.Empty);
            cleaned = ReversedSpriteTagRegex.Replace(cleaned, string.Empty);
            cleaned = DirectionalControlCharsRegex.Replace(cleaned, string.Empty);
            cleaned = BidiCorruptedBracketTokenRegex.Replace(cleaned, match =>
                "{[" + new string(match.Groups[1].Value.Reverse().ToArray()) + ":" + new string(match.Groups[2].Value.Reverse().ToArray()) + "]}"
            );
            cleaned = ReversedBracketBraceTokenRegex.Replace(
                cleaned,
                match => "{[" + new string(match.Groups[1].Value.Reverse().ToArray()) + "]}"
            );
            cleaned = ReversedBraceTokenRegex.Replace(cleaned, "{$1}");
            cleaned = NormalizeBraceTokens(cleaned);
            cleaned = NormalizeBracketBraceTokens(cleaned);
            cleaned = FixCorruptedPercentTokens(cleaned);
            cleaned = cleaned.Replace(">b/<", string.Empty).Replace(">b<", string.Empty);
            cleaned = cleaned.Replace(">i/<", string.Empty).Replace(">i<", string.Empty);
            cleaned = cleaned.Replace("\"=eman etirps<", string.Empty).Replace(">\"ytilauq\"=eman etirps<", string.Empty);
            return cleaned;
        }

        private static Dictionary<string, string> _rtlProtectedTokens;

        private static readonly Regex RtlProtectAllTokens = new Regex(
            @"(\{\[([A-Z0-9_:,\.\-]+)\]\})|(%([A-Z][A-Z0-9_]+)%)",
            RegexOptions.Compiled
        );

        private static bool ApplyRTLfixPrefix(ref string line)
        {
            if (!IsArabicLanguageActive() || string.IsNullOrEmpty(line))
            {
                return true;
            }

            var map = new Dictionary<string, string>();
            int counter = 0;

            line = RtlProtectAllTokens.Replace(line, match =>
            {
                string key = "\u0003" + counter + "\u0003";
                map[key] = match.Value;
                counter++;
                return key;
            });

            if (map.Count > 0)
            {
                _rtlProtectedTokens = map;
            }

            return true;
        }

        private static void ApplyRTLfixPostfix(ref string __result)
        {
            var map = _rtlProtectedTokens;
            if (map == null || map.Count == 0)
            {
                return;
            }

            _rtlProtectedTokens = null;

            try
            {
                __result = DirectionalControlCharsRegex.Replace(__result, string.Empty);
                foreach (var kvp in map)
                {
                    __result = __result.Replace(kvp.Key, kvp.Value);
                }
            }
            catch
            {
            }
        }

        private static string FixCorruptedTokens(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return text;
            }

            text = DirectionalControlCharsRegex.Replace(text, string.Empty);
            text = ReversedBracketBraceTokenRegex.Replace(
                text,
                match => "{[" + new string(match.Groups[1].Value.Reverse().ToArray()) + "]}"
            );
            text = ReversedBraceTokenRegex.Replace(text, "{$1}");
            text = NormalizeBraceTokens(text);
            text = NormalizeBracketBraceTokens(text);
            text = FixCorruptedPercentTokens(text);
            return text;
        }

        private static readonly Regex CorruptedPercentTokenEndRegex = new Regex(
            @"([A-Z][A-Z0-9_]+)%%",
            RegexOptions.Compiled
        );
        private static readonly Regex ReversedPercentTokenRegex = new Regex(
            @"%([A-Z0-9_]+)%",
            RegexOptions.Compiled
        );
        private static readonly HashSet<string> KnownPercentTokens = new HashSet<string>(StringComparer.Ordinal)
        {
            "NAME", "FIRSTNAME", "LASTNAME", "NICKNAME", "COMMUNITY",
            "SALVAGERETURNS", "HEALTHVITAL", "STORAGEAMOUNT", "WATERSTORAGEAMOUNT",
            "RESEARCH", "RECIPE", "LANDMARKNAME", "HOTKEY", "BIOME_COST", "DAY"
        };

        private static string FixCorruptedPercentTokens(string text)
        {
            text = CorruptedPercentTokenEndRegex.Replace(text, match =>
            {
                var token = match.Groups[1].Value;
                if (KnownPercentTokens.Contains(token))
                {
                    return "%" + token + "%";
                }
                return match.Value;
            });

            text = ReversedPercentTokenRegex.Replace(text, match =>
            {
                var token = match.Groups[1].Value;
                if (token.Length >= 3 && LooksLikeReversedToken(token))
                {
                    var reversed = new string(token.Reverse().ToArray());
                    if (KnownPercentTokens.Contains(reversed))
                    {
                        return "%" + reversed + "%";
                    }
                }
                return match.Value;
            });

            return text;
        }

        private static string NormalizeBraceTokens(string value)
        {
            return BraceTokenRegex.Replace(
                value,
                match =>
                {
                    var token = match.Groups[1].Value;
                    if (string.IsNullOrEmpty(token))
                    {
                        return match.Value;
                    }

                    var normalizedToken = LooksLikeReversedToken(token)
                        ? new string(token.Reverse().ToArray())
                        : token;

                    return "{" + normalizedToken + "}";
                }
            );
        }

        private static bool LooksLikeReversedToken(string token)
        {
            if (token.Length < 6)
            {
                return false;
            }

            if (token.Contains("_"))
            {
                return true;
            }

            return token.EndsWith("NOIT", StringComparison.Ordinal)
                || token.EndsWith("EMIT", StringComparison.Ordinal)
                || token.EndsWith("ETUBIRTTA", StringComparison.Ordinal)
                || token.EndsWith("TNEMNGISSA", StringComparison.Ordinal)
                || token.EndsWith("GNIDLIUB", StringComparison.Ordinal)
                || token.EndsWith("SETUNIM", StringComparison.Ordinal);
        }

        private static string NormalizeBracketBraceTokens(string value)
        {
            return BracketBraceTokenRegex.Replace(
                value,
                match =>
                {
                    var token = match.Groups[1].Value;
                    if (string.IsNullOrEmpty(token))
                    {
                        return match.Value;
                    }

                    var normalizedToken = LooksLikeReversedToken(token)
                        ? new string(token.Reverse().ToArray())
                        : token;

                    return "{[" + normalizedToken + "]}";
                }
            );
        }

        private static void ApplyArabicLayout(TMP_Text text)
        {
            if (text == null || string.IsNullOrEmpty(text.text))
            {
                return;
            }

            if (!ContainsArabic(text.text) || !IsArabicLanguageActive())
            {
                return;
            }

            switch (text.alignment)
            {
                case TextAlignmentOptions.TopRight:
                    text.alignment = TextAlignmentOptions.TopLeft;
                    break;
                case TextAlignmentOptions.Right:
                    text.alignment = TextAlignmentOptions.Left;
                    break;
                case TextAlignmentOptions.BottomRight:
                    text.alignment = TextAlignmentOptions.BottomLeft;
                    break;
                case TextAlignmentOptions.BaselineRight:
                    text.alignment = TextAlignmentOptions.BaselineLeft;
                    break;
                case TextAlignmentOptions.MidlineRight:
                    text.alignment = TextAlignmentOptions.MidlineLeft;
                    break;
                case TextAlignmentOptions.CaplineRight:
                    text.alignment = TextAlignmentOptions.CaplineLeft;
                    break;
            }
        }

        private static void ApplyArabicLayout(Text text)
        {
            if (text == null || string.IsNullOrEmpty(text.text))
            {
                return;
            }

            if (!ContainsArabic(text.text) || !IsArabicLanguageActive())
            {
                return;
            }

            switch (text.alignment)
            {
                case TextAnchor.UpperRight:
                    text.alignment = TextAnchor.UpperLeft;
                    break;
                case TextAnchor.MiddleRight:
                    text.alignment = TextAnchor.MiddleLeft;
                    break;
                case TextAnchor.LowerRight:
                    text.alignment = TextAnchor.LowerLeft;
                    break;
            }
        }

        private static bool ContainsArabic(string text)
        {
            foreach (var ch in text)
            {
                if ((ch >= '\u0600' && ch <= '\u06FF') || (ch >= '\u0750' && ch <= '\u077F') || (ch >= '\u08A0' && ch <= '\u08FF'))
                {
                    return true;
                }
            }

            return false;
        }

        private static void SanitizeTextSetterPrefix(ref string value)
        {
            if (IsArabicLanguageActive())
            {
                value = FixCorruptedTokens(value);
            }
        }

        private static void SanitizeSetTextPrefix(ref string sourceText)
        {
            if (IsArabicLanguageActive())
            {
                sourceText = FixCorruptedTokens(sourceText);
            }
        }

        private static void LocalizedTextUpdateTextPostfix(object __instance)
        {
            if (!IsArabicLanguageActive() || __instance == null)
            {
                return;
            }

            try
            {
                var instanceType = __instance.GetType();
                var uiTextField = instanceType.GetField("_targetText", BindingFlags.Instance | BindingFlags.NonPublic);
                var tmpTextField = instanceType.GetField("_targetTextMeshPro", BindingFlags.Instance | BindingFlags.NonPublic);

                var uiText = uiTextField != null ? uiTextField.GetValue(__instance) as Text : null;
                if (uiText != null)
                {
                    var sanitized = SanitizeVisibleText(uiText.text);
                    if (!string.Equals(sanitized, uiText.text, StringComparison.Ordinal))
                    {
                        uiText.text = sanitized;
                    }

                    ApplyArabicLayout(uiText);
                }

                var tmpText = tmpTextField != null ? tmpTextField.GetValue(__instance) as TMP_Text : null;
                if (tmpText != null)
                {
                    var sanitized = SanitizeVisibleText(tmpText.text);
                    if (!string.Equals(sanitized, tmpText.text, StringComparison.Ordinal))
                    {
                        tmpText.text = sanitized;
                    }

                    ApplyArabicLayout(tmpText);
                    tmpText.havePropertiesChanged = true;
                    tmpText.ForceMeshUpdate(true, true);
                }
            }
            catch
            {
            }
        }

        private static void TextFieldSetTextPrefix(ref string text)
        {
            if (IsArabicLanguageActive())
            {
                text = FixCorruptedTokens(text);
            }
        }

        private static void TextFieldSetTextPostfix(object __instance)
        {
            if (!IsArabicLanguageActive() || __instance == null)
            {
                return;
            }

            try
            {
                var instanceType = __instance.GetType();
                var textField = instanceType.GetField("_text", BindingFlags.Instance | BindingFlags.NonPublic);
                var tmpText = textField != null ? textField.GetValue(__instance) as TMP_Text : null;
                if (tmpText == null)
                {
                    return;
                }

                var sanitized = SanitizeVisibleText(tmpText.text);
                if (!string.Equals(sanitized, tmpText.text, StringComparison.Ordinal))
                {
                    tmpText.text = sanitized;
                }

                ApplyArabicLayout(tmpText);
                tmpText.havePropertiesChanged = true;
                tmpText.ForceMeshUpdate(true, true);
            }
            catch
            {
            }
        }

        private static void RecipeItemDisplayInitializePrefix(ref string amount)
        {
            if (IsArabicLanguageActive())
            {
                amount = FixCorruptedTokens(amount);
            }
        }

        private static void RecipeItemDisplayInitializePostfix(object __instance)
        {
            if (!IsArabicLanguageActive() || __instance == null)
            {
                return;
            }

            try
            {
                var instanceType = __instance.GetType();
                var amountTextField = instanceType.GetField("_amountText", BindingFlags.Instance | BindingFlags.NonPublic);
                var nameTextField = instanceType.GetField("_nameText", BindingFlags.Instance | BindingFlags.NonPublic);

                var amountText = amountTextField != null ? amountTextField.GetValue(__instance) as TMP_Text : null;
                if (amountText != null)
                {
                    var sanitizedAmount = SanitizeVisibleText(amountText.text);
                    if (!string.Equals(sanitizedAmount, amountText.text, StringComparison.Ordinal))
                    {
                        amountText.text = sanitizedAmount;
                    }

                    ApplyArabicLayout(amountText);
                    amountText.havePropertiesChanged = true;
                    amountText.ForceMeshUpdate(true, true);
                }

                var nameText = nameTextField != null ? nameTextField.GetValue(__instance) as TMP_Text : null;
                if (nameText != null)
                {
                    var sanitizedName = SanitizeVisibleText(nameText.text);
                    if (!string.Equals(sanitizedName, nameText.text, StringComparison.Ordinal))
                    {
                        nameText.text = sanitizedName;
                    }

                    ApplyArabicLayout(nameText);
                    nameText.havePropertiesChanged = true;
                    nameText.ForceMeshUpdate(true, true);
                }
            }
            catch
            {
            }
        }

        private static bool IsArabicLanguageActive()
        {
            if (_instance == null)
            {
                return false;
            }

            if (string.Equals(_instance._lastObservedLanguage, "Arabic", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(_instance._lastObservedLanguage, "ar", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            try
            {
                var localizationManagerType = FindType("I2.Loc.LocalizationManager");
                if (localizationManagerType == null)
                {
                    return false;
                }

                var currentLanguage = localizationManagerType.GetProperty("CurrentLanguage", BindingFlags.Public | BindingFlags.Static);
                var current = currentLanguage != null ? currentLanguage.GetValue(null, null) as string : null;
                return string.Equals(current, "Arabic", StringComparison.OrdinalIgnoreCase) ||
                       string.Equals(current, "ar", StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                return false;
            }
        }

        private static List<object> GetSources(Type localizationManagerType)
        {
            var sourcesProperty = localizationManagerType.GetProperty("Sources", BindingFlags.Public | BindingFlags.Static);
            if (sourcesProperty != null)
            {
                var value = sourcesProperty.GetValue(null, null) as IEnumerable;
                if (value != null)
                {
                    return value.Cast<object>().ToList();
                }
            }

            var sourcesField = localizationManagerType.GetField("Sources", BindingFlags.Public | BindingFlags.Static);
            if (sourcesField != null)
            {
                var value = sourcesField.GetValue(null) as IEnumerable;
                if (value != null)
                {
                    return value.Cast<object>().ToList();
                }
            }

            return new List<object>();
        }

        private static Type FindType(string fullName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var type = assembly.GetType(fullName, false);
                if (type != null)
                {
                    return type;
                }
            }

            return null;
        }

        private static Type FindTypeByShortName(string shortName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try
                {
                    types = assembly.GetTypes();
                }
                catch
                {
                    continue;
                }

                foreach (var type in types)
                {
                    if (type == null)
                    {
                        continue;
                    }

                    if (string.Equals(type.Name, shortName, StringComparison.Ordinal))
                    {
                        return type;
                    }
                }
            }

            return null;
        }

        private static object GetMemberValue(object target, string name)
        {
            if (target == null)
            {
                return null;
            }

            var type = target.GetType();
            var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
            if (field != null)
            {
                return field.GetValue(target);
            }

            var property = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
            if (property != null)
            {
                return property.GetValue(target, null);
            }

            return null;
        }

        private static void SetMemberValue(object target, string name, object value)
        {
            if (target == null)
            {
                return;
            }

            var type = target.GetType();
            var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
            if (field != null)
            {
                field.SetValue(target, value);
                return;
            }

            var property = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
            if (property != null && property.CanWrite)
            {
                property.SetValue(target, value, null);
            }
        }

        [Serializable]
        private class TranslationPayload
        {
            public List<TranslationEntry> entries;
        }

        [Serializable]
        private class TranslationEntry
        {
            public string key;
            public string Arabic;
        }
    }
}
