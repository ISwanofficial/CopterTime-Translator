from __future__ import annotations

import csv
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from coptertime_docs.config import (
    DATABASE_PATH,
    DEFAULT_BRANDS,
    LEGACY_GLOSSARY_PATH,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def text_hash(value: str) -> str:
    normalized = normalize_text(value).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE
                );

                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id INTEGER NOT NULL,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(brand_id, source_text COLLATE NOCASE),
                    FOREIGN KEY(brand_id) REFERENCES brands(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_hash TEXT NOT NULL UNIQUE,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    source_language TEXT NOT NULL DEFAULT 'en',
                    target_language TEXT NOT NULL DEFAULT 'ru',
                    uses INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    status TEXT NOT NULL,
                    paragraphs_total INTEGER NOT NULL DEFAULT 0,
                    translated_new INTEGER NOT NULL DEFAULT 0,
                    translated_from_memory INTEGER NOT NULL DEFAULT 0,
                    english_fragments INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_terms_source
                ON terms(source_text COLLATE NOCASE);

                CREATE INDEX IF NOT EXISTS idx_tm_source_hash
                ON translation_memory(source_hash);
                """
            )

            for brand in DEFAULT_BRANDS:
                db.execute(
                    "INSERT OR IGNORE INTO brands(name) VALUES (?)",
                    (brand,),
                )

        self._seed_default_terms()
        self._import_legacy_glossary_once()

    def _seed_default_terms(self) -> None:
        defaults = [
            ("General", "Power Button", "Кнопка питания"),
            ("General", "Remote Controller", "Пульт управления"),
            ("General", "Quick Start Guide", "Краткое руководство"),
            ("General", "User Manual", "Руководство пользователя"),
            ("General", "Battery Life", "Время работы от аккумулятора"),
            ("General", "Firmware Upgrade", "Обновление прошивки"),
            ("General", "White Balance", "Баланс белого"),
            ("General", "Exposure Compensation", "Компенсация экспозиции"),
            ("General", "Photo", "Фото"),
            ("General", "Accessories", "Аксессуары"),
            ("QYSEA", "Thruster", "Движитель"),
            ("QYSEA", "Thrusters", "Движители"),
            ("QYSEA", "Tether", "Кабель-трос"),
            ("QYSEA", "Tether Spool", "Катушка кабеля-троса"),
            ("QYSEA", "Depth Holding", "Удержание глубины"),
            ("QYSEA", "Depth Lock", "Фиксация глубины"),
            ("QYSEA", "Posture Lock", "Фиксация положения"),
            ("QYSEA", "ROV", "подводный аппарат"),
            ("QYSEA", "Go Dive", "Начать погружение"),
            ("BETAFPV", "Angle Mode", "Режим стабилизации"),
            ("BETAFPV", "Acro Mode", "Акро-режим"),
            ("BETAFPV", "Air Mode", "Air Mode"),
            ("DJI", "Gimbal", "Подвес"),
            ("DJI", "Tracking", "Отслеживание"),
            ("FIMI", "Return to Home", "Возврат домой"),
            ("ToolkitRC", "Storage Mode", "Режим хранения"),
        ]
        for brand, source, target in defaults:
            self.upsert_term(brand, source, target, approved=True)

    def _import_legacy_glossary_once(self) -> None:
        marker = self.path.parent / ".legacy_glossary_imported"
        if marker.exists() or not LEGACY_GLOSSARY_PATH.exists():
            return

        try:
            with LEGACY_GLOSSARY_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            for row in rows:
                if len(row) < 2:
                    continue
                source, target = row[0].strip(), row[1].strip()
                if not source or not target:
                    continue
                if source.casefold() in {"english", "source", "en"}:
                    continue
                brand = row[2].strip() if len(row) >= 3 and row[2].strip() else "General"
                self.upsert_term(brand, source, target, approved=True)
            marker.write_text(utc_now(), encoding="utf-8")
        except Exception:
            # Импорт старого файла не должен мешать запуску программы.
            pass

    def list_brands(self) -> list[str]:
        with self.connect() as db:
            rows = db.execute("SELECT name FROM brands ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def ensure_brand(self, name: str) -> int:
        name = normalize_text(name) or "General"
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO brands(name) VALUES (?)", (name,))
            row = db.execute(
                "SELECT id FROM brands WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
        return int(row["id"])

    def upsert_term(
        self,
        brand: str,
        source_text: str,
        target_text: str,
        approved: bool = True,
        notes: str = "",
    ) -> None:
        source_text = normalize_text(source_text)
        target_text = normalize_text(target_text)
        if not source_text or not target_text:
            raise ValueError("Исходный термин и перевод не могут быть пустыми.")

        brand_id = self.ensure_brand(brand)
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO terms(
                    brand_id, source_text, target_text, approved, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(brand_id, source_text)
                DO UPDATE SET
                    target_text = excluded.target_text,
                    approved = excluded.approved,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    brand_id,
                    source_text,
                    target_text,
                    int(approved),
                    notes.strip(),
                    now,
                    now,
                ),
            )

    def delete_term(self, term_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM terms WHERE id = ?", (term_id,))

    def search_terms(
        self,
        query: str = "",
        brand: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        clauses = []
        params: list[object] = []

        if query.strip():
            clauses.append(
                "(t.source_text LIKE ? OR t.target_text LIKE ? OR t.notes LIKE ?)"
            )
            pattern = f"%{query.strip()}%"
            params.extend([pattern, pattern, pattern])

        if brand and brand != "Все бренды":
            clauses.append("b.name = ? COLLATE NOCASE")
            params.append(brand)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    t.id,
                    b.name AS brand,
                    t.source_text,
                    t.target_text,
                    t.approved,
                    t.notes,
                    t.updated_at
                FROM terms t
                JOIN brands b ON b.id = t.brand_id
                {where}
                ORDER BY b.name, LENGTH(t.source_text) DESC, t.source_text
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def glossary_for_brand(self, brand: str) -> list[tuple[str, str]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT t.source_text, t.target_text
                FROM terms t
                JOIN brands b ON b.id = t.brand_id
                WHERE t.approved = 1
                  AND (b.name = 'General' OR b.name = ? COLLATE NOCASE)
                ORDER BY LENGTH(t.source_text) DESC
                """,
                (brand,),
            ).fetchall()
        return [(row["source_text"], row["target_text"]) for row in rows]

    def memory_get(self, source_text: str) -> str | None:
        key = text_hash(source_text)
        with self.connect() as db:
            row = db.execute(
                "SELECT target_text FROM translation_memory WHERE source_hash = ?",
                (key,),
            ).fetchone()
            if row:
                db.execute(
                    """
                    UPDATE translation_memory
                    SET uses = uses + 1, updated_at = ?
                    WHERE source_hash = ?
                    """,
                    (utc_now(), key),
                )
        return row["target_text"] if row else None

    def memory_put(self, source_text: str, target_text: str) -> None:
        source_text = normalize_text(source_text)
        target_text = normalize_text(target_text)
        if not source_text or not target_text:
            return

        key = text_hash(source_text)
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO translation_memory(
                    source_hash, source_text, target_text, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_hash)
                DO UPDATE SET
                    target_text = excluded.target_text,
                    updated_at = excluded.updated_at
                """,
                (key, source_text, target_text, now, now),
            )

    def record_document(
        self,
        source_path: str,
        output_path: str,
        brand: str,
        status: str,
        paragraphs_total: int,
        translated_new: int,
        translated_from_memory: int,
        english_fragments: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO documents(
                    source_path, output_path, brand, status,
                    paragraphs_total, translated_new,
                    translated_from_memory, english_fragments, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_path,
                    output_path,
                    brand,
                    status,
                    paragraphs_total,
                    translated_new,
                    translated_from_memory,
                    english_fragments,
                    utc_now(),
                ),
            )
