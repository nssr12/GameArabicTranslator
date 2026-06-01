using UnityEngine;
using UnityEditor;
using System.IO;

public static class BuildArabicBundle
{
    [MenuItem("🌍 Arabic Mod/Build Arabic Font Bundle")]
    public static void Build()
    {
        // اسم الـ AssetBundle المطلوب
        const string bundleName = "arabic_font.bundle";

        // الـ asset الرئيسي
        string assetPath = "Assets/Fonts/segoeui SDF Arabic.asset";
        if (!File.Exists(assetPath))
        {
            EditorUtility.DisplayDialog(
                "Arabic Font Bundle",
                "❌ لم يُعثر على:\n" + assetPath + "\n\nتأكّد من وجود الملف في Assets/Fonts/",
                "OK");
            return;
        }

        // عيّن assetBundleName على الـ asset (TMP_FontAsset)
        var importer = AssetImporter.GetAtPath(assetPath);
        importer.assetBundleName = bundleName;
        importer.SaveAndReimport();

        // مجلد الإخراج
        string outDir = "Assets/../Build";
        Directory.CreateDirectory(outDir);

        // ابنِ
        var manifest = BuildPipeline.BuildAssetBundles(
            outDir,
            BuildAssetBundleOptions.None,
            BuildTarget.StandaloneWindows64);

        if (manifest == null)
        {
            EditorUtility.DisplayDialog("Arabic Font Bundle", "❌ فشل البناء — راجع Console.", "OK");
            return;
        }

        string bundleFile = Path.Combine(outDir, bundleName);
        var fullPath = Path.GetFullPath(bundleFile);
        var size = new FileInfo(fullPath).Length / 1024;
        Debug.Log("[ArabicFontBundle] ✓ Built: " + fullPath + "  (" + size + " KB)");

        EditorUtility.DisplayDialog(
            "Arabic Font Bundle",
            "✅ تم البناء بنجاح!\n\n"
            + "الملف: " + fullPath + "\n"
            + "الحجم: " + size + " KB\n\n"
            + "انسخه إلى:\n"
            + "<game>/BepInEx/config/ArabicGameTranslator/fonts/arabic_font.bundle",
            "OK");

        // افتح المجلد في Explorer
        EditorUtility.RevealInFinder(fullPath);
    }
}
