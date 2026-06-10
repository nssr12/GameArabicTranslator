"""
games/translation_registry.py — Online translation registry
Fetches manifest.json from GitHub to discover available translations + app updates.
"""
from __future__ import annotations
import os
import json
from typing import Optional, Dict

MANIFEST_URL = (
    "https://raw.githubusercontent.com/nssr12/GameArabicTranslator/main/manifest.json"
)
APP_VERSION = "2.3"


def _version_gt(a: str, b: str) -> bool:
    try:
        return (
            tuple(int(x) for x in str(a).split("."))
            > tuple(int(x) for x in str(b).split("."))
        )
    except Exception:
        return False


class TranslationRegistry:
    """Thin wrapper around the remote manifest.json."""

    def __init__(self):
        self._manifest: Optional[dict] = None

    def fetch(self, timeout: int = 8) -> bool:
        """Download and parse the manifest over **verified** HTTPS.
        المنفست هو مرساة الثقة → نتحقّق من شهادة SSL دائماً (عبر certifi)."""
        errors = []
        from games.security import ssl_context, requests_verify
        # urllib مع سياق SSL موثَّق (certifi)
        try:
            import urllib.request
            ctx = ssl_context()
            req = urllib.request.Request(
                MANIFEST_URL,
                headers={"User-Agent": "GameArabicTranslator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                self._manifest = json.loads(resp.read().decode())
                return True
        except Exception as e:
            errors.append(f"urllib:{e}")
        # Fallback: requests (تحقّق SSL مفعَّل عبر certifi)
        try:
            import requests
            r = requests.get(MANIFEST_URL, timeout=timeout, verify=requests_verify())
            if r.ok:
                self._manifest = r.json()
                return True
            errors.append(f"requests:status={r.status_code}")
        except Exception as e:
            errors.append(f"requests:{e}")
        self._last_error = " | ".join(errors)
        return False

    @property
    def available(self) -> bool:
        return self._manifest is not None

    def get_translation(self, game_id: str) -> Optional[dict]:
        """Return translation info dict for game_id, or None."""
        if not self._manifest:
            return None
        return self._manifest.get("translations", {}).get(game_id)

    def has_update(self, current: str = APP_VERSION) -> Optional[dict]:
        """Return app info dict if a newer version exists, else None."""
        if not self._manifest:
            return None
        app_info = self._manifest.get("app", {})
        if _version_gt(app_info.get("version", "0"), current):
            return app_info
        return None

    def all_translations(self) -> Dict[str, dict]:
        """Return all available translations keyed by game_id."""
        if not self._manifest:
            return {}
        return dict(self._manifest.get("translations", {}))
