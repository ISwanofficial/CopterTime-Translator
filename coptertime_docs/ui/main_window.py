from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from coptertime_docs import __version__
from coptertime_docs.documents.docx_processor import DocxProcessor
from coptertime_docs.storage.database import Database
from coptertime_docs.translator.engine import TranslationEngine
from coptertime_docs.ui.glossary_window import GlossaryWindow


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.database = Database()
        self.engine = TranslationEngine(self.database)
        self.processor = DocxProcessor(self.database, self.engine)
        self.events: queue.Queue = queue.Queue()

        self.title(f"CopterTime Docs v{__version__}")
        self.geometry("860x650")
        self.minsize(760, 590)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.brand_var = tk.StringVar(value="General")
        self.status_var = tk.StringVar(value="Готово к работе")
        self.progress_var = tk.DoubleVar(value=0)

        self._build()
        self.after(100, self._process_events)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(20, 18, 20, 12))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="CopterTime Docs",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Перевод технических инструкций с терминологией CopterTime",
        ).pack(anchor="w", pady=(3, 0))

        form = ttk.LabelFrame(self, text="Документ", padding=16)
        form.pack(fill="x", padx=20, pady=(0, 12))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Исходный DOCX").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", padx=10
        )
        ttk.Button(form, text="Выбрать…", command=self.choose_source).grid(
            row=0, column=2
        )

        ttk.Label(form, text="Результат").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(form, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=10, pady=(12, 0)
        )
        ttk.Button(form, text="Выбрать…", command=self.choose_output).grid(
            row=1, column=2, pady=(12, 0)
        )

        ttk.Label(form, text="Бренд").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.brand_box = ttk.Combobox(
            form,
            textvariable=self.brand_var,
            values=self.database.list_brands(),
            state="readonly",
            width=24,
        )
        self.brand_box.grid(row=2, column=1, sticky="w", padx=10, pady=(12, 0))

        actions = ttk.Frame(self, padding=(20, 0))
        actions.pack(fill="x")
        self.analyze_button = ttk.Button(
            actions,
            text="Проверить документ",
            command=self.analyze_document,
        )
        self.analyze_button.pack(side="left")
        self.translate_button = ttk.Button(
            actions,
            text="Перевести",
            command=self.start_translation,
        )
        self.translate_button.pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Словари",
            command=self.open_glossary,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Открыть папку результата",
            command=self.open_output_folder,
        ).pack(side="right")

        progress_frame = ttk.Frame(self, padding=(20, 14, 20, 6))
        progress_frame.pack(fill="x")
        self.progress = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
        )
        self.progress.pack(fill="x")
        ttk.Label(progress_frame, textvariable=self.status_var).pack(
            anchor="w", pady=(5, 0)
        )

        log_frame = ttk.LabelFrame(self, text="Журнал", padding=10)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(6, 18))
        self.log = tk.Text(log_frame, wrap="word", state="disabled", height=15)
        self.log.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)

        self._write_log(
            "v0.4 готова. Основной формат: DOCX. "
            "Для PDF сначала используйте конвертацию в DOCX."
        )

    def choose_source(self) -> None:
        filename = filedialog.askopenfilename(
            title="Выберите документ",
            filetypes=[("Документ Word", "*.docx")],
        )
        if not filename:
            return
        source = Path(filename)
        self.source_var.set(str(source))
        suggested = source.with_name(f"{source.stem}_RU.docx")
        self.output_var.set(str(suggested))
        self._write_log(f"Выбран документ: {source.name}")

    def choose_output(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Сохранить результат",
            defaultextension=".docx",
            filetypes=[("Документ Word", "*.docx")],
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else "",
        )
        if filename:
            self.output_var.set(filename)

    def analyze_document(self) -> None:
        source = self._validated_source()
        if source is None:
            return
        try:
            analysis = self.processor.analyze(source)
        except Exception as error:
            messagebox.showerror("Ошибка анализа", str(error), parent=self)
            return

        report = (
            f"Анализ: абзацев — {analysis.paragraphs}; "
            f"текстовых фрагментов — {analysis.text_fragments}; "
            f"таблиц — {analysis.tables}; изображений — {analysis.images}; "
            f"слов — {analysis.words}; "
            f"фрагментов с английским текстом — {analysis.english_fragments}."
        )
        self._write_log(report)
        messagebox.showinfo("Диагностика документа", report, parent=self)

    def start_translation(self) -> None:
        source = self._validated_source()
        if source is None:
            return

        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("Результат", "Укажите путь для результата.", parent=self)
            return

        output = Path(output_text)
        if source.resolve() == output.resolve():
            messagebox.showwarning(
                "Результат",
                "Исходный файл и результат не должны совпадать.",
                parent=self,
            )
            return

        self._set_busy(True)
        self.progress_var.set(0)
        self.status_var.set("Подготовка…")
        self._write_log(f"Начат перевод: {source.name}")

        thread = threading.Thread(
            target=self._translation_worker,
            args=(source, output, self.brand_var.get()),
            daemon=True,
        )
        thread.start()

    def _translation_worker(self, source: Path, output: Path, brand: str) -> None:
        try:
            report = self.processor.translate(
                source,
                output,
                brand,
                progress=lambda current, total, text: self.events.put(
                    ("progress", current, total, text)
                ),
            )
            self.events.put(("done", report))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]

                if kind == "progress":
                    _, current, total, text = event
                    percent = (current / total * 100) if total else 100
                    self.progress_var.set(percent)
                    self.status_var.set(f"Фрагмент {current} из {total}")
                    if current == 1 or current == total or current % 10 == 0:
                        self._write_log(f"{current}/{total}: {text}")

                elif kind == "done":
                    report = event[1]
                    self.progress_var.set(100)
                    self.status_var.set("Перевод завершён")
                    self._set_busy(False)
                    summary = (
                        f"Готово: новых переводов — {report.translated_new}; "
                        f"из памяти — {report.translated_from_memory}; "
                        f"пропущено — {report.skipped}; "
                        f"фрагментов с английским после проверки — "
                        f"{report.english_fragments_after}.\n\n"
                        f"Файл:\n{report.output_path}"
                    )
                    self._write_log(summary.replace("\n", " "))
                    messagebox.showinfo("Перевод завершён", summary, parent=self)

                elif kind == "error":
                    self._set_busy(False)
                    self.progress_var.set(0)
                    self.status_var.set("Ошибка")
                    self._write_log(f"Ошибка: {event[1]}")
                    messagebox.showerror("Ошибка перевода", event[1], parent=self)

        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def open_glossary(self) -> None:
        window = GlossaryWindow(self, self.database)
        window.grab_set()

    def open_output_folder(self) -> None:
        output = self.output_var.get().strip()
        target = Path(output).parent if output else Path.cwd()
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(target)  # type: ignore[attr-defined]
        except Exception as error:
            messagebox.showerror("Не удалось открыть папку", str(error), parent=self)

    def _validated_source(self) -> Path | None:
        value = self.source_var.get().strip()
        if not value:
            messagebox.showwarning("Документ", "Сначала выберите DOCX.", parent=self)
            return None
        source = Path(value)
        if not source.exists():
            messagebox.showerror("Документ", "Исходный файл не найден.", parent=self)
            return None
        if source.suffix.lower() != ".docx":
            messagebox.showwarning(
                "Формат",
                "В версии 0.4 поддерживается перевод DOCX.",
                parent=self,
            )
            return None
        return source

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.translate_button.configure(state=state)
        self.analyze_button.configure(state=state)

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def run_app() -> None:
    app = MainWindow()
    app.mainloop()
