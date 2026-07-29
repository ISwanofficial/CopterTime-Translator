from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from coptertime_docs.storage.database import Database


class GlossaryWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, database: Database) -> None:
        super().__init__(master)
        self.database = database
        self.selected_id: int | None = None

        self.title("Словари — CopterTime Docs")
        self.geometry("980x620")
        self.minsize(820, 520)
        self.transient(master)

        self.search_var = tk.StringVar()
        self.brand_filter_var = tk.StringVar(value="Все бренды")
        self.edit_brand_var = tk.StringVar(value="General")
        self.source_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.approved_var = tk.BooleanVar(value=True)

        self._build()
        self.refresh()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Поиск:").pack(side="left")
        search = ttk.Entry(top, textvariable=self.search_var, width=34)
        search.pack(side="left", padx=(6, 12))
        search.bind("<KeyRelease>", lambda _event: self.refresh())

        ttk.Label(top, text="Бренд:").pack(side="left")
        self.brand_filter = ttk.Combobox(
            top,
            textvariable=self.brand_filter_var,
            state="readonly",
            width=18,
        )
        self.brand_filter.pack(side="left", padx=6)
        self.brand_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Button(top, text="Новый термин", command=self.clear_form).pack(side="right")

        content = ttk.Panedwindow(self, orient="horizontal")
        content.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        list_frame = ttk.Frame(content)
        edit_frame = ttk.LabelFrame(content, text="Карточка термина", padding=14)
        content.add(list_frame, weight=3)
        content.add(edit_frame, weight=2)

        columns = ("brand", "source", "target", "approved")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("brand", text="Бренд")
        self.tree.heading("source", text="Английский")
        self.tree.heading("target", text="Русский")
        self.tree.heading("approved", text="Проверен")
        self.tree.column("brand", width=100)
        self.tree.column("source", width=200)
        self.tree.column("target", width=240)
        self.tree.column("approved", width=70, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._select_row)

        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        ttk.Label(edit_frame, text="Бренд").grid(row=0, column=0, sticky="w")
        self.edit_brand = ttk.Combobox(
            edit_frame,
            textvariable=self.edit_brand_var,
            width=30,
        )
        self.edit_brand.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(edit_frame, text="Английский термин").grid(row=2, column=0, sticky="w")
        ttk.Entry(edit_frame, textvariable=self.source_var).grid(
            row=3, column=0, sticky="ew", pady=(4, 12)
        )

        ttk.Label(edit_frame, text="Русский перевод").grid(row=4, column=0, sticky="w")
        ttk.Entry(edit_frame, textvariable=self.target_var).grid(
            row=5, column=0, sticky="ew", pady=(4, 12)
        )

        ttk.Label(edit_frame, text="Комментарий").grid(row=6, column=0, sticky="w")
        self.notes = tk.Text(edit_frame, height=6, wrap="word")
        self.notes.grid(row=7, column=0, sticky="nsew", pady=(4, 12))

        ttk.Checkbutton(
            edit_frame,
            text="Термин проверен",
            variable=self.approved_var,
        ).grid(row=8, column=0, sticky="w")

        buttons = ttk.Frame(edit_frame)
        buttons.grid(row=9, column=0, sticky="ew", pady=(18, 0))
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Удалить", command=self.delete).pack(side="left", padx=8)

        edit_frame.columnconfigure(0, weight=1)
        edit_frame.rowconfigure(7, weight=1)

    def refresh(self) -> None:
        brands = self.database.list_brands()
        self.brand_filter["values"] = ["Все бренды", *brands]
        self.edit_brand["values"] = brands

        rows = self.database.search_terms(
            query=self.search_var.get(),
            brand=self.brand_filter_var.get(),
        )

        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["brand"],
                    row["source_text"],
                    row["target_text"],
                    "Да" if row["approved"] else "Нет",
                ),
                tags=(row["notes"],),
            )

    def _select_row(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        self.selected_id = int(item_id)
        values = self.tree.item(item_id, "values")
        self.edit_brand_var.set(values[0])
        self.source_var.set(values[1])
        self.target_var.set(values[2])
        self.approved_var.set(values[3] == "Да")
        tags = self.tree.item(item_id, "tags")
        self.notes.delete("1.0", "end")
        if tags:
            self.notes.insert("1.0", tags[0])

    def clear_form(self) -> None:
        self.selected_id = None
        self.edit_brand_var.set("General")
        self.source_var.set("")
        self.target_var.set("")
        self.approved_var.set(True)
        self.notes.delete("1.0", "end")
        self.tree.selection_remove(self.tree.selection())

    def save(self) -> None:
        try:
            self.database.upsert_term(
                self.edit_brand_var.get(),
                self.source_var.get(),
                self.target_var.get(),
                self.approved_var.get(),
                self.notes.get("1.0", "end").strip(),
            )
        except ValueError as error:
            messagebox.showwarning("Проверьте данные", str(error), parent=self)
            return
        self.refresh()
        self.clear_form()

    def delete(self) -> None:
        if self.selected_id is None:
            return
        if not messagebox.askyesno(
            "Удаление",
            "Удалить выбранный термин?",
            parent=self,
        ):
            return
        self.database.delete_term(self.selected_id)
        self.refresh()
        self.clear_form()
