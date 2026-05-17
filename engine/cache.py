import sqlite3
import os
import threading
import unicodedata
from typing import Optional, Dict, List


class TranslationCache:
    """Per-game SQLite cache. Each game gets its own .db file in cache_dir."""

    def __init__(self, db_path: str = "data/cache/translations.db"):
        # Accept either a legacy single-file path or a directory.
        # Always derive the cache directory from the path.
        if db_path.endswith(".db"):
            self._cache_dir = os.path.dirname(db_path) or "."
        else:
            self._cache_dir = db_path
        os.makedirs(self._cache_dir, exist_ok=True)
        self._local       = threading.local()
        # Games whose connections must be reset on next access (cross-thread)
        self._pending_reset: set[str] = set()
        self._reset_lock = threading.Lock()
        # Games soft-deleted this session (SQL cleared, file may still exist on Windows)
        self._soft_deleted: set[str] = set()
        self._cleanup_empty_dbs()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup_empty_dbs(self):
        """Remove empty .db files left by failed delete_game() calls (Windows file-lock)."""
        try:
            for fname in os.listdir(self._cache_dir):
                if not fname.endswith(".db"):
                    continue
                db_path = os.path.join(self._cache_dir, fname)
                try:
                    conn = sqlite3.connect(db_path)
                    row = conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type='table' AND name='translations'"
                    ).fetchone()
                    empty = (not row or row[0] == 0 or
                             conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 0)
                    conn.close()
                    if empty:
                        for path in [db_path, db_path + "-shm", db_path + "-wal"]:
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

    def _game_db_path(self, game_name: str) -> str:
        safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in game_name).strip()
        return os.path.join(self._cache_dir, f"{safe}.db")

    def _get_conn(self, game_name: str) -> sqlite3.Connection:
        if not hasattr(self._local, "conns"):
            self._local.conns = {}
        # If this game was reset (deleted), close the stale connection in this thread
        with self._reset_lock:
            needs_reset = game_name in self._pending_reset
            if needs_reset:
                self._pending_reset.discard(game_name)
        if needs_reset and game_name in self._local.conns:
            try:
                self._local.conns[game_name].close()
            except Exception:
                pass
            del self._local.conns[game_name]
        if game_name not in self._local.conns:
            path = self._game_db_path(game_name)
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._init_schema(conn)
            self._local.conns[game_name] = conn
        return self._local.conns[game_name]

    def _init_schema(self, conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS translations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                original_text    TEXT    NOT NULL UNIQUE,
                translated_text  TEXT    NOT NULL,
                model_used       TEXT    DEFAULT 'unknown',
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hit_count        INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_original ON translations(original_text);

            CREATE TABLE IF NOT EXISTS failed_translations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                original_text TEXT    NOT NULL UNIQUE,
                reason        TEXT    DEFAULT '',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        # Migrate old schemas that may be missing newer columns
        existing = {row[1] for row in conn.execute("PRAGMA table_info(translations)")}
        for col, ddl in [
            ("hit_count", "ALTER TABLE translations ADD COLUMN hit_count INTEGER DEFAULT 0"),
            ("updated_at", "ALTER TABLE translations ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("model_used", "ALTER TABLE translations ADD COLUMN model_used TEXT DEFAULT 'unknown'"),
        ]:
            if col not in existing:
                try:
                    conn.execute(ddl)
                    conn.commit()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Public API  (same signatures as before — no breaking changes)
    # ------------------------------------------------------------------

    def get(self, game_name: str, original_text: str) -> Optional[str]:
        conn = self._get_conn(game_name)
        row = conn.execute(
            "SELECT translated_text FROM translations WHERE original_text = ?",
            (original_text,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE translations SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE original_text = ?",
                (original_text,)
            )
            conn.commit()
            return row[0]
        return None

    def put(self, game_name: str, original_text: str, translated_text: str, model: str = "unknown"):
        if not translated_text or translated_text == original_text:
            return
        # If this game was soft-deleted but data is being written again, make it visible
        self._soft_deleted.discard(game_name)
        conn = self._get_conn(game_name)
        conn.execute("""
            INSERT INTO translations (original_text, translated_text, model_used)
            VALUES (?, ?, ?)
            ON CONFLICT(original_text) DO UPDATE SET
                translated_text = excluded.translated_text,
                model_used      = excluded.model_used,
                updated_at      = CURRENT_TIMESTAMP
        """, (original_text, translated_text, model))
        conn.commit()

    def mark_failed(self, game_name: str, original_text: str, reason: str = ""):
        conn = self._get_conn(game_name)
        # عند تكرار محاولة فاشلة، نُحدّث السبب لأحدث رسالة
        conn.execute(
            "INSERT INTO failed_translations (original_text, reason) VALUES (?, ?) "
            "ON CONFLICT(original_text) DO UPDATE SET reason=excluded.reason",
            (original_text, reason)
        )
        conn.commit()

    def is_failed(self, game_name: str, original_text: str) -> bool:
        conn = self._get_conn(game_name)
        return conn.execute(
            "SELECT 1 FROM failed_translations WHERE original_text = ?",
            (original_text,)
        ).fetchone() is not None

    def get_failed_page(self, game_name: str, offset: int = 0, limit: int = 50,
                        search: str = "") -> list:
        """يُرجع صفحة من الترجمات الفاشلة مع سببها."""
        conn = self._get_conn(game_name)
        conditions, params = [], []
        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? OR reason LIKE ?)")
            params.extend([pattern, pattern])
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT original_text, reason, created_at "
            f"FROM failed_translations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params
        ).fetchall()
        return [{"original": r[0], "reason": r[1] or "", "created_at": r[2] or ""} for r in rows]

    def count_failed(self, game_name: str, search: str = "") -> int:
        conn = self._get_conn(game_name)
        conditions, params = [], []
        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? OR reason LIKE ?)")
            params.extend([pattern, pattern])
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return conn.execute(
            f"SELECT COUNT(*) FROM failed_translations {where}", params
        ).fetchone()[0]

    def delete_failed(self, game_name: str, original_text: str):
        """يُزيل إدخالاً من الفاشلة → الطلب التالي سيستدعي الـ AI من جديد."""
        conn = self._get_conn(game_name)
        conn.execute(
            "DELETE FROM failed_translations WHERE original_text = ?",
            (original_text,)
        )
        conn.commit()

    def clear_failed(self, game_name: str):
        """يحذف كل الإدخالات الفاشلة لهذه اللعبة."""
        conn = self._get_conn(game_name)
        conn.execute("DELETE FROM failed_translations")
        conn.commit()

    def get_batch(self, game_name: str, texts: List[str]) -> Dict[str, str]:
        if not texts:
            return {}
        conn = self._get_conn(game_name)
        placeholders = ",".join(["?"] * len(texts))
        rows = conn.execute(
            f"SELECT original_text, translated_text FROM translations WHERE original_text IN ({placeholders})",
            texts
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_sample_originals(self, game_name: str, limit: int = 5) -> List[str]:
        """Return up to `limit` original_text values stored for this game."""
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT original_text FROM translations LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_all_for_game(self, game_name: str) -> Dict[str, str]:
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT original_text, translated_text FROM translations"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_stats(self, game_name: str) -> dict:
        conn = self._get_conn(game_name)
        total = conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
        hits  = conn.execute("SELECT COALESCE(SUM(hit_count), 0) FROM translations").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM failed_translations").fetchone()[0]
        return {
            "total_translations": total,
            "cache_hits": hits,
            "failed_count": failed,
        }

    def get_all_games(self) -> List[str]:
        games = []
        for fname in sorted(os.listdir(self._cache_dir)):
            if fname.endswith(".db"):
                game_name = fname[:-3]
                if game_name not in self._soft_deleted:
                    games.append(game_name)
        return games

    def export_game(self, game_name: str) -> Dict[str, str]:
        return self.get_all_for_game(game_name)

    def import_game(self, game_name: str, translations: Dict[str, str], model: str = "imported"):
        conn = self._get_conn(game_name)
        for orig, trans in translations.items():
            conn.execute("""
                INSERT INTO translations (original_text, translated_text, model_used)
                VALUES (?, ?, ?)
                ON CONFLICT(original_text) DO UPDATE SET
                    translated_text = excluded.translated_text,
                    model_used      = excluded.model_used,
                    updated_at      = CURRENT_TIMESTAMP
            """, (orig, trans, model))
        conn.commit()

    def clear_game(self, game_name: str):
        """Delete all translations for a game via SQL (no file deletion, safe across threads)."""
        conn = self._get_conn(game_name)
        conn.execute("DELETE FROM translations")
        conn.execute("DELETE FROM failed_translations")
        conn.commit()

    def delete_game(self, game_name: str):
        """Clear all translations for a game and delete the .db file."""
        db_path = self._game_db_path(game_name)

        # Always clear data via SQL first — works even when proxy holds the file open.
        # On Windows, os.remove() fails with PermissionError if another thread has
        # the .db file open, so the SQL delete is the only reliable way to wipe data.
        try:
            conn = self._get_conn(game_name)
            conn.execute("DELETE FROM translations")
            conn.execute("DELETE FROM failed_translations")
            conn.commit()
        except Exception:
            pass

        # Signal all other threads to reset stale connections before we close ours
        with self._reset_lock:
            self._pending_reset.add(game_name)

        # Close this thread's connection
        if hasattr(self._local, "conns") and game_name in self._local.conns:
            try:
                self._local.conns[game_name].close()
            except Exception:
                pass
            del self._local.conns[game_name]

        # Checkpoint WAL then attempt file deletion
        try:
            tmp = sqlite3.connect(db_path)
            tmp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            tmp.close()
        except Exception:
            pass

        file_deleted = False
        for path in [db_path, db_path + "-shm", db_path + "-wal"]:
            try:
                os.remove(path)
                if path == db_path:
                    file_deleted = True
            except (FileNotFoundError, PermissionError):
                pass

        # If the file couldn't be deleted (Windows — proxy has it open), mark as
        # soft-deleted so get_all_games() hides it for the rest of this session.
        # The empty file will be cleaned up on the next startup.
        if not file_deleted:
            self._soft_deleted.add(game_name)

    def get_page(self, game_name: str, offset: int = 0, limit: int = 50,
                 search: str = "", model_filter: str = "") -> list:
        conn = self._get_conn(game_name)
        conditions, params = [], []

        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? OR translated_text LIKE ?)")
            params.extend([pattern, pattern])
        if model_filter and model_filter != "All Models":
            conditions.append("model_used = ?")
            params.append(model_filter)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT original_text, translated_text, model_used, hit_count "
            f"FROM translations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params
        ).fetchall()
        return [{"original": r[0], "translated": r[1], "model": r[2], "hits": r[3]} for r in rows]

    def count_entries(self, game_name: str, search: str = "", model_filter: str = "") -> int:
        conn = self._get_conn(game_name)
        conditions, params = [], []

        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? OR translated_text LIKE ?)")
            params.extend([pattern, pattern])
        if model_filter and model_filter != "All Models":
            conditions.append("model_used = ?")
            params.append(model_filter)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return conn.execute(f"SELECT COUNT(*) FROM translations {where}", params).fetchone()[0]

    def get_models_for_game(self, game_name: str) -> List[str]:
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT DISTINCT model_used FROM translations ORDER BY model_used"
        ).fetchall()
        return [r[0] for r in rows if r[0]]

    def update_translation(self, game_name: str, original_text: str, new_translated: str):
        conn = self._get_conn(game_name)
        conn.execute(
            "UPDATE translations SET translated_text = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE original_text = ?",
            (new_translated, original_text)
        )
        conn.commit()

    def delete_entry(self, game_name: str, original_text: str):
        conn = self._get_conn(game_name)
        conn.execute("DELETE FROM translations WHERE original_text = ?", (original_text,))
        conn.commit()

    def delete_all(self):
        """Delete ALL game databases."""
        for game in self.get_all_games():
            self.delete_game(game)

    def delete_by_model(self, game_name: str, model_name: str):
        conn = self._get_conn(game_name)
        conn.execute("DELETE FROM translations WHERE model_used = ?", (model_name,))
        conn.commit()

    def get_by_model(self, game_name: str, model_name: str) -> Dict[str, str]:
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT original_text, translated_text FROM translations WHERE model_used = ?",
            (model_name,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def count_by_model(self, game_name: str, model_name: str) -> int:
        conn = self._get_conn(game_name)
        return conn.execute(
            "SELECT COUNT(*) FROM translations WHERE model_used = ?",
            (model_name,)
        ).fetchone()[0]

    def close(self):
        if hasattr(self._local, "conns"):
            for conn in self._local.conns.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._local.conns = {}
