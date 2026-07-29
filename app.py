from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, filedialog, messagebox, ttk
import tkinter as tk

from document_processor import DocumentProcessor
from exporter import export_docx_to_pdf
from translator_engine import OnlineTranslator

APP_TITLE = "CopterTime Translator v0.3"


class TranslatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x560")
        self.minsize(700, 520)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.source_var = StringVar()
        self.output_var = StringVar(value=str(Path.cwd() / "output"))
        self.glossary_var = StringVar(value=str(Path.cwd() / "glossary.csv"))
        self.translate_tables_var = BooleanVar(value=True)
        self.translate_headers_var = BooleanVar(value=True)
        self.use_glossary_var = BooleanVar(value=True)
        self.export_pdf_var = BooleanVar(value=True)

        self._build_ui()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="CopterTime Translator", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Быстрый перевод EN → RU без API-ключа. Нужен интернет.",
        ).pack(anchor="w", pady=(2, 16))

        source_box = ttk.LabelFrame(outer, text="Исходный документ", padding=12)
        source_box.pack(fill="x")
        ttk.Entry(source_box, textvariable=self.source_var).pack(side="left", fill="x", expand=True)
        ttk.Button(source_box, text="Выбрать…", command=self._choose_source).pack(side="left", padx=(8, 0))

        output_box = ttk.LabelFrame(outer, text="Папка результата", padding=12)
        output_box.pack(fill="x", pady=(12, 0))
        ttk.Entry(output_box, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(output_box, text="Выбрать…", command=self._choose_output).pack(side="left", padx=(8, 0))

        glossary_box = ttk.LabelFrame(outer, text="Словарь терминов", padding=12)
        glossary_box.pack(fill="x", pady=(12, 0))
        ttk.Entry(glossary_box, textvariable=self.glossary_var).pack(side="left", fill="x", expand=True)
        ttk.Button(glossary_box, text="Выбрать…", command=self._choose_glossary).pack(side="left", padx=(8, 0))
        ttk.Button(glossary_box, text="Открыть словарь", command=self._open_glossary).pack(side="left", padx=(8, 0))

        options = ttk.LabelFrame(outer, text="Параметры", padding=12)
        options.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(options, text="Использовать словарь CopterTime", variable=self.use_glossary_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Переводить таблицы", variable=self.translate_tables_var).grid(row=0, column=1, sticky="w", padx=(24, 0))
        ttk.Checkbutton(options, text="Переводить колонтитулы", variable=self.translate_headers_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text="Создать PDF через Word/LibreOffice", variable=self.export_pdf_var).grid(row=1, column=1, sticky="w", padx=(24, 0), pady=(6, 0))

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(14, 0))
        self.start_button = ttk.Button(action_row, text="ПЕРЕВЕСТИ", command=self._start)
        self.start_button.pack(side="left")
        self.progress = ttk.Progressbar(action_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self.progress_label = ttk.Label(action_row, text="0%")
        self.progress_label.pack(side="left", padx=(8, 0))

        log_box = ttk.LabelFrame(outer, text="Журнал", padding=8)
        log_box.pack(fill="both", expand=True, pady=(12, 0))
        self.log = tk.Text(log_box, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

    def _choose_source(self) -> None:
        filename = filedialog.askopenfilename(
            title="Выберите документ",
            filetypes=[("Документы", "*.docx *.pdf"), ("Word", "*.docx"), ("PDF", "*.pdf")],
        )
        if filename:
            self.source_var.set(filename)

    def _choose_output(self) -> None:
        folder = filedialog.askdirectory(title="Папка результата")
        if folder:
            self.output_var.set(folder)

    def _choose_glossary(self) -> None:
        filename = filedialog.askopenfilename(
            title="Выберите словарь",
            filetypes=[("CSV", "*.csv"), ("Все файлы", "*.*")],
        )
        if filename:
            self.glossary_var.set(filename)

    def _open_glossary(self) -> None:
        import os
        glossary = Path(self.glossary_var.get().strip().strip('"'))
        if not glossary.exists():
            messagebox.showerror(APP_TITLE, "Файл словаря не найден.")
            return
        try:
            os.startfile(str(glossary))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Не удалось открыть словарь:\n{exc}")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_progress(self, done: int, total: int) -> None:
        percent = 0 if total <= 0 else int(done * 100 / total)
        self.progress.configure(maximum=max(total, 1), value=done)
        self.progress_label.configure(text=f"{percent}%")

    def _start(self) -> None:
        source = Path(self.source_var.get().strip().strip('"'))
        output = Path(self.output_var.get().strip().strip('"'))
        glossary = Path(self.glossary_var.get().strip().strip('"'))

        if not source.exists() or source.suffix.lower() not in {".docx", ".pdf"}:
            messagebox.showerror(APP_TITLE, "Выберите существующий DOCX или PDF.")
            return
        if self.use_glossary_var.get() and not glossary.exists():
            messagebox.showerror(APP_TITLE, "Файл словаря не найден.")
            return

        output.mkdir(parents=True, exist_ok=True)
        self.start_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.progress_label.configure(text="0%")
        self._append_log(f"Исходный файл: {source}")
        self._append_log("Запуск…")

        args = {
            "source": source,
            "output": output,
            "glossary": glossary if self.use_glossary_var.get() else None,
            "tables": self.translate_tables_var.get(),
            "headers": self.translate_headers_var.get(),
            "pdf": self.export_pdf_var.get(),
        }
        threading.Thread(target=self._work, kwargs=args, daemon=True).start()

    def _work(self, source: Path, output: Path, glossary: Path | None, tables: bool, headers: bool, pdf: bool) -> None:
        try:
            translator = OnlineTranslator(
                glossary_path=glossary,
                cache_path=output / "translation_cache.sqlite3",
                log_callback=lambda msg: self.events.put(("log", msg)),
            )
            processor = DocumentProcessor(
                translator=translator,
                progress_callback=lambda d, t: self.events.put(("progress", (d, t))),
                log_callback=lambda msg: self.events.put(("log", msg)),
            )
            result_docx = processor.process(source, output, tables, headers)
            result_pdf = None
            if pdf:
                self.events.put(("log", "Экспорт в PDF…"))
                result_pdf = export_docx_to_pdf(result_docx)
                if result_pdf is None:
                    self.events.put(("log", "PDF не создан. DOCX сохранён."))
            self.events.put(("done", (result_docx, result_pdf)))
        except Exception as exc:
            self.events.put(("error", f"{exc}\n\n{traceback.format_exc()}"))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "progress":
                    done, total = payload
                    self._set_progress(int(done), int(total))
                elif event == "done":
                    docx, pdf = payload
                    self.start_button.configure(state="normal")
                    self._append_log(f"Готово: {docx}")
                    if pdf:
                        self._append_log(f"Готово: {pdf}")
                    messagebox.showinfo(APP_TITLE, f"Перевод завершён.\n\nDOCX:\n{docx}" + (f"\n\nPDF:\n{pdf}" if pdf else ""))
                elif event == "error":
                    self.start_button.configure(state="normal")
                    self._append_log("ОШИБКА:\n" + str(payload))
                    messagebox.showerror(APP_TITLE, "Произошла ошибка. Пришлите скрин конца журнала.")
        except queue.Empty:
            pass
        self.after(120, self._poll_events)


if __name__ == "__main__":
    TranslatorApp().mainloop()
