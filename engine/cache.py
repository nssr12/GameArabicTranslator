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
        self._local = threading.local()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _game_db_path(self, game_name: str) -> str:
        safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in game_name).strip()
        return os.path.join(self._cache_dir, f"{safe}.db")

    def _get_conn(self, game_name: str) -> sqlite3.Connection:
        if not hasattr(self._local, "conns"):
            self._local.conns = {}
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
        conn.execute(
            "INSERT OR IGNORE INTO failed_translations (original_text, reason) VALUES (?, ?)",
            (original_text, reason)
        )
        conn.commit()

    def is_failed(self, game_name: str, original_text: str) -> bool:
        conn = self._get_conn(game_name)
        return conn.execute(
            "SELECT 1 FROM failed_translations WHERE original_text = ?",
            (original_text,)
        ).fetchone() is not None

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
                games.append(fname[:-3])
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
        """Close all connections to the game DB and delete the .db file."""
        db_path = self._game_db_path(game_name)
        # Close this thread's connection
        if hasattr(self._local, "conns") and game_name in self._local.conns:
            try:
                self._local.conns[game_name].close()
            except Exception:
                pass
            del self._local.conns[game_name]
        # Open a fresh connection to flush WAL, then close
        try:
            tmp = sqlite3.connect(db_path)
            tmp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            tmp.close()
        except Exception:
            pass
        # Delete .db + WAL sidecar files
        for path in [db_path, db_path + "-shm", db_path + "-wal"]:
            try:
                os.remove(path)
            except (FileNotFoundError, PermissionError):
                pass

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
