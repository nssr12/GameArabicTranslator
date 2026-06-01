"""
start_proxy.py - Standalone proxy server launcher.

Useful for games that don't use BepInEx (no Start Server button in GUI).

Usage:
    python tools/start_proxy.py --game "Manor Lords"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ_ROOT))


def main():
    ap = argparse.ArgumentParser(description="Start translation proxy without GUI")
    ap.add_argument("--game", required=True, help="Game name for cache key")
    ap.add_argument("--tag-mode", default="bulletproof",
                    choices=["inline", "strip", "tiered", "bulletproof"])
    args = ap.parse_args()

    print("=" * 70)
    print(f"  Translation Proxy - '{args.game}'")
    print("=" * 70)

    # ── Engine ──────────────────────────────────────────────────
    try:
        from engine.translator import TranslationEngine
        from engine.cache import TranslationCache
        from engine.proxy_server import ProxyServer
    except ImportError as e:
        print(f"[X] Import failed: {e}")
        return 1

    try:
        engine = TranslationEngine()
        active = engine.get_active_model()
        if not active:
            print("[X] No active translator. Configure Ollama in GUI or config.json")
            return 2
        print(f"[OK] Translator: {active}")

        tr = engine.get_translator(active)
        actual_model = getattr(tr, "model", active) or active
        print(f"[OK] Model: {actual_model}")
    except Exception as e:
        print(f"[X] Engine load failed: {e}")
        return 3

    # ── Cache ──────────────────────────────────────────────────
    cache_path = str(PROJ_ROOT / "data/cache/translations.db")
    try:
        cache = TranslationCache(cache_path)
        print(f"[OK] Cache: data/cache/{args.game}.db")
    except Exception as e:
        print(f"[X] Cache load failed: {e}")
        return 4

    # ── Proxy ──────────────────────────────────────────────────
    try:
        proxy = ProxyServer(engine, cache)
        cfg = {
            "apply_bidi": False,
            "text_reorder_char_limit": 0,
            "tag_mode": args.tag_mode,
        }
        ok, msg = proxy.start(args.game, cfg)
        if not ok:
            print(f"[X] Proxy start failed: {msg}")
            return 5
        print()
        print(f"[OK] {msg}")
        print(f"     Test: curl http://127.0.0.1:5001/?text=Hello")
        print()
        print("-" * 70)
        print("Next:")
        print("  1. Watcher should auto-start in another window")
        print("  2. Launch Manor Lords from Steam")
        print("  3. Translations will appear automatically")
        print("-" * 70)
        print()
        print("[*] Press Ctrl+C to stop...")
        print()

        try:
            while proxy.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[*] Stopping proxy...")

        proxy.stop()
        print("[OK] Stopped")
        return 0

    except Exception as e:
        print(f"[X] Proxy failed: {e}")
        import traceback
        traceback.print_exc()
        return 6


if __name__ == "__main__":
    sys.exit(main())
