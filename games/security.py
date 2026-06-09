"""
games/security.py — أدوات أمان التحميل (checksum + SSL موثَّق).

سلسلة الثقة:
  1. manifest.json يُجلَب عبر HTTPS **موثَّق** (شهادة certifi) → مصدر موثوق.
  2. الـ manifest يحوي sha256 لكل ملف (تطبيق/ترجمة/for_cache).
  3. كل ملف يُحمَّل ثم يُتحقَّق sha256 منه → حتى لو ضعُف اتصال التحميل،
     لا يمكن حقن ملف مُتلاعَب (لن يطابق الـ hash الموثوق).

ملاحظة PyInstaller: النسخة المُغلَّفة قد تفتقر لشهادات النظام، لذا نستخدم
حزمة certifi (تُرفَق في الـ .spec). إن غابت certifi نقع على شهادات النظام.
"""
from __future__ import annotations
import hashlib
import os
import ssl


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    """يحسب sha256 لملف (hex lowercase)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def ca_bundle() -> str | None:
    """مسار حزمة شهادات certifi إن توفّرت."""
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


def ssl_context() -> ssl.SSLContext:
    """سياق SSL موثَّق (يفضّل certifi). تحقّق الشهادة + المضيف مفعَّل."""
    ca = ca_bundle()
    try:
        if ca and os.path.isfile(ca):
            return ssl.create_default_context(cafile=ca)
    except Exception:
        pass
    return ssl.create_default_context()


def requests_verify():
    """قيمة verify لـ requests: مسار certifi أو True (تحقّق دائماً)."""
    ca = ca_bundle()
    return ca if (ca and os.path.isfile(ca)) else True


def verify_sha256(path: str, expected: str | None) -> bool:
    """يتحقّق أن sha256 الملف يطابق المتوقَّع.
    إن كان expected فارغاً (إصدار قديم بلا checksum) → True (توافق رجعي)."""
    if not expected:
        return True
    try:
        return sha256_file(path).lower() == str(expected).strip().lower()
    except Exception:
        return False


__all__ = ["sha256_file", "ca_bundle", "ssl_context", "requests_verify", "verify_sha256"]
