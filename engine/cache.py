import sqlite3
import os
import threading
import time
import unicodedata
from typing import Optional, Dict, List, Tuple


class TranslationCache:
    
    def __init__(self, db_path: str = "data/cache/translations.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._ensure_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn
    
    def _ensure_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT NOT NULL,
                original_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                model_used TEXT DEFAULT 'unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hit_count INTEGER DEFAULT 0,
                UNIQUE(game_name, original_text)
            );
            
            CREATE INDEX IF NOT EXISTS idx_game_text 
                ON translations(game_name, original_text);
            CREATE INDEX IF NOT EXISTS idx_game 
                ON translations(game_name);
            
            CREATE TABLE IF NOT EXISTS failed_translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT NOT NULL,
                original_text TEXT NOT NULL,
                reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(game_name, original_text)
            );
            
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT NOT NULL,
                total_translated INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0,
                api_calls INTEGER DEFAULT 0,
                last_translation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(game_name)
            );
        """)
        conn.commit()
    
    def get(self, game_name: str, original_text: str) -> Optional[str]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT translated_text FROM translations WHERE game_name = ? AND original_text = ?",
            (game_name, original_text)
        )
        row = cursor.fetchone()
        if row:
            conn.execute(
                "UPDATE translations SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE game_name = ? AND original_text = ?",
                (game_name, original_text)
            )
            conn.commit()
            return row[0]
        return None
    
    def put(self, game_name: str, original_text: str, translated_text: str, model: str = "unknown"):
        if not translated_text or translated_text == original_text:
            return
        
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO translations (game_name, original_text, translated_text, model_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(game_name, original_text) DO UPDATE SET
                translated_text = excluded.translated_text,
                model_used = excluded.model_used,
                updated_at = CURRENT_TIMESTAMP
        """, (game_name, original_text, translated_text, model))
        conn.commit()
    
    def mark_failed(self, game_name: str, original_text: str, reason: str = ""):
        conn = self._get_conn()
        conn.execute("""
            INSERT OR IGNORE INTO failed_translations (game_name, original_text, reason)
            VALUES (?, ?, ?)
        """, (game_name, original_text, reason))
        conn.commit()
    
    def is_failed(self, game_name: str, original_text: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM failed_translations WHERE game_name = ? AND original_text = ?",
            (game_name, original_text)
        )
        return cursor.fetchone() is not None
    
    def get_batch(self, game_name: str, texts: List[str]) -> Dict[str, str]:
        if not texts:
            return {}
        
        conn = self._get_conn()
        placeholders = ",".join(["?"] * len(texts))
        cursor = conn.execute(
            f"SELECT original_text, translated_text FROM translations WHERE game_name = ? AND original_text IN ({placeholders})",
            [game_name] + texts
        )
        result = {}
        for row in cursor.fetchall():
            result[row[0]] = row[1]
        return result
    
    def get_all_for_game(self, game_name: str) -> Dict[str, str]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT original_text, translated_text FROM translations WHERE game_name = ?",
            (game_name,)
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def get_stats(self, game_name: str) -> dict:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM translations WHERE game_name = ?",
            (game_name,)
        )
        total = cursor.fetchone()[0]
        
        cursor = conn.execute(
            "SELECT SUM(hit_count) FROM translations WHERE game_name = ?",
            (game_name,)
        )
        hits = cursor.fetchone()[0] or 0
        
        cursor = conn.execute(
            "SELECT COUNT(*) FROM failed_translations WHERE game_name = ?",
            (game_name,)
        )
        failed = cursor.fetchone()[0]
        
        return {
            "total_translations": total,
            "cache_hits": hits,
            "failed_count": failed
        }
    
    def get_all_games(self) -> List[str]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT DISTINCT game_name FROM translations ORDER BY game_name")
        return [row[0] for row in cursor.fetchall()]
    
    def export_game(self, game_name: str) -> Dict[str, str]:
        return self.get_all_for_game(game_name)
    
    def import_game(self, game_name: str, translations: Dict[str, str], model: str = "imported"):
        conn = self._get_conn()
        for orig, trans in translations.items():
            conn.execute("""
                INSERT INTO translations (game_name, original_text, translated_text, model_used)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(game_name, original_text) DO UPDATE SET
                    translated_text = excluded.translated_text,
                    model_used = excluded.model_used,
                    updated_at = CURRENT_TIMESTAMP
            """, (game_name, orig, trans, model))
        conn.commit()
    
    def delete_game(self, game_name: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM translations WHERE game_name = ?", (game_name,))
        conn.execute("DELETE FROM failed_translations WHERE game_name = ?", (game_name,))
        conn.commit()
    
    def _normalize_arabic(self, text: str) -> str:
        text = unicodedata.normalize('NFKC', text)
        text = text.replace('\u0640', '')
        text = text.replace('\u0622', '\u0627')
        text = text.replace('\u0623', '\u0627')
        text = text.replace('\u0625', '\u0627')
        text = text.replace('\u0649', '\u064A')
        return text
    
    def get_page(self, game_name: str, offset: int = 0, limit: int = 50, search: str = "", model_filter: str = "") -> list:
        conn = self._get_conn()
        conditions = ["game_name = ?"]
        params = [game_name]
        
        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? OR translated_text LIKE ? OR original_text LIKE ? OR translated_text LIKE ?)")
            params.extend([pattern, pattern, f"%{search.lower()}%", f"%{search.upper()}%"])
        
        if model_filter and model_filter != "All Models":
            conditions.append("model_used = ?")
            params.append(model_filter)
        
        where = " AND ".join(conditions)
        params.extend([limit, offset])
        
        cursor = conn.execute(
            f"SELECT original_text, translated_text, model_used, hit_count FROM translations WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params
        )
        return [{"original": row[0], "translated": row[1], "model": row[2], "hits": row[3]} for row in cursor.fetchall()]
    
    def count_entries(self, game_name: str, search: str = "", model_filter: str = "") -> int:
        conn = self._get_conn()
        conditions = ["game_name = ?"]
        params = [game_name]
        
        if search:
            pattern = f"%{search}%"
            conditions.append("(original_text LIKE ? ESCAPE '\\' OR translated_text LIKE ? ESCAPE '\\')")
            params.extend([pattern, pattern])
        
        if model_filter and model_filter != "All Models":
            conditions.append("model_used = ?")
            params.append(model_filter)
        
        where = " AND ".join(conditions)
        cursor = conn.execute(f"SELECT COUNT(*) FROM translations WHERE {where}", params)
        return cursor.fetchone()[0]
    
    def get_models_for_game(self, game_name: str) -> List[str]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT DISTINCT model_used FROM translations WHERE game_name = ? ORDER BY model_used",
            (game_name,)
        )
        return [row[0] for row in cursor.fetchall() if row[0]]
    
    def update_translation(self, game_name: str, original_text: str, new_translated: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE translations SET translated_text = ?, updated_at = CURRENT_TIMESTAMP WHERE game_name = ? AND original_text = ?",
            (new_translated, game_name, original_text)
        )
        conn.commit()
    
    def delete_entry(self, game_name: str, original_text: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM translations WHERE game_name = ? AND original_text = ?", (game_name, original_text))
        conn.commit()
    
    def delete_all(self):
        conn = self._get_conn()
        conn.execute("DELETE FROM translations")
        conn.execute("DELETE FROM failed_translations")
        conn.commit()
    
    def delete_by_model(self, game_name: str, model_name: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM translations WHERE game_name = ? AND model_used = ?", (game_name, model_name))
        conn.commit()
    
    def get_by_model(self, game_name: str, model_name: str) -> Dict[str, str]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT original_text, translated_text FROM translations WHERE game_name = ? AND model_used = ?",
            (game_name, model_name)
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def count_by_model(self, game_name: str, model_name: str) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM translations WHERE game_name = ? AND model_used = ?",
            (game_name, model_name)
        )
        return cursor.fetchone()[0]
    
    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
