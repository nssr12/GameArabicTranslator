import os

cs_path = r'C:\Users\nssr1\Desktop\ArabicGameTranslatorMVP\mods\FlotsamArabicRuntime\FlotsamArabicRuntime.cs'
with open(cs_path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '                var payload = JsonConvert.DeserializeObject<TranslationPayload>(File.ReadAllText(path));\n                if (payload == null || payload.entries == null)\n                {\n                    Logger.LogWarning("Translations payload is empty.");\n                    return;\n                }'

new = '''                var rawJson = File.ReadAllText(path);
                TranslationPayload payload = null;
                
                // Try entries format first
                try { payload = JsonConvert.DeserializeObject<TranslationPayload>(rawJson); } catch {}
                
                // If entries is empty, try I2Languages full format
                if (payload == null || payload.entries == null || payload.entries.Count == 0)
                {
                    try
                    {
                        var i2Data = JsonConvert.DeserializeObject<dynamic>(rawJson);
                        var mSource = i2Data?.mSource;
                        var mTerms = mSource?.mTerms;
                        var termsArray = mTerms?.Array;
                        if (termsArray != null)
                        {
                            payload = new TranslationPayload { entries = new List<TranslationEntry>() };
                            foreach (var term in termsArray)
                            {
                                var key = (string)term.Term;
                                var langs = term.Languages?.Array;
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
                }'''

if old in content:
    content = content.replace(old, new)
    with open(cs_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Modified LoadTranslations to support both formats')
else:
    print('Could not find target code block')
    # Show context around LoadTranslations
    idx = content.find('LoadTranslations')
    if idx >= 0:
        print('Context:')
        print(content[idx:idx+500])
