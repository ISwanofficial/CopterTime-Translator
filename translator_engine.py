from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from deep_translator import GoogleTranslator


CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")
URL_EMAIL_RE = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\S+)", re.I)
ONLY_TECH_RE = re.compile(r"^[\W\d_]+$")


class TranslationCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS translations "
                "(key TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def get(self, source: str) -> str | None:
        key = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT target FROM translations WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, source: str, target: str) -> None:
        key = hashlib.sha256(source.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO translations(key, source, target) VALUES (?, ?, ?)",
                (key, source, target),
            )


class Glossary:
    def __init__(self, path: Path | None) -> None:
        self.entries: list[tuple[str, str]] = []
        if path and path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    source = (row.get("English") or "").strip()
                    target = (row.get("Russian") or "").strip()
                    if source and target:
                        self.entries.append((source, target))
        self.entries.sort(key=lambda item: len(item[0]), reverse=True)

    def protect(self, text: str) -> tuple[str, dict[str, str]]:
        replacements: dict[str, str] = {}
        protected = text
        for index, (source, target) in enumerate(self.entries):
            token = f"ZZCT{index:04d}ZZ"
            pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.I)
            if pattern.search(protected):
                protected = pattern.sub(token, protected)
                replacements[token] = target
        return protected, replacements

    @staticmethod
    def restore(text: str, replacements: dict[str, str]) -> str:
        result = text
        for token, target in replacements.items():
            result = re.sub(re.escape(token), target, result, flags=re.I)
        return result


class TechnicalPostProcessor:
    RULES = [
        (re.compile(r"\bФото\s*\(Снимок\)\b", re.I), "Фото"),
        (re.compile(r"\bВКЛ\s*/\s*ВЫКЛ\b", re.I), "Вкл./выкл."),
        (re.compile(r"\bРазъем\b", re.I), "Разъём"),
        (re.compile(r"\bкабель-трос\s+подводный аппарат\s*\(ROV\)\s*Вилка\b", re.I),
         "Разъём кабеля-троса подводного аппарата (ROV)"),
        (re.compile(r"\bкабель-трос\s+Разъём RC\b", re.I), "Разъём RC кабеля-троса"),
        (re.compile(r"\bПо пути есть (?:еще|ещё) аксессуары\.?\b", re.I), "Дополнительные аксессуары"),
    ]

    @classmethod
    def apply(cls, text: str) -> str:
        result = text
        for pattern, replacement in cls.RULES:
            result = pattern.sub(replacement, result)
        result = re.sub(r"[ \t]+([,.;:!?])", r"\1", result)
        result = re.sub(r" {2,}", " ", result)
        return result


class OnlineTranslator:
    def __init__(
        self,
        glossary_path: Path | None,
        cache_path: Path,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.glossary = Glossary(glossary_path)
        self.cache = TranslationCache(cache_path)
        self.log = log_callback or (lambda _msg: None)
        self.engine = GoogleTranslator(source="en", target="ru")

    @staticmethod
    def should_translate(text: str) -> bool:
        stripped = text.strip()
        if not stripped or len(stripped) < 2:
            return False
        if ONLY_TECH_RE.fullmatch(stripped):
            return False
        latin = len(LATIN_RE.findall(stripped))
        cyrillic = len(CYRILLIC_RE.findall(stripped))
        if latin == 0 or cyrillic > latin:
            return False
        if URL_EMAIL_RE.fullmatch(stripped):
            return False
        return True

    @staticmethod
    def split_text(text: str, max_chars: int = 3000) -> list[str]:
        """
        Split text safely for online translation services.

        Handles:
        - normal paragraphs split by sentences;
        - very long sentences;
        - OCR/PDFCandy blocks with little punctuation;
        - single words/URLs longer than the service limit.
        """
        if len(text) <= max_chars:
            return [text]

        chunks: list[str] = []
        current = ""

        def flush() -> None:
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        def add_piece(piece: str) -> None:
            nonlocal current
            piece = piece.strip()
            if not piece:
                return

            if len(piece) > max_chars:
                flush()
                words = piece.split()
                if len(words) <= 1:
                    for start in range(0, len(piece), max_chars):
                        chunks.append(piece[start:start + max_chars])
                    return

                temp = ""
                for word in words:
                    if len(word) > max_chars:
                        if temp:
                            chunks.append(temp)
                            temp = ""
                        for start in range(0, len(word), max_chars):
                            chunks.append(word[start:start + max_chars])
                        continue

                    candidate = f"{temp} {word}".strip()
                    if len(candidate) > max_chars:
                        if temp:
                            chunks.append(temp)
                        temp = word
                    else:
                        temp = candidate
                if temp:
                    chunks.append(temp)
                return

            candidate = f"{current} {piece}".strip()
            if len(candidate) > max_chars:
                flush()
                current = piece
            else:
                current = candidate

        paragraphs = re.split(r"\n\s*\n", text)
        for paragraph in paragraphs:
            sentences = re.split(r"(?<=[.!?;:])\s+", paragraph)
            for sentence in sentences:
                add_piece(sentence)
            flush()

        return [chunk for chunk in chunks if chunk]

    def translate_text(self, text: str) -> str:
        if not self.should_translate(text):
            return text

        cached = self.cache.get(text)
        if cached is not None:
            return cached

        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        core = text.strip()
        protected, replacements = self.glossary.protect(core)

        parts = []
        for chunk in self.split_text(protected):
            last_error = None
            for attempt in range(3):
                try:
                    parts.append(self.engine.translate(chunk))
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(2 + attempt * 2)
            if last_error is not None:
                raise RuntimeError(f"Сервис перевода не ответил: {last_error}")

        result = " ".join(part.strip() for part in parts if part)
        result = self.glossary.restore(result, replacements)
        result = TechnicalPostProcessor.apply(result)
        result = leading + result + trailing
        self.cache.put(text, result)
        return result
