"""
games/locres_patcher.py — UE4/UE5 .locres binary patcher.

Supports:
  - Version 1/2  (legacy namespace→key→value flat format)
  - Version 3    (string-table indexed format, UE5 default)

Usage:
  entries = LocresPatcher.read(path)               -> list[LocEntry]
  replaced, total = LocresPatcher.patch(src, dst, {en: ar})
  files = LocresPatcher.find_locres_files(folder)  -> list[str]
"""
from __future__ import annotations
import os
import shutil
import struct
from dataclasses import dataclass
from typing import BinaryIO, Callable

_MAGIC_V3          = 0x7C05AC73
_VERSION_OPTIMIZED = 2   # version >= 2 has int64 string-table offset (UE5)
_VERSION_COMPACT   = 1   # version 1: string table after namespace data, no offset


# ── FString helpers ───────────────────────────────────────────────────────────

def _read_fstring(f: BinaryIO) -> str:
    raw = f.read(4)
    if len(raw) < 4:
        return ""
    length = struct.unpack("<i", raw)[0]
    if length == 0:
        return ""
    if length < 0:
        byte_count = (-length) * 2
        data = f.read(byte_count)
        return data.decode("utf-16-le").rstrip("\x00")
    else:
        data = f.read(length)
        return data.decode("latin-1", errors="replace").rstrip("\x00")


def _write_fstring(f: BinaryIO, s: str) -> None:
    if not s:
        f.write(struct.pack("<i", 0))
        return
    try:
        encoded = s.encode("latin-1") + b"\x00"
        f.write(struct.pack("<i", len(encoded)))
        f.write(encoded)
    except (UnicodeEncodeError, UnicodeDecodeError):
        encoded = (s + "\x00").encode("utf-16-le")
        f.write(struct.pack("<i", -(len(encoded) // 2)))
        f.write(encoded)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LocEntry:
    namespace:   str
    key:         str
    source_hash: int
    value:       str


# ── Patcher ───────────────────────────────────────────────────────────────────

class LocresPatcher:

    @staticmethod
    def read(path: str, logger=None) -> list[LocEntry]:
        """Parse a .locres file → list of LocEntry."""
        with open(path, "rb") as f:
            magic_raw = f.read(4)
            if len(magic_raw) < 4:
                return []
            magic = struct.unpack("<I", magic_raw)[0]
            if magic == _MAGIC_V3:
                version = struct.unpack("<B", f.read(1))[0]
                if logger:
                    logger(f"  [locres] magic=V3  version={version}")
                if version >= _VERSION_OPTIMIZED:
                    return LocresPatcher._read_optimized(f, logger)
                if version == _VERSION_COMPACT:
                    return LocresPatcher._read_compact(f, logger)
                # version == 0 with magic → legacy inline FStrings
                f.seek(0)
                return LocresPatcher._read_legacy(f, magic)
            if logger:
                logger(f"  [locres] no magic (0x{magic:08X}) → legacy")
            f.seek(0)
            return LocresPatcher._read_legacy(f, magic)

    @staticmethod
    def _read_optimized(f: BinaryIO, logger=None) -> list[LocEntry]:
        """version >= 2: int64 pointer to string table at start."""
        entries: list[LocEntry] = []
        try:
            str_table_offset = struct.unpack("<q", f.read(8))[0]
            if logger:
                logger(f"  [locres] str_table_offset={str_table_offset}")
            current_pos = f.tell()
            f.seek(str_table_offset)
            str_count = struct.unpack("<i", f.read(4))[0]
            if logger:
                logger(f"  [locres] str_count={str_count}")
            str_table: list[str] = []
            for _ in range(max(0, str_count)):
                _ref = struct.unpack("<i", f.read(4))[0]
                str_table.append(_read_fstring(f))
            f.seek(current_pos)
            ns_count = struct.unpack("<i", f.read(4))[0]
            if logger:
                logger(f"  [locres] ns_count={ns_count}")
            for _ in range(max(0, ns_count)):
                ns_idx    = struct.unpack("<i", f.read(4))[0]
                namespace = str_table[ns_idx] if 0 <= ns_idx < len(str_table) else ""
                key_count = struct.unpack("<i", f.read(4))[0]
                for _ in range(max(0, key_count)):
                    key_hash = struct.unpack("<I", f.read(4))[0]
                    src_hash = struct.unpack("<I", f.read(4))[0]
                    val_idx  = struct.unpack("<i", f.read(4))[0]
                    value    = str_table[val_idx] if 0 <= val_idx < len(str_table) else ""
                    entries.append(LocEntry(namespace, str(key_hash), src_hash, value))
        except Exception as e:
            if logger:
                logger(f"  [locres] optimized read error: {e}")
        return entries

    @staticmethod
    def _read_compact(f: BinaryIO, logger=None) -> list[LocEntry]:
        """version == 1: namespace data first, string table follows at end."""
        try:
            data = f.read()
        except Exception:
            return []
        import io
        buf = io.BytesIO(data)

        raw_entries: list[tuple] = []
        try:
            ns_count = struct.unpack("<i", buf.read(4))[0]
            if logger:
                logger(f"  [locres] compact ns_count={ns_count}")
            for _ in range(max(0, ns_count)):
                ns_idx    = struct.unpack("<i", buf.read(4))[0]
                key_count = struct.unpack("<i", buf.read(4))[0]
                for _ in range(max(0, key_count)):
                    key_hash = struct.unpack("<I", buf.read(4))[0]
                    src_hash = struct.unpack("<I", buf.read(4))[0]
                    val_idx  = struct.unpack("<i", buf.read(4))[0]
                    raw_entries.append((ns_idx, key_hash, src_hash, val_idx))
            str_count = struct.unpack("<i", buf.read(4))[0]
            if logger:
                logger(f"  [locres] compact str_count={str_count}")
            str_table: list[str] = []
            for _ in range(max(0, str_count)):
                str_table.append(_read_fstring(buf))
        except Exception as e:
            if logger:
                logger(f"  [locres] compact read error: {e}")
            return []

        entries: list[LocEntry] = []
        for ns_idx, key_hash, src_hash, val_idx in raw_entries:
            namespace = str_table[ns_idx] if 0 <= ns_idx < len(str_table) else ""
            value     = str_table[val_idx] if 0 <= val_idx < len(str_table) else ""
            entries.append(LocEntry(namespace, str(key_hash), src_hash, value))
        return entries

    @staticmethod
    def _read_legacy(f: BinaryIO, first_int: int) -> list[LocEntry]:
        entries: list[LocEntry] = []
        try:
            ns_count = first_int
            if ns_count < 0 or ns_count > 100_000:
                return []
            for _ in range(ns_count):
                namespace = _read_fstring(f)
                key_count = struct.unpack("<i", f.read(4))[0]
                for _ in range(max(0, key_count)):
                    key      = _read_fstring(f)
                    src_hash = struct.unpack("<I", f.read(4))[0]
                    value    = _read_fstring(f)
                    entries.append(LocEntry(namespace, key, src_hash, value))
        except Exception:
            pass
        return entries

    @staticmethod
    def patch(
        src_path: str,
        dst_path: str,
        translations: dict[str, str],
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int]:
        """
        Read src_path, replace values found in translations {english: arabic},
        write result to dst_path. Returns (replaced_count, total_count).
        """
        entries  = LocresPatcher.read(src_path)
        total    = len(entries)
        replaced = 0
        for i, entry in enumerate(entries):
            if progress_cb and i % 200 == 0:
                progress_cb(i, total)
            clean = entry.value.strip()
            if clean and clean in translations:
                entry.value = translations[clean]
                replaced += 1
        if progress_cb:
            progress_cb(total, total)
        LocresPatcher._write(dst_path, entries, src_path)
        return replaced, total

    @staticmethod
    def _write(path: str, entries: list[LocEntry], original_path: str) -> None:
        """Write as legacy v1 format. Uses temp-file + atomic rename to prevent corruption."""
        bak = original_path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(original_path, bak)
        ns_map: dict[str, list[LocEntry]] = {}
        for e in entries:
            ns_map.setdefault(e.namespace, []).append(e)
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(struct.pack("<i", len(ns_map)))
                for ns, elist in ns_map.items():
                    _write_fstring(f, ns)
                    f.write(struct.pack("<i", len(elist)))
                    for e in elist:
                        _write_fstring(f, e.key)
                        f.write(struct.pack("<I", e.source_hash))
                        _write_fstring(f, e.value)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            raise

    @staticmethod
    def find_locres_files(folder: str) -> list[str]:
        """Recursively find .locres AND .locres.txt files under folder."""
        found = []
        for root, _, files in os.walk(folder):
            for fname in files:
                lower = fname.lower()
                if lower.endswith(".locres.txt") or (
                    lower.endswith(".locres") and not lower.endswith(".locres.txt")
                ):
                    found.append(os.path.join(root, fname))
        return sorted(found)

    @staticmethod
    def restore_backup(locres_path: str) -> bool:
        """Restore .locres from its .bak backup if it exists."""
        bak = locres_path + ".bak"
        if os.path.exists(bak):
            shutil.copy2(bak, locres_path)
            return True
        return False


# ── .locres.txt text-format handler ──────────────────────────────────────────
# Format produced by UE4localizationsTool and FModel:
#   [~NAMES-INCLUDED~]//Don't edit or remove this line.
#   Namespace::Key="Value"
#   Namespace::Key=Value without quotes
#
# Workflow:
#   1. read_txt(path) → list[LocEntry]
#   2. patch_txt(src, dst, {en: ar}) → (replaced, total)
#   3. compile_txt_to_locres(txt, locres, tool_path) → bool

class LocresTxtFile:
    _HEADER = "[~NAMES-INCLUDED~]//Don't edit or remove this line."

    @staticmethod
    def read(path: str) -> list[LocEntry]:
        entries: list[LocEntry] = []
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n\r")
                    if not line or line.startswith("["):
                        continue
                    sep = line.find("::")
                    if sep < 0:
                        continue
                    namespace = line[:sep]
                    rest = line[sep + 2:]
                    eq = rest.find("=")
                    if eq < 0:
                        continue
                    key   = rest[:eq]
                    value = rest[eq + 1:]
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                        value = value.replace('\\"', '"')   # unescape \" → "
                    entries.append(LocEntry(namespace, key, 0, value))
        except Exception:
            pass
        return entries

    @staticmethod
    def patch(src_path: str, dst_path: str, translations: dict[str, str]) -> tuple[int, int]:
        """Replace English values with Arabic translations and write new .locres.txt."""
        entries = LocresTxtFile.read(src_path)
        total    = len(entries)
        replaced = 0
        for e in entries:
            clean = e.value.strip()
            if clean and clean in translations:
                e.value   = translations[clean]
                replaced += 1
        bak = src_path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(src_path, bak)
        LocresTxtFile._write(dst_path, entries)
        return replaced, total

    @staticmethod
    def _write(path: str, entries: list[LocEntry]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                value = e.value.replace('\\"', '"')
                f.write(f'{e.namespace}::{e.key}={value}\n')

    @staticmethod
    def extract(locres_path: str, tool_path: str) -> tuple[bool, str]:
        """
        UE4localizationsTool export Game.locres  →  Game.locres.txt (نفس المجلد).
        Returns (ok, message).
        """
        import subprocess
        if not os.path.isfile(tool_path):
            return False, f"الأداة غير موجودة: {tool_path}"
        try:
            r = subprocess.run(
                [tool_path, "export", locres_path],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return True, r.stdout or "تم الاستخراج بنجاح"
            return False, (r.stderr or r.stdout or "").strip() or f"خطأ كود {r.returncode}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def compile(txt_path: str, tool_path: str) -> tuple[bool, str]:
        """
        UE4localizationsTool import Game.locres.txt  →  Game.locres (نفس المجلد).
        Returns (ok, message).
        """
        import subprocess
        if not os.path.isfile(tool_path):
            return False, f"الأداة غير موجودة: {tool_path}"
        try:
            r = subprocess.run(
                [tool_path, "import", txt_path],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return True, r.stdout or "تم التجميع بنجاح"
            return False, (r.stderr or r.stdout or "").strip() or f"خطأ كود {r.returncode}"
        except Exception as e:
            return False, str(e)
