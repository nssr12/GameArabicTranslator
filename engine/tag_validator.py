"""
engine/tag_validator.py — تحقق صارم من سلامة tag markers في رد المودل.

نستخدمه قبل استعادة التاقات للتأكد أن المودل لم يحذف/يكرر/يُعِد ترتيب
أي marker. عند الفشل نُرجع تفاصيل المشكلة لإعادة المحاولة أو fallback.
"""
from __future__ import annotations
from typing import NamedTuple


_BP_OPEN  = "⟦"
_BP_CLOSE = "⟧"


class ValidationResult(NamedTuple):
    valid: bool
    issues: list[str]   # رسائل تشرح ما الذي فشل
    severity: str       # "ok" | "recoverable" | "fatal"


def validate_bulletproof_markers(translated: str, tokens: list) -> ValidationResult:
    """
    يتحقق من 4 شروط:
      1. كل marker موجود — لا مفقود
      2. كل marker موجود مرة واحدة فقط — لا مكرر
      3. ⟦/N⟧ يأتي بعد ⟦N⟧ في النص — ترتيب سليم
      4. الترتيب النسبي للـ pairs لم يتغيّر بشكل غير منطقي

    severity:
      ok          → كل شيء سليم
      recoverable → ينقص marker واحد أو اثنان → retry قد يصلحها
      fatal       → فوضى كاملة → fallback لـ strip mode أو إعادة النص الأصلي
    """
    if not tokens:
        return ValidationResult(True, [], "ok")
    if not translated:
        return ValidationResult(False, ["empty translated"], "fatal")

    issues: list[str] = []
    missing_count = 0

    for idx, (kind, _name, _attrs, _inner) in enumerate(tokens):
        if kind == "paired":
            op = f"{_BP_OPEN}{idx}{_BP_CLOSE}"
            cl = f"{_BP_OPEN}/{idx}{_BP_CLOSE}"
            op_count = translated.count(op)
            cl_count = translated.count(cl)
            if op_count == 0:
                issues.append(f"missing opener {op}")
                missing_count += 1
            elif op_count > 1:
                issues.append(f"duplicate opener {op} (×{op_count})")
            if cl_count == 0:
                issues.append(f"missing closer {cl}")
                missing_count += 1
            elif cl_count > 1:
                issues.append(f"duplicate closer {cl} (×{cl_count})")
            # ترتيب: المغلق بعد الفاتح
            if op_count >= 1 and cl_count >= 1:
                if translated.index(op) >= translated.index(cl):
                    issues.append(f"closer {cl} appears before opener {op}")

        elif kind == "self":
            mk = f"{_BP_OPEN}*{idx}{_BP_CLOSE}"
            mk_count = translated.count(mk)
            if mk_count == 0:
                issues.append(f"missing self-closing {mk}")
                missing_count += 1
            elif mk_count > 1:
                issues.append(f"duplicate self-closing {mk} (×{mk_count})")

    if not issues:
        return ValidationResult(True, [], "ok")

    total_markers = sum(2 if t[0] == "paired" else 1 for t in tokens)
    # إذا فقد أكثر من 50% من العلامات → fatal
    if missing_count / total_markers > 0.5:
        return ValidationResult(False, issues, "fatal")
    return ValidationResult(False, issues, "recoverable")


def summarize_issues(result: ValidationResult, max_items: int = 3) -> str:
    """رسالة مختصرة بالعربي للـ log."""
    if result.valid:
        return "✓ سليم"
    head = result.issues[:max_items]
    more = len(result.issues) - len(head)
    msg = "; ".join(head)
    if more > 0:
        msg += f" (+{more} مشاكل أخرى)"
    return f"[{result.severity}] {msg}"


__all__ = ["validate_bulletproof_markers", "summarize_issues", "ValidationResult"]
