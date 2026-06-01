"""
unreal_hook_watcher.py - Watches hook DLL Translate folder, translates via our proxy.

Architecture:
    Hook DLL (ZXSOSZXMod.dll - installed by unreal_hook installer)  -writes->  Translate/<hash>.subtitle.en.txt
                                              |
                                              v
                                       unreal_hook_watcher.py
                                              |
                              HTTP GET http://127.0.0.1:5001/?text=...
                                              |
                                              v
                                       Proxy (our system)
                                       - translations.txt (manual)
                                       - skip_patterns
                                       - failed DB
                                       - SQLite cache
                                       - Ollama AI
                                              |
                                              v
                                       Arabic text
                                              |
                                              v
                                       arabic_reshaper
                                              |
                                              v
                              Translate/<hash>.subtitle.txt (UTF-16 LE + BOM)
                                              |
                                              v
                                       Hook DLL reads & displays in-game

Usage:
    1. Make sure proxy is running (run start_proxy.py)
    2. python tools/unreal_hook_watcher.py
    3. Launch the game from Steam
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ_ROOT))

DEFAULT_TRANSLATE_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Manor Lords\ManorLords\Binaries\Win64\Translate"
DEFAULT_PROXY_URL = "http://127.0.0.1:5001"


def banner(msg):
    print("\n" + "=" * 70)
    print(f"  {msg}")
    print("=" * 70)


# ── File I/O ──────────────────────────────────────────────────────────
def read_en_file(path: Path) -> str:
    """Read .en.txt (UTF-16 LE, with or without BOM)."""
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xff\xfe"):
            raw = raw[2:]
        text = raw.decode("utf-16-le", errors="replace")
        return text.rstrip("\x00").rstrip("\n").rstrip("\r")
    except Exception as e:
        print(f"  [X] Failed to read {path.name}: {e}")
        return ""


def write_ar_file(path: Path, text: str):
    """Write .subtitle.txt (UTF-16 LE + BOM)."""
    data = b"\xff\xfe" + text.encode("utf-16-le")
    path.write_bytes(data)


# ── HTTP client ───────────────────────────────────────────────────────
def translate_via_proxy(text: str, proxy_url: str, timeout: int = 60) -> str | None:
    """Send text to proxy, return translation (None on failure)."""
    try:
        encoded = urllib.parse.quote(text, safe='')
        url = f"{proxy_url}/?text={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "unreal-hook-watcher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            result = data.decode("utf-8", errors="replace")
            return result if result else None
    except urllib.error.URLError as e:
        print(f"  [X] proxy URL error: {e}")
        return None
    except Exception as e:
        print(f"  [X] proxy error: {e}")
        return None


def check_proxy(proxy_url: str) -> bool:
    """Verify proxy is reachable (just opens TCP connection, doesn't translate)."""
    import socket
    try:
        # Parse host:port from URL
        host = proxy_url.replace("http://", "").replace("https://", "").split("/")[0]
        if ":" in host:
            h, p = host.split(":")
            port = int(p)
        else:
            h, port = host, 80
        # Just TCP connect - don't request translation (model may need cold start)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((h, port))
        s.close()
        return True
    except Exception:
        return False


# ── arabic reshaper ───────────────────────────────────────────────────
_reshape = None
def get_reshaper():
    global _reshape
    if _reshape is None:
        try:
            import arabic_reshaper
            _reshape = arabic_reshaper.reshape
        except ImportError:
            _reshape = lambda t: t
    return _reshape


# ── Pre-translation filters (skip junk before sending to AI) ──────────
# These run BEFORE the proxy/AI call to avoid wasting compute on garbage.
# Returns: (should_translate, reason_if_skipped)

# Regex patterns for "junk" texts (internal identifiers, not user-facing UI)
_RX_CJK = re.compile(r'[　-鿿＀-￯぀-ゟ゠-ヿ]')
_RX_PLACEHOLDER_ONLY = re.compile(r'^\s*(\{[^}]*\}|<[^>]*>|\s)+\s*$')
_RX_CAMEL_BOUNDARY = re.compile(r'[a-z][A-Z]')           # CowPal, SearchTarget, DayCount
_RX_HAS_DIGIT = re.compile(r'\d')                         # for "DayXXX", "Stat01"
_RX_SNAKE = re.compile(r'^[a-z][a-z0-9_]*_[a-z0-9_]+$')  # snake_case (must have _)
_RX_NUMS_ONLY = re.compile(r'^[\d\s\.,\-+:/\\]+$')
_RX_ASCII_PUNCT_ONLY = re.compile(r'^[^\w\s؀-ۿ]+$')
_RX_ENDS_DIGITS = re.compile(r'[A-Za-z]+X*\d*$')        # DayXXXX, Stat01


def should_translate(text: str, source_lang: str = "en") -> tuple[bool, str]:
    """Decide whether to send this text to the translation proxy.

    Returns (True, '') to translate, or (False, reason) to skip.
    Skipped texts get written as-is to .subtitle.txt so FLTAH stops re-asking.
    """
    if not text:
        return False, "empty"

    s = text.strip()
    if not s:
        return False, "whitespace"
    if len(s) < 2:
        return False, "too_short"

    # تجاهل النصوص اللي ليست بلغة المصدر (مثل ياباني عند source=en)
    if source_lang == "en" and _RX_CJK.search(s):
        return False, "non_english_chars"

    # تجاهل النصوص اللي placeholders فقط: {X}, <tag>
    cleaned = re.sub(r'\{[^}]*\}|<[^>]*>', '', s).strip()
    if not cleaned:
        return False, "placeholders_only"

    # تجاهل internal identifiers (DayXXXX, SearchTarget, CowPal, snake_case)
    # لكن نقبل الكلمات الإفرادية الطبيعية مثل: Other, Stopped, Next, Back
    if ' ' not in s:
        # snake_case معرّفات حتمية
        if _RX_SNAKE.match(s):
            return False, "snake_case"
        # PascalCase composite (CowPal, SearchTarget) — يحوي boundary lowercase→uppercase
        if _RX_CAMEL_BOUNDARY.search(s):
            return False, "pascal_composite"
        # نمط XXX (DayXXXX, ItemXX)
        if 'XX' in s and any(c.isupper() for c in s):
            return False, "placeholder_pattern"
        # كلمة بدون مسافات + رقم = ID (Stat01, Level5, Day1, ...)
        if len(s) >= 4 and _RX_HAS_DIGIT.search(s):
            return False, "id_with_digits"
        # سلسلة طويلة بدون مسافات + underscore = asset path
        if len(s) > 20 and '_' in s:
            return False, "long_no_spaces"

    # تجاهل أرقام فقط
    if _RX_NUMS_ONLY.match(s):
        return False, "numbers_only"

    # تجاهل علامات ترقيم فقط
    if _RX_ASCII_PUNCT_ONLY.match(s):
        return False, "punct_only"

    # نسبة الأحرف اللاتينية يجب تكون معقولة
    letters = sum(1 for c in s if c.isalpha() and c.isascii())
    if len(s) > 5 and letters / len(s) < 0.3:
        return False, "low_letter_density"

    return True, ""


# ── State ─────────────────────────────────────────────────────────────
in_progress: set[str] = set()
failed_perm: set[str] = set()
skip_stats: dict[str, int] = {}  # reason → count
lock = threading.Lock()


def needs_translation(translate_dir: Path) -> list[Path]:
    """Return .en.txt files needing translation."""
    out = []
    for en_file in translate_dir.glob("*.subtitle.en.txt"):
        base = en_file.name.replace(".subtitle.en.txt", "")
        ar_file = translate_dir / f"{base}.subtitle.txt"
        if ar_file.exists():
            continue
        with lock:
            if base in in_progress or base in failed_perm:
                continue
        out.append(en_file)
    return out


def process_file(en_path: Path, translate_dir: Path, proxy_url: str, reshaper) -> str:
    """Process one file. Returns: 'ok', 'skip', 'fail'."""
    base = en_path.name.replace(".subtitle.en.txt", "")
    ar_path = translate_dir / f"{base}.subtitle.txt"

    with lock:
        if base in in_progress:
            return "skip"
        in_progress.add(base)

    try:
        en_text = read_en_file(en_path)
        if not en_text:
            with lock:
                failed_perm.add(base)
            return "fail"

        if not en_text.strip():
            write_ar_file(ar_path, en_text)
            return "ok"

        # ⚡ فلتر مسبق: تجاهل junk قبل ما نُرسل للـ AI (يوفّر آلاف الطلبات)
        ok_translate, skip_reason = should_translate(en_text, source_lang="en")
        if not ok_translate:
            # نكتب نفس النص الإنجليزي ك translation كي FLTAH ما يطلبه ثاني
            write_ar_file(ar_path, en_text)
            with lock:
                skip_stats[skip_reason] = skip_stats.get(skip_reason, 0) + 1
            return "skip"

        # Translate via proxy
        ar_text = translate_via_proxy(en_text, proxy_url, timeout=120)

        if not ar_text:
            with lock:
                failed_perm.add(base)
            return "fail"

        # If proxy returned same English text = unchanged (skip or failed)
        if ar_text.strip() == en_text.strip():
            write_ar_file(ar_path, en_text)
            return "skip"

        # Arabic reshaper
        try:
            ar_text_reshaped = reshaper(ar_text)
        except Exception:
            ar_text_reshaped = ar_text

        # Save
        write_ar_file(ar_path, ar_text_reshaped)

        # Display (only ASCII info - the EN preview, length, and short hash)
        en_preview = en_text[:50].replace("\n", " ").replace("\r", "")
        # Avoid printing Arabic to terminal (corrupts on Windows cmd)
        print(f"  [OK] [{base[:12]:>12}] len={len(en_text):4d} EN: {en_preview!r}")
        return "ok"

    except Exception as e:
        print(f"  [X] Error processing {base}: {e}")
        with lock:
            failed_perm.add(base)
        return "fail"
    finally:
        with lock:
            in_progress.discard(base)


def main():
    ap = argparse.ArgumentParser(description="Unreal hook watcher - uses proxy for translation")
    ap.add_argument("--translate-dir", default=DEFAULT_TRANSLATE_DIR)
    ap.add_argument("--proxy-url", default=DEFAULT_PROXY_URL)
    ap.add_argument("--poll-interval", type=float, default=1.0)
    ap.add_argument("--parallel", type=int, default=3,
                    help="Parallel translations (default 3)")
    args = ap.parse_args()

    banner("Unreal Hook Watcher (Proxy-based)")

    translate_dir = Path(args.translate_dir)
    if not translate_dir.exists():
        print(f"[X] Translate folder not found: {translate_dir}")
        return 1
    print(f"[*] Watching: {translate_dir}")
    print(f"[*] Proxy:    {args.proxy_url}")
    print(f"[*] Parallel: {args.parallel} requests")

    # Check proxy
    print("\n[*] Checking proxy...")
    if not check_proxy(args.proxy_url):
        print(f"[X] Proxy not responding at {args.proxy_url}")
        print()
        print("Fix:")
        print("  1. Make sure start_proxy.py is running in another window")
        print("  2. Or run: python tools/start_proxy.py --game \"Manor Lords\"")
        print("  3. Wait a few seconds and try again")
        return 2
    print("[OK] Proxy responding")

    reshaper = get_reshaper()
    print("[OK] arabic_reshaper ready")

    banner("Watching - Ctrl+C to exit")

    total_ok = 0
    total_skip = 0
    total_fail = 0
    cycle = 0

    executor = ThreadPoolExecutor(max_workers=args.parallel)

    try:
        while True:
            cycle += 1
            pending = needs_translation(translate_dir)

            if pending:
                futures = []
                for en_path in pending:
                    futures.append(executor.submit(
                        process_file, en_path, translate_dir, args.proxy_url, reshaper
                    ))

                for fut in futures:
                    try:
                        result = fut.result(timeout=180)
                        if result == "ok":
                            total_ok += 1
                        elif result == "skip":
                            total_skip += 1
                        else:
                            total_fail += 1
                    except Exception as e:
                        total_fail += 1
                        print(f"  [X] future error: {e}")

            if cycle % 20 == 0:
                with lock:
                    n_inprog = len(in_progress)
                    n_failed = len(failed_perm)
                    skip_breakdown = dict(skip_stats)
                print(f"  [STATS] cycle #{cycle} | OK:{total_ok} | SKIP:{total_skip} | FAIL:{total_fail} | running:{n_inprog} | perm-failed:{n_failed}")
                if skip_breakdown:
                    parts = [f"{k}={v}" for k, v in sorted(skip_breakdown.items(), key=lambda x: -x[1])[:6]]
                    print(f"          skip reasons: {', '.join(parts)}")

            time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print("\n\n[*] Stopped")
    finally:
        executor.shutdown(wait=False)

    print(f"\n[FINAL] OK:{total_ok} | SKIP:{total_skip} | FAIL:{total_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
