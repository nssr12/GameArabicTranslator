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
            ("mode_used",  "ALTER TABLE translations ADD COLUMN mode_used TEXT DEFAULT ''"),  # learning cache
            # is_preferred: علم اختيار يدوي صريح للترجمة الأفضل في حالة وجود ترجمات متعدّدة
            # — أعلى أولوية في خوارزمية get_best الهرمية
            ("is_preferred", "ALTER TABLE translations ADD COLUMN is_preferred INTEGER DEFAULT 0"),
        ]:
            if col not in existing:
                try:
                    conn.execute(ddl)
                    conn.commit()
                except Exception:
                    pass

        # ── Migration v2: UNIQUE(original_text) → UNIQUE(original_text, model_used)
        # يسمح بترجمات متعدّدة لنفس النص (واحدة لكل مودل) للدمج الهرمي.
        # يحفظ كل البيانات الموجودة كما هي — لا فقدان.
        self._migrate_to_composite_unique(conn)
        # نفس الترقية لجدول failed_translations
        existing_failed = {row[1] for row in conn.execute("PRAGMA table_info(failed_translations)")}
        for col, ddl in [
            ("modes_tried", "ALTER TABLE failed_translations ADD COLUMN modes_tried TEXT DEFAULT ''"),
            # model_used: المودل الذي حاول الترجمة وفشل — يُستخدم عند التصحيح اليدوي
            # لحفظ الترجمة المُصحَّحة تحت نفس المودل في كاش النجاح
            ("model_used", "ALTER TABLE failed_translations ADD COLUMN model_used TEXT DEFAULT ''"),
        ]:
            if col not in existing_failed:
                try:
                    conn.execute(ddl)
                    conn.commit()
                except Exception:
                    pass

        # جدول إحصاءات الـ mode (Learning cache على مستوى اللعبة)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mode_stats (
                mode          TEXT PRIMARY KEY,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_used_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # جدول أولوية المودلات — يستخدم في الدمج الهرمي
        # priority أعلى = يفوز عند التعارض. الترتيب الافتراضي: حسب الإضافة.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_priority (
                model_used    TEXT PRIMARY KEY,
                priority      INTEGER NOT NULL DEFAULT 0,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    def _migrate_to_composite_unique(self, conn: sqlite3.Connection):
        """يُحوّل UNIQUE(original_text) إلى UNIQUE(original_text, model_used).
        SQLite لا يدعم DROP CONSTRAINT — يجب إعادة بناء الجدول.
        يحافظ على كل البيانات الموجودة (id, hit_count, ...).
        """
        try:
            # ابحث عن قيد UNIQUE الحالي
            indexes = conn.execute("PRAGMA index_list(translations)").fetchall()
            # idx: (seq, name, unique, origin, partial)
            old_unique_only_text = False
            new_unique_composite = False
            for idx in indexes:
                if not idx[2]:
                    continue
                cols = [r[2] for r in conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()]
                if cols == ["original_text"]:
                    old_unique_only_text = True
                elif sorted(cols) == sorted(["original_text", "model_used"]):
                    new_unique_composite = True

            if new_unique_composite:
                return   # تمت الترقية مسبقاً

            if not old_unique_only_text:
                # جدول قديم بصيغة مختلفة — لا تتدخّل
                return

            # إعادة بناء آمنة — executescript يدير الـ transaction بنفسه
            conn.executescript("""
                ALTER TABLE translations RENAME TO _translations_v1;
                CREATE TABLE translations (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_text    TEXT    NOT NULL,
                    translated_text  TEXT    NOT NULL,
                    model_used       TEXT    NOT NULL DEFAULT 'unknown',
                    mode_used        TEXT    DEFAULT '',
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hit_count        INTEGER DEFAULT 0,
                    is_preferred     INTEGER DEFAULT 0,
                    UNIQUE(original_text, model_used)
                );
            """)
            # انسخ كل الأعمدة المتاحة (نراعي أن الـ v1 قد لا يحوي is_preferred)
            v1_cols = {row[1] for row in conn.execute("PRAGMA table_info(_translations_v1)")}
            base_cols = ["id", "original_text", "translated_text", "model_used",
                         "created_at", "updated_at", "hit_count"]
            optional_cols = ["mode_used", "is_preferred"]
            all_cols = base_cols + [c for c in optional_cols if c in v1_cols]
            cols_csv = ", ".join(all_cols)
            # عَوِّض NULLs في model_used → 'unknown' لتفادي مشاكل NOT NULL
            select_parts = []
            for c in all_cols:
                if c == "model_used":
                    select_parts.append("COALESCE(NULLIF(TRIM(model_used), ''), 'unknown') AS model_used")
                else:
                    select_parts.append(c)
            conn.execute(
                f"INSERT INTO translations ({cols_csv}) "
                f"SELECT {', '.join(select_parts)} FROM _translations_v1"
            )
            conn.execute("DROP TABLE _translations_v1")
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_original ON translations(original_text);
                CREATE INDEX IF NOT EXISTS idx_original_model ON translations(original_text, model_used);
            """)
            conn.commit()
            print("[Cache] migrated translations table to v2 (UNIQUE on text+model)")
        except Exception as e:
            # ترقية فشلت — يبقى الجدول القديم سليماً (لا يكسر التطبيق)
            print(f"[Cache] migration to v2 failed: {e}")

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

    def put(self, game_name: str, original_text: str, translated_text: str,
            model: str = "unknown", mode_used: str = ""):
        if not translated_text or translated_text == original_text:
            return
        # If this game was soft-deleted but data is being written again, make it visible
        self._soft_deleted.discard(game_name)
        # تطبيع: model_used فارغ → "unknown" (يلائم NOT NULL في الـ schema الجديد)
        model = (model or "unknown").strip() or "unknown"
        conn = self._get_conn(game_name)
        # Schema v2: UNIQUE(original_text, model_used) — صف منفصل لكل مودل
        # نفس النص يُحفَظ مرات متعدّدة (واحدة لكل مودل ترجمه) ويُختار الأفضل عند التصدير.
        conn.execute("""
            INSERT INTO translations (original_text, translated_text, model_used, mode_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(original_text, model_used) DO UPDATE SET
                translated_text = excluded.translated_text,
                mode_used       = excluded.mode_used,
                updated_at      = CURRENT_TIMESTAMP
        """, (original_text, translated_text, model, mode_used))
        conn.commit()

    def set_preferred(self, game_name: str, original_text: str, model_used: str,
                      preferred: bool = True):
        """يحدّد أن ترجمة معيّنة (نص × مودل) هي المختارة يدوياً.
        يضع is_preferred=1 على هذا الصف و 0 على بقية صفوف نفس النص."""
        conn = self._get_conn(game_name)
        conn.execute(
            "UPDATE translations SET is_preferred = 0 WHERE original_text = ?",
            (original_text,)
        )
        if preferred:
            conn.execute(
                "UPDATE translations SET is_preferred = 1 "
                "WHERE original_text = ? AND model_used = ?",
                (original_text, model_used)
            )
        conn.commit()

    # ── Model priority management ───────────────────────────────────────────

    def get_model_priorities(self, game_name: str) -> dict[str, int]:
        """يُرجع خريطة {model_used: priority} للعبة معيّنة."""
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT model_used, priority FROM model_priority"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_model_priority(self, game_name: str, model_used: str, priority: int):
        """يُحدّث أولوية مودل (أعلى = يفوز عند التعارض)."""
        conn = self._get_conn(game_name)
        conn.execute("""
            INSERT INTO model_priority (model_used, priority, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(model_used) DO UPDATE SET
                priority = excluded.priority,
                updated_at = CURRENT_TIMESTAMP
        """, (model_used, priority))
        conn.commit()

    def get_best(self, game_name: str, original_text: str,
                 deprioritize_suffix: str = "") -> Optional[str]:
        """يُرجع أفضل ترجمة للنص حسب الخوارزمية الهرمية:
          1) is_preferred=1     — اختيار يدوي صريح
          2) mode_used='manual' — تصحيح يدوي عبر EditDialog
          3) إجماع 2+ مودلات    — نفس الترجمة من أكثر من مودل
          4) أعلى model_priority — حسب جدول الأولوية
          5) الأحدث (MAX updated_at) — fallback نهائي

        deprioritize_suffix: لو محدّد (مثل ":i2")، نفلتر الترجمات من المودلات
          التي تنتهي بهذا الـ suffix **عندما يتوفّر بديل بدونها**. مفيد للـ live
          export — ترجمات :i2 بصيغة template ({0}) أو contextual لا تناسب
          عرض TMP الـ live (اللعبة تستبدل placeholders قبل الإرسال).
        """
        conn = self._get_conn(game_name)
        rows = conn.execute("""
            SELECT translated_text, model_used,
                   COALESCE(is_preferred, 0), COALESCE(mode_used, ''),
                   COALESCE(updated_at, '')
            FROM translations
            WHERE original_text = ?
        """, (original_text,)).fetchall()
        if not rows:
            return None
        # فضّل المودلات بدون suffix عندما يتوفّر بديل
        if deprioritize_suffix and len(rows) > 1:
            no_suffix = [r for r in rows if not str(r[1]).endswith(deprioritize_suffix)]
            if no_suffix:
                rows = no_suffix
        if len(rows) == 1:
            return rows[0][0]

        # المستوى 1: is_preferred
        preferred = [r for r in rows if r[2]]
        if preferred:
            return preferred[0][0]

        # المستوى 2: mode_used='manual'
        manual = [r for r in rows if r[3] == "manual"]
        if manual:
            # لو فيه عدة manual، خذ الأحدث
            manual.sort(key=lambda r: r[4] or "", reverse=True)
            return manual[0][0]

        # المستوى 3: إجماع — نفس الترجمة من 2+ مودلات
        from collections import Counter
        counts = Counter(r[0] for r in rows)
        most_common, count = counts.most_common(1)[0]
        if count >= 2:
            return most_common

        # المستوى 4: أعلى model_priority
        priorities = self.get_model_priorities(game_name)
        # نقطة الافتراضي 0 إن لم يُحدَّد
        rows_by_prio = sorted(rows, key=lambda r: priorities.get(r[1], 0), reverse=True)
        top_prio = priorities.get(rows_by_prio[0][1], 0)
        if top_prio > 0:
            return rows_by_prio[0][0]

        # المستوى 5: الأحدث
        rows_by_time = sorted(rows, key=lambda r: r[4] or "", reverse=True)
        return rows_by_time[0][0]

    def iter_best_translations(self, game_name: str, model_filter: str = "",
                                deprioritize_suffix: str = ""):
        """مولّد يمرّ على كل النصوص الفريدة في اللعبة ويُرجع (original, best_translation).
        إذا حُدّد model_filter غير فارغ، يُرجع ترجمة هذا المودل فقط (بلا دمج هرمي).

        deprioritize_suffix: يُمرَّر إلى get_best — يفضّل المودلات بدون الـ suffix.

        ⚠ يُتجاوز كل نص يطابق skip_patterns (يُترَك بالإنجليزية تلقائياً
        لأن ArabicFontFixer لن يجده في _staticTr → لن يستبدله).
        """
        # حمّل skip_patterns مرة واحدة قبل البدء
        try:
            from engine import skip_patterns
            skip_pats = skip_patterns.get_patterns()
        except Exception:
            skip_pats = []

        conn = self._get_conn(game_name)
        if model_filter:
            # فلتر بمودل واحد — لا حاجة للهرمية
            rows = conn.execute("""
                SELECT original_text, translated_text
                FROM translations
                WHERE model_used = ?
                ORDER BY original_text
            """, (model_filter,)).fetchall()
            for r in rows:
                # تخطّى لو يطابق skip_patterns
                if skip_pats:
                    try:
                        if skip_patterns.matches(r[0], skip_pats):
                            continue
                    except Exception:
                        pass
                yield r[0], r[1]
            return
        # كل المودلات — طبّق الدمج الهرمي على كل نص فريد
        rows = conn.execute(
            "SELECT DISTINCT original_text FROM translations ORDER BY original_text"
        ).fetchall()
        for r in rows:
            # تخطّى لو يطابق skip_patterns (يبقى بالإنجليزية في اللعبة)
            if skip_pats:
                try:
                    if skip_patterns.matches(r[0], skip_pats):
                        continue
                except Exception:
                    pass
            best = self.get_best(game_name, r[0], deprioritize_suffix=deprioritize_suffix)
            if best:
                yield r[0], best

    # ── Learning cache ────────────────────────────────────────────────────

    def record_mode_success(self, game_name: str, mode: str):
        """يُحدّث إحصاء نجاح لـ mode محدد. للـ Learning cache."""
        conn = self._get_conn(game_name)
        conn.execute("""
            INSERT INTO mode_stats (mode, success_count, last_used_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(mode) DO UPDATE SET
                success_count = success_count + 1,
                last_used_at  = CURRENT_TIMESTAMP
        """, (mode,))
        conn.commit()

    def record_mode_failure(self, game_name: str, mode: str):
        conn = self._get_conn(game_name)
        conn.execute("""
            INSERT INTO mode_stats (mode, failure_count, last_used_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(mode) DO UPDATE SET
                failure_count = failure_count + 1,
                last_used_at  = CURRENT_TIMESTAMP
        """, (mode,))
        conn.commit()

    def get_mode_stats(self, game_name: str) -> list[dict]:
        """يُرجع إحصاءات الأوضاع مرتّبة بمعدل النجاح."""
        conn = self._get_conn(game_name)
        rows = conn.execute("""
            SELECT mode, success_count, failure_count,
                   CAST(success_count AS REAL) / (success_count + failure_count + 0.001) AS rate,
                   last_used_at
            FROM mode_stats
            ORDER BY rate DESC, success_count DESC
        """).fetchall()
        return [{
            "mode": r[0], "success": r[1], "failure": r[2],
            "rate": float(r[3]), "last_used": r[4],
        } for r in rows]

    def get_best_mode(self, game_name: str, default: str = "tiered") -> str:
        """يُرجع الـ mode الذي نجح أكثر تاريخياً (للاقتراح الذكي)."""
        stats = self.get_mode_stats(game_name)
        if not stats:
            return default
        # أكثر من 5 محاولات على الأقل، وإلا يبقى الافتراضي
        if stats[0]["success"] + stats[0]["failure"] < 5:
            return default
        return stats[0]["mode"]

    def mark_failed(self, game_name: str, original_text: str, reason: str = "",
                    model_used: str = ""):
        conn = self._get_conn(game_name)
        # عند تكرار محاولة فاشلة، نُحدّث السبب والمودل لأحدث محاولة
        conn.execute(
            "INSERT INTO failed_translations (original_text, reason, model_used) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(original_text) DO UPDATE SET "
            "reason=excluded.reason, model_used=excluded.model_used",
            (original_text, reason, model_used)
        )
        conn.commit()

    def is_failed(self, game_name: str, original_text: str) -> bool:
        conn = self._get_conn(game_name)
        return conn.execute(
            "SELECT 1 FROM failed_translations WHERE original_text = ?",
            (original_text,)
        ).fetchone() is not None

    def get_failed_page(self, game_name: str, offset: int = 0, limit: int = 50,
                        search: str = "", exact_match: bool = False) -> list:
        """يُرجع صفحة من الترجمات الفاشلة مع سببها."""
        conn = self._get_conn(game_name)
        conditions, params = [], []
        if search:
            if exact_match:
                conditions.append(
                    "(original_text = ? COLLATE NOCASE OR reason = ? COLLATE NOCASE)"
                )
                params.extend([search, search])
            else:
                pattern = f"%{search}%"
                conditions.append("(original_text LIKE ? OR reason LIKE ?)")
                params.extend([pattern, pattern])
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT original_text, reason, created_at, model_used "
            f"FROM failed_translations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params
        ).fetchall()
        return [
            {
                "original":   r[0],
                "reason":     r[1] or "",
                "created_at": r[2] or "",
                "model":      (r[3] or "") if len(r) > 3 else "",
            }
            for r in rows
        ]

    def count_failed(self, game_name: str, search: str = "",
                     exact_match: bool = False) -> int:
        conn = self._get_conn(game_name)
        conditions, params = [], []
        if search:
            if exact_match:
                conditions.append(
                    "(original_text = ? COLLATE NOCASE OR reason = ? COLLATE NOCASE)"
                )
                params.extend([search, search])
            else:
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

    def _build_search_conditions(self, search: str, model_filter: str,
                                  exact_match: bool, health_filter: str) -> tuple[list, list]:
        """يبني WHERE conditions و params مشتركة بين count و get_page.

        health_filter:
          "manual"    → mode_used = 'manual'
          "preferred" → is_preferred = 1
          "conflict"  → original_text له ترجمات من 2+ مودلات (subquery)
          (broken يُطبَّق post-fetch في الـ caller — يحتاج regex)
        """
        conditions, params = [], []
        if search:
            if exact_match:
                conditions.append(
                    "(original_text = ? COLLATE NOCASE OR "
                    "translated_text = ? COLLATE NOCASE)"
                )
                params.extend([search, search])
            else:
                pattern = f"%{search}%"
                conditions.append("(original_text LIKE ? OR translated_text LIKE ?)")
                params.extend([pattern, pattern])
        if model_filter and model_filter != "All Models":
            conditions.append("model_used = ?")
            params.append(model_filter)
        if health_filter == "manual":
            conditions.append("LOWER(COALESCE(mode_used,'')) = 'manual'")
        elif health_filter == "preferred":
            conditions.append("COALESCE(is_preferred, 0) = 1")
        elif health_filter == "conflict":
            conditions.append(
                "original_text IN (SELECT original_text FROM translations "
                "GROUP BY original_text HAVING COUNT(DISTINCT model_used) > 1)"
            )
        return conditions, params

    def get_page(self, game_name: str, offset: int = 0, limit: int = 50,
                 search: str = "", model_filter: str = "",
                 exact_match: bool = False, health_filter: str = "") -> list:
        conn = self._get_conn(game_name)
        conditions, params = self._build_search_conditions(
            search, model_filter, exact_match, health_filter
        )
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params = list(params) + [limit, offset]
        rows = conn.execute(
            f"SELECT original_text, translated_text, model_used, hit_count, "
            f"       COALESCE(mode_used, ''), COALESCE(is_preferred, 0) "
            f"FROM translations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params
        ).fetchall()
        return [
            {
                "original": r[0], "translated": r[1], "model": r[2],
                "hits": r[3], "mode_used": r[4], "is_preferred": bool(r[5]),
            }
            for r in rows
        ]

    def count_entries(self, game_name: str, search: str = "", model_filter: str = "",
                      exact_match: bool = False, health_filter: str = "") -> int:
        conn = self._get_conn(game_name)
        conditions, params = self._build_search_conditions(
            search, model_filter, exact_match, health_filter
        )
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return conn.execute(f"SELECT COUNT(*) FROM translations {where}", params).fetchone()[0]

    def iter_all_for_broken_check(self, game_name: str, search: str = "",
                                   model_filter: str = "", exact_match: bool = False):
        """مولّد لكل الصفوف (للفلتر post-process مثل 'broken').
        يُرجع dicts مثل get_page لكن بدون LIMIT/OFFSET."""
        conn = self._get_conn(game_name)
        conditions, params = self._build_search_conditions(
            search, model_filter, exact_match, ""
        )
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cursor = conn.execute(
            f"SELECT original_text, translated_text, model_used, hit_count, "
            f"       COALESCE(mode_used, ''), COALESCE(is_preferred, 0) "
            f"FROM translations {where} ORDER BY id DESC",
            params
        )
        for r in cursor:
            yield {
                "original": r[0], "translated": r[1], "model": r[2],
                "hits": r[3], "mode_used": r[4], "is_preferred": bool(r[5]),
            }

    def get_models_for_game(self, game_name: str) -> List[str]:
        conn = self._get_conn(game_name)
        rows = conn.execute(
            "SELECT DISTINCT model_used FROM translations ORDER BY model_used"
        ).fetchall()
        return [r[0] for r in rows if r[0]]

    def update_translation(self, game_name: str, original_text: str,
                           new_translated: str, mode_used: str = ""):
        conn = self._get_conn(game_name)
        if mode_used:
            conn.execute(
                "UPDATE translations SET translated_text = ?, mode_used = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE original_text = ?",
                (new_translated, mode_used, original_text)
            )
        else:
            conn.execute(
                "UPDATE translations SET translated_text = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE original_text = ?",
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

    def get_if_model_matches(self, game_name: str, original_text: str,
                             model_name: str) -> Optional[str]:
        """يُرجع الترجمة فقط إن كان النموذج يطابق الفلتر. أسرع من get_by_model
        لاستعلامات الـ proxy الفردية. يُحدّث hit_count تلقائياً."""
        conn = self._get_conn(game_name)
        row = conn.execute(
            "SELECT translated_text FROM translations "
            "WHERE original_text = ? AND model_used = ?",
            (original_text, model_name)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE translations SET hit_count = hit_count + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE original_text = ?",
                (original_text,)
            )
            conn.commit()
            return row[0]
        return None

    def count_by_model(self, game_name: str, model_name: str = "") -> int | dict:
        """
        إن مُرِّر model_name → عدد ترجمات هذا المودل (int).
        إن لم يُمرَّر → dict {model: count} لكل المودلات في اللعبة.
        """
        conn = self._get_conn(game_name)
        if model_name:
            return conn.execute(
                "SELECT COUNT(*) FROM translations WHERE model_used = ?",
                (model_name,)
            ).fetchone()[0]
        # لا فلتر → خريطة كاملة
        rows = conn.execute(
            "SELECT model_used, COUNT(*) FROM translations "
            "GROUP BY model_used ORDER BY model_used"
        ).fetchall()
        return {r[0]: r[1] for r in rows if r[0]}

    def close(self):
        if hasattr(self._local, "conns"):
            for conn in self._local.conns.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._local.conns = {}
