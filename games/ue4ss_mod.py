"""
games/ue4ss_mod.py — مولّد UE4SS Arabic Translator mod.

يُنشئ ويُحدِّث المجلد:
    <game_path>/<GameName>/Binaries/Win64/Mods/UE4ArabicTranslator/

يُصدِّر:
    - dict/translations.txt من الكاش (دمج هرمي)
    - يُحدِّث mods.txt لتفعيل الـ mod
    - ينسخ UE4SS الأساسي (UE4SS.dll, dwmapi.dll, settings) من tools/UE4SS

يقرأ:
    - dict/missing.txt — نصوص جديدة وجدتها اللعبة → تُضاف لـ cache كـ pending
"""
from __future__ import annotations

import os
import shutil
from typing import Tuple, List

_BASE       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODS_DIR   = os.path.join(_BASE, "mods")
_TOOLS_DIR  = os.path.join(_BASE, "tools")
_UE4SS_SRC  = os.path.join(_TOOLS_DIR, "UE4SS", "zDEV-UE4SS_v3.0.1")
_TRANSLATOR_SRC = os.path.join(_MODS_DIR, "UE4ArabicTranslator")


class UE4SSMod:
    """يُدير تثبيت/تحديث UE4SS + UE4ArabicTranslator في ألعاب UE."""

    MOD_NAME = "UE4ArabicTranslator"

    # ── المسارات داخل اللعبة ──────────────────────────────────────────

    def _win64_dir(self, game_path: str, game_id: str) -> str:
        """مجلد Binaries/<Platform> داخل اللعبة — كشف ذكي.

        يدعم:
          - Win64 الكلاسيكي (معظم ألعاب UE)
          - WinGRTS (Grounded2 وألعاب RTS مخصّصة)
          - WinGDK, GDK (نسخ Xbox/Microsoft Store)
          - أيّ مجلد ثنائيات يحوي ملف .exe
        + كشف اسم المجلد الفرعي حتى لو كان غير منتظم (مسافات، عربي، إلخ).
        """
        if not game_path or not os.path.isdir(game_path):
            return os.path.join(game_path, game_id, "Binaries", "Win64")

        # 1) جرّب الاحتمالات الشائعة بترتيب الأولوية
        gid_no_space = game_id.replace(" ", "")
        bin_platforms = ["Win64", "WinGRTS", "WinGDK", "Windows"]
        subfolders = [gid_no_space, game_id, "Maine", "Augusta"]   # الأكثر شيوعاً

        # احتمالات صريحة (subfolder × platform)
        for sub in subfolders:
            for plat in bin_platforms:
                c = os.path.join(game_path, sub, "Binaries", plat)
                if os.path.isdir(c):
                    return c
        # أو مباشرة في الجذر
        for plat in bin_platforms:
            c = os.path.join(game_path, "Binaries", plat)
            if os.path.isdir(c):
                return c

        # 2) Scan تلقائي: ابحث عن أي مجلد <sub>/Binaries/<plat>/ فيه .exe
        try:
            for entry in os.listdir(game_path):
                sub = os.path.join(game_path, entry)
                if not os.path.isdir(sub):
                    continue
                if entry.lower() in ("engine", "saved", "configs", "resources"):
                    continue
                bin_dir = os.path.join(sub, "Binaries")
                if not os.path.isdir(bin_dir):
                    continue
                # افحص كل subdir في Binaries/
                for plat_dir in os.listdir(bin_dir):
                    candidate = os.path.join(bin_dir, plat_dir)
                    if not os.path.isdir(candidate):
                        continue
                    # نبحث عن أي ملف .exe (اللعبة نفسها)
                    try:
                        for f in os.listdir(candidate):
                            if f.lower().endswith(".exe"):
                                return candidate
                    except OSError:
                        continue
        except OSError:
            pass

        # 3) fallback: المسار الكلاسيكي (سيُنشأ إن لزم)
        return os.path.join(game_path, gid_no_space, "Binaries", "Win64")

    def _mods_dir(self, game_path: str, game_id: str) -> str:
        return os.path.join(self._win64_dir(game_path, game_id), "Mods")

    def _mod_target(self, game_path: str, game_id: str) -> str:
        return os.path.join(self._mods_dir(game_path, game_id), self.MOD_NAME)

    def _mods_txt(self, game_path: str, game_id: str) -> str:
        return os.path.join(self._mods_dir(game_path, game_id), "mods.txt")

    # ── الحالة ────────────────────────────────────────────────────────

    def is_ue4ss_installed(self, game_path: str, game_id: str) -> bool:
        """يفحص لو UE4SS موجود (dwmapi.dll + UE4SS.dll)."""
        w64 = self._win64_dir(game_path, game_id)
        return (os.path.isfile(os.path.join(w64, "dwmapi.dll")) and
                os.path.isfile(os.path.join(w64, "UE4SS.dll")))

    def is_mod_installed(self, game_path: str, game_id: str) -> bool:
        """يفحص لو UE4ArabicTranslator موجود."""
        target = self._mod_target(game_path, game_id)
        return os.path.isfile(os.path.join(target, "Scripts", "main.lua"))

    # ── التثبيت ────────────────────────────────────────────────────────

    def install_ue4ss(self, game_path: str, game_id: str) -> Tuple[bool, List[str]]:
        """ينسخ UE4SS الأساسي من tools إلى Binaries/Win64/ في اللعبة."""
        log: List[str] = []
        w64 = self._win64_dir(game_path, game_id)
        if not os.path.isdir(w64):
            return False, [f"مجلد Binaries/Win64 غير موجود: {w64}"]
        if not os.path.isdir(_UE4SS_SRC):
            return False, [f"UE4SS source غير موجود: {_UE4SS_SRC}"]
        try:
            # ملفات UE4SS الأساسية في الجذر
            essentials = ["dwmapi.dll", "UE4SS.dll", "UE4SS-settings.ini"]
            for f in essentials:
                src = os.path.join(_UE4SS_SRC, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(w64, f))
                    log.append(f"✓ {f}")
            # مجلدات UE4SS الفرعية
            for d in ("UE4SS_Signatures", "VTableLayoutTemplates", "MemberVarLayoutTemplates"):
                src = os.path.join(_UE4SS_SRC, d)
                if os.path.isdir(src):
                    dst = os.path.join(w64, d)
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    log.append(f"✓ {d}/")
            # تأكّد من وجود Mods/mods.txt
            os.makedirs(self._mods_dir(game_path, game_id), exist_ok=True)
            mods_txt = self._mods_txt(game_path, game_id)
            if not os.path.isfile(mods_txt):
                # انسخ Mods/mods.txt الافتراضي
                default_mods = os.path.join(_UE4SS_SRC, "Mods", "mods.txt")
                if os.path.isfile(default_mods):
                    shutil.copy2(default_mods, mods_txt)
            log.append(f"✓ UE4SS مثبَّت في {w64}")
            return True, log
        except Exception as e:
            return False, log + [f"خطأ في التثبيت: {e}"]

    def install_translator_mod(self, game_path: str, game_id: str) -> Tuple[bool, List[str]]:
        """ينسخ مود UE4ArabicTranslator + يُحدِّث mods.txt."""
        log: List[str] = []
        if not os.path.isdir(_TRANSLATOR_SRC):
            return False, [f"مود المصدر غير موجود: {_TRANSLATOR_SRC}"]
        try:
            target = self._mod_target(game_path, game_id)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # احذف الإصدار القديم لو موجود (نُبقي dict/ لو يحوي missing.txt مفيد)
            preserve_missing = None
            missing_path = os.path.join(target, "dict", "missing.txt")
            if os.path.isfile(missing_path):
                try:
                    with open(missing_path, "r", encoding="utf-8") as f:
                        preserve_missing = f.read()
                except Exception:
                    pass
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(_TRANSLATOR_SRC, target)
            log.append(f"✓ نُسخ UE4ArabicTranslator → {target}")
            # رجّع missing.txt لو كان موجود
            if preserve_missing:
                with open(missing_path, "w", encoding="utf-8") as f:
                    f.write(preserve_missing)
                log.append("✓ حُفِظ missing.txt القديم")

            # حدّث mods.txt
            self._ensure_mod_enabled(game_path, game_id, log)
            return True, log
        except Exception as e:
            return False, log + [f"خطأ في تثبيت المود: {e}"]

    def _ensure_mod_enabled(self, game_path: str, game_id: str, log: List[str]):
        """يضيف 'UE4ArabicTranslator : 1' لـ mods.txt إن لم يكن موجوداً."""
        mods_txt = self._mods_txt(game_path, game_id)
        line = f"{self.MOD_NAME} : 1"
        content = ""
        if os.path.isfile(mods_txt):
            with open(mods_txt, "r", encoding="utf-8") as f:
                content = f.read()
        if self.MOD_NAME in content:
            # موجود لكن قد يكون : 0 — حدّثه
            new_lines = []
            replaced = False
            for ln in content.splitlines():
                if ln.strip().startswith(self.MOD_NAME):
                    new_lines.append(line)
                    replaced = True
                else:
                    new_lines.append(ln)
            if not replaced:
                new_lines.append(line)
            with open(mods_txt, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
            log.append("✓ mods.txt: المود مُفعَّل")
        else:
            with open(mods_txt, "a", encoding="utf-8") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write(line + "\n")
            log.append("✓ mods.txt: أُضيف المود")

    # ── تصدير القاموس ──────────────────────────────────────────────────

    def export_dict(self, game_path: str, game_id: str, cache,
                    game_name: str = "", model_filter: str = "") -> Tuple[bool, str, int]:
        """يُصدِّر translations.txt للـ mod (نفس صيغة ArabicFontFixer/Flotsam).

        يحترم skip_patterns تلقائياً عبر cache.iter_best_translations().
        """
        if not game_path or not cache:
            return False, "مسار اللعبة أو الكاش غير محدد", 0
        if not self.is_mod_installed(game_path, game_id):
            return False, "المود غير مثبَّت — ثبّته أولاً", 0
        if not game_name:
            game_name = game_id

        target = self._mod_target(game_path, game_id)
        dict_path = os.path.join(target, "dict", "translations.txt")
        os.makedirs(os.path.dirname(dict_path), exist_ok=True)
        try:
            count = 0
            with open(dict_path, "w", encoding="utf-8") as f:
                f.write("# UE4 Arabic Translator dict — مُولَّد تلقائياً\n\n")
                for en, ar in cache.iter_best_translations(game_name, model_filter):
                    if not en or not ar:
                        continue
                    # ⚠ مهم: UE4SS يستلم النص العربي كما هو من الذاكرة، ثم اللعبة تعرضه
                    # عبر UE's TMP/UMG الذي يدعم BiDi و Arabic shaping تلقائياً.
                    # لا نحتاج arabic_reshaper هنا (UE يتولّاه).
                    safe_key = en.replace("=", "\\=").replace("\n", "\\n")
                    safe_val = ar.replace("\n", "\\n")
                    f.write(f"{safe_key}={safe_val}\n")
                    count += 1
        except Exception as e:
            return False, f"خطأ في الكتابة: {e}", 0

        suffix = f" (مودل: {model_filter})" if model_filter else " (دمج هرمي)"
        return True, f"صُدِّرت {count:,} ترجمة{suffix} → UE4ArabicTranslator/dict/translations.txt", count

    # ── قراءة missing.txt ──────────────────────────────────────────────

    def read_missing(self, game_path: str, game_id: str) -> List[str]:
        """يقرأ نصوص missing.txt التي جمعتها اللعبة + يمسحها."""
        target = self._mod_target(game_path, game_id)
        missing_path = os.path.join(target, "dict", "missing.txt")
        if not os.path.isfile(missing_path):
            return []
        seen = set()
        out = []
        try:
            with open(missing_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\r\n")
                    if not line or line.startswith("#"):
                        continue
                    # الصيغة: key= (لا قيمة)
                    if "=" in line:
                        key = line.split("=", 1)[0]
                    else:
                        key = line
                    key = key.replace("\\=", "=").replace("\\n", "\n").strip()
                    if key and key not in seen:
                        seen.add(key)
                        out.append(key)
        except Exception:
            pass
        return out

    def clear_missing(self, game_path: str, game_id: str) -> bool:
        """يفرّغ missing.txt بعد قراءته."""
        target = self._mod_target(game_path, game_id)
        missing_path = os.path.join(target, "dict", "missing.txt")
        try:
            if os.path.isfile(missing_path):
                with open(missing_path, "w", encoding="utf-8") as f:
                    f.write("")
            return True
        except Exception:
            return False

    # ── إلغاء التثبيت ──────────────────────────────────────────────────

    def uninstall_mod(self, game_path: str, game_id: str) -> Tuple[bool, List[str]]:
        """يحذف المود فقط (يُبقي UE4SS)."""
        log: List[str] = []
        target = self._mod_target(game_path, game_id)
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
                log.append(f"🗑 حُذف {self.MOD_NAME}/")
            # حدّث mods.txt
            mods_txt = self._mods_txt(game_path, game_id)
            if os.path.isfile(mods_txt):
                with open(mods_txt, "r", encoding="utf-8") as f:
                    lines = [ln for ln in f.read().splitlines()
                             if not ln.strip().startswith(self.MOD_NAME)]
                with open(mods_txt, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                log.append("✓ mods.txt: أُزيل المود")
            return True, log
        except Exception as e:
            return False, log + [f"خطأ: {e}"]

    def uninstall_ue4ss(self, game_path: str, game_id: str) -> Tuple[bool, List[str]]:
        """يحذف UE4SS كاملاً + كل الـ mods (للإعادة من الصفر)."""
        log: List[str] = []
        w64 = self._win64_dir(game_path, game_id)
        try:
            # احذف ملفات UE4SS الأساسية
            for fname in ("dwmapi.dll", "UE4SS.dll", "UE4SS.pdb", "UE4SS-settings.ini"):
                fp = os.path.join(w64, fname)
                if os.path.isfile(fp):
                    os.remove(fp)
                    log.append(f"🗑 {fname}")
            # احذف المجلدات
            for d in ("UE4SS_Signatures", "VTableLayoutTemplates",
                      "MemberVarLayoutTemplates", "Mods"):
                dp = os.path.join(w64, d)
                if os.path.isdir(dp):
                    shutil.rmtree(dp)
                    log.append(f"🗑 {d}/")
            return True, log
        except Exception as e:
            return False, log + [f"خطأ: {e}"]


__all__ = ["UE4SSMod"]
