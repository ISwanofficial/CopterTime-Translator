from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from deep_translator import GoogleTranslator

from coptertime_docs.config import MAX_TRANSLATION_CHARS
from coptertime_docs.storage.database import Database, normalize_text


ProgressCallback = Callable[[str], None]


@dataclass
class TranslationResult:
    text: str
    from_memory: bool


class TranslationEngine:
    def __init__(
        self,
        database: Database,
        source_language: str = "en",
        target_language: str = "ru",
    ) -> None:
        self.database = database
        self.translator = GoogleTranslator(
            source=source_language,
            target=target_language,
        )

    def translate(
        self,
        text: str,
        brand: str,
        progress: ProgressCallback | None = None,
    ) -> TranslationResult:
        original = text or ""
        normalized = normalize_text(original)

        if not normalized or not self._needs_translation(normalized):
            return TranslationResult(original, from_memory=False)

        cached = self.database.memory_get(normalized)
        if cached:
            result = self._apply_glossary(cached, brand)
            return TranslationResult(result, from_memory=True)

        protected, tokens = self._protect_values(normalized)
        chunks = self._split_text(protected)
        translated_chunks: list[str] = []

        for index, chunk in enumerate(chunks, start=1):
            if progress and len(chunks) > 1:
                progress(f"Перевод части {index}/{len(chunks)}")
            translated_chunks.append(self._translate_with_retry(chunk))

        translated = " ".join(translated_chunks)
        translated = self._restore_values(translated, tokens)
        translated = self._apply_glossary(translated, brand)
        translated = self._postprocess(translated)

        self.database.memory_put(normalized, translated)
        return TranslationResult(translated, from_memory=False)

    @staticmethod
    def _needs_translation(text: str) -> bool:
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
        if not letters:
            return False
        latin = len(re.findall(r"[A-Za-z]", text))
        cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
        return latin >= 2 and latin > cyrillic * 0.35

    def _translate_with_retry(self, text: str) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = self.translator.translate(text)
                if not result:
                    raise RuntimeError("Сервис перевода вернул пустой ответ.")
                return result
            except Exception as error:
                last_error = error
                time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"Не удалось перевести фрагмент: {last_error}")

    @staticmethod
    def _split_text(text: str) -> list[str]:
        if len(text) <= MAX_TRANSLATION_CHARS:
            return [text]

        sentences = re.split(r"(?<=[.!?;:])\s+", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            if len(sentence) > MAX_TRANSLATION_CHARS:
                words = sentence.split()
                for word in words:
                    candidate = f"{current} {word}".strip()
                    if len(candidate) > MAX_TRANSLATION_CHARS and current:
                        chunks.append(current)
                        current = word
                    else:
                        current = candidate
                continue

            candidate = f"{current} {sentence}".strip()
            if len(candidate) > MAX_TRANSLATION_CHARS and current:
                chunks.append(current)
                current = sentence
            else:
                current = candidate

        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _protect_values(text: str) -> tuple[str, dict[str, str]]:
        patterns = [
            r"\b\d+(?:[.,]\d+)?\s?(?:V|A|W|Wh|mAh|Ah|Hz|kHz|MHz|GHz|fps|MB/s|Mbps|GB|TB|mm|cm|m|km|kg|g|°C|°F|%)\b",
            r"\b(?:FIFISH|QYSEA|BETAFPV|DJI|FIMI|MJX|ToolkitRC|ELRS|FPV|ROV|Wi-?Fi|microSD|USB|HDMI|JPEG|DNG|NTSC|PAL)\b",
            r"\b[A-Z]{2,}[A-Z0-9._/-]*\b",
        ]

        tokens: dict[str, str] = {}
        protected = text
        counter = 0

        def replace(match: re.Match) -> str:
            nonlocal counter
            key = f"ZXQ{counter}QXZ"
            tokens[key] = match.group(0)
            counter += 1
            return key

        for pattern in patterns:
            protected = re.sub(pattern, replace, protected, flags=re.IGNORECASE)

        return protected, tokens

    @staticmethod
    def _restore_values(text: str, tokens: dict[str, str]) -> str:
        restored = text
        for key, value in tokens.items():
            restored = restored.replace(key, value)
            restored = restored.replace(key.lower(), value)
        return restored

    def _apply_glossary(self, text: str, brand: str) -> str:
        result = text
        for source, target in self.database.glossary_for_brand(brand):
            result = re.sub(
                rf"(?<!\w){re.escape(source)}(?!\w)",
                target,
                result,
                flags=re.IGNORECASE,
            )
        return result

    @staticmethod
    def _postprocess(text: str) -> str:
        replacements = {
            "Фото (Снимок)": "Фото",
            "фото (снимок)": "фото",
            "По пути есть еще аксессуары": "Линейка аксессуаров продолжает расширяться",
            "По пути есть ещё аксессуары": "Линейка аксессуаров продолжает расширяться",
            "ВКЛ/ВЫКЛ": "ВКЛ./ВЫКЛ.",
        }
        result = text
        for old, new in replacements.items():
            result = result.replace(old, new)
        result = re.sub(r"\s+([,.;:!?])", r"\1", result)
        result = re.sub(r"[ \t]{2,}", " ", result)
        return result.strip()
