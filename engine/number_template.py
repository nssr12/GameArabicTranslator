"""
engine/number_template.py — تقويلب الأرقام (number templating) لتقليل تكرار الكاش.

المشكلة: اللعبة تستبدل القوالب بالأرقام قبل أن يصل النص للعرض، فنلتقط:
   "Current Tier: 2"، "Fertility: 100% من 0 الى 100"، "Population: 5/10" ...
كل قيمة رقمية تُنشئ مدخلاً منفصلاً في الكاش وتستهلك ترجمة AI جديدة (تكرار ضخم).

الحل: نستبدل كل رقم بعلامة {0} {1} ... — وهي علامة **محميّة أصلاً** في برومت
النظام وفي engine/models/base.py::translate_preserving_tokens (تُمرَّر verbatim).
فيصبح المفتاح قالباً واحداً يُترجَم مرّة:

   "Current Tier: 2"  →  قالب "Current Tier: {0}"  + ["2"]
   "Current Tier: 5"  →  نفس القالب → cache hit
بعد الترجمة نُعيد الأرقام الأصلية في أماكنها → "المستوى الحالي: 5".

ملاحظات أمان:
- لو النص يحوي {..} أصلاً (قالب لم يُستبدَل) لا نتدخّل (تجنّب تضارب الترقيم).
- نلتقط الأرقام مع فواصلها العشرية/الآلاف و% اللاحقة، دون أن نبتلع علامات الترقيم.
"""
import re

# رقم: تتابع أرقام مع فواصل عشرية/آلاف داخلية (.,)، اختيارياً % لاحقة.
# لا ينتهي بفاصل (نتجنّب ابتلاع نقطة نهاية الجملة "Tier: 2.").
_NUM_RE = re.compile(r'\d+(?:[.,]\d+)*%?')

# لو النص فيه {..} أصلاً (قالب لم يُستبدَل) — لا نقولِب لتجنّب تضارب أرقام العلامات.
_HAS_BRACE = re.compile(r'\{[^{}]*\}')


def should_templatize(text: str) -> bool:
    """هل يستحق هذا النص التقويلب؟ (فيه رقم، وبلا {..} مسبقة)."""
    if not text or _HAS_BRACE.search(text):
        return False
    return bool(_NUM_RE.search(text))


def extract(text: str):
    """يُرجع (template, numbers). template فيه {0}{1}.. بدل الأرقام بالترتيب."""
    nums: list[str] = []

    def rep(m):
        nums.append(m.group(0))
        return "{" + str(len(nums) - 1) + "}"

    template = _NUM_RE.sub(rep, text)
    return template, nums


def restore(template: str, numbers) -> str:
    """يُعيد الأرقام الأصلية إلى أماكن العلامات {0}{1}.. في النص المُترجَم."""
    out = template
    for i, n in enumerate(numbers):
        out = out.replace("{" + str(i) + "}", n, 1)
    return out
