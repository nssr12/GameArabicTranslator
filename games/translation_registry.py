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
APP_VERSION = "1.0"


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
        """Download and parse the manifest. Returns True on success."""
        # Use urllib (no SSL cert issues in PyInstaller bundles)
        try:
            import urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            req = urllib.request.Request(
                MANIFEST_URL,
                headers={"User-Agent": "GameArabicTranslator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                self._manifest = json.loads(resp.read().decode())
                return True
        except Exception:
            pass
        # Fallback: requests
        try:
            import requests
            r = requests.get(MANIFEST_URL, timeout=timeout, verify=False)
            if r.ok:
                self._manifest = r.json()
                return True
        except Exception:
            pass
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
