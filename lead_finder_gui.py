#!/usr/bin/env python3
"""
Поиск клиентов — простое окно поверх lead_finder.

Запуск:
    python3 lead_finder_gui.py

Вкладка «Поиск»: вводишь город, выбираешь ниши -> «Искать». Программа берёт
организации из OpenStreetMap, проверяет сайты и сохраняет CSV. Имя файла =
город + ниша (напр. казань__автосервис.csv).

Вкладка «Результаты»: список CSV в папке — открыть таблицей или удалить.
"""

import csv
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import lead_finder as lf


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Поиск клиентов")
        self.geometry("820x680")
        self.minsize(680, 560)

        self.log_q = queue.Queue()
        self.worker = None
        self.result_path = None
        self.out_dir = os.path.abspath(".")
        self.dir_var = tk.StringVar(value=self.out_dir)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.tab_search = ttk.Frame(nb)
        self.tab_results = ttk.Frame(nb)
        nb.add(self.tab_search, text="  Поиск  ")
        nb.add(self.tab_results, text="  Результаты  ")
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_files())

        self._build_search(self.tab_search)
        self._build_results(self.tab_results)

        self.after(100, self._drain_log)

    # ====================================================== вкладка ПОИСК
    def _build_search(self, root):
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Город:").grid(row=0, column=0, sticky="w")
        self.city_var = tk.StringVar(value="Казань")
        ttk.Entry(top, textvariable=self.city_var, width=30).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(top, text="Лимит организаций:").grid(row=0, column=2, sticky="e", padx=(20, 0))
        self.limit_var = tk.IntVar(value=60)
        ttk.Spinbox(top, from_=10, to=500, increment=10, width=6,
                    textvariable=self.limit_var).grid(row=0, column=3, sticky="w", padx=6)

        nf = ttk.LabelFrame(root, text="Ниши (ничего не отмечено = все ниши)")
        nf.pack(fill="both", expand=True, **pad)
        bar = ttk.Frame(nf)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Выбрать все", command=self._select_all).pack(side="left")
        ttk.Button(bar, text="Снять все", command=self._select_none).pack(side="left", padx=6)

        canvas = tk.Canvas(nf, highlightthickness=0)
        sb = ttk.Scrollbar(nf, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        sb.pack(side="right", fill="y")
        self.niche_vars = {}
        cols = 3
        for i, niche in enumerate(lf.NICHES):
            v = tk.BooleanVar(value=False)
            self.niche_vars[niche] = v
            ttk.Checkbutton(inner, text=niche, variable=v).grid(
                row=i // cols, column=i % cols, sticky="w", padx=8, pady=2)

        of = ttk.Frame(root)
        of.pack(fill="x", **pad)
        ttk.Label(of, text="Папка для CSV:").pack(side="left")
        ttk.Entry(of, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(of, text="Выбрать...", command=self._choose_dir).pack(side="left")

        af = ttk.Frame(root)
        af.pack(fill="x", **pad)
        self.run_btn = ttk.Button(af, text="🔍  Искать клиентов", command=self._run)
        self.run_btn.pack(side="left")
        self.pb = ttk.Progressbar(af, mode="indeterminate")
        self.pb.pack(side="right", fill="x", expand=True, padx=(10, 0))

        lframe = ttk.LabelFrame(root, text="Ход работы")
        lframe.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(lframe, height=8, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb = ttk.Scrollbar(lframe, command=self.log.yview)
        lsb.pack(side="right", fill="y")
        self.log["yscrollcommand"] = lsb.set

    # =================================================== вкладка РЕЗУЛЬТАТЫ
    def _build_results(self, root):
        pad = {"padx": 10, "pady": 6}
        ttk.Label(root, text="CSV-файлы в папке результатов:").pack(anchor="w", **pad)

        lf_ = ttk.Frame(root)
        lf_.pack(fill="both", expand=True, padx=10)
        self.files = tk.Listbox(lf_, height=12)
        self.files.pack(side="left", fill="both", expand=True)
        self.files.bind("<Double-Button-1>", lambda e: self._open_table())
        fsb = ttk.Scrollbar(lf_, command=self.files.yview)
        fsb.pack(side="right", fill="y")
        self.files["yscrollcommand"] = fsb.set

        bf = ttk.Frame(root)
        bf.pack(fill="x", **pad)
        ttk.Button(bf, text="📊  Открыть таблицей", command=self._open_table).pack(side="left")
        ttk.Button(bf, text="Открыть в Excel", command=self._open_external).pack(side="left", padx=6)
        ttk.Button(bf, text="🗑  Удалить", command=self._delete_file).pack(side="left")
        ttk.Button(bf, text="Обновить список", command=self._refresh_files).pack(side="right")

    def _refresh_files(self):
        if not hasattr(self, "files"):
            return
        d = self.dir_var.get().strip() or "."
        self.files.delete(0, "end")
        try:
            names = sorted(f for f in os.listdir(d) if f.lower().endswith(".csv"))
        except OSError:
            names = []
        for n in names:
            self.files.insert("end", n)

    def _selected_path(self):
        sel = self.files.curselection()
        if not sel:
            messagebox.showinfo("Выбери файл", "Сначала выбери CSV в списке.")
            return None
        return os.path.join(self.dir_var.get().strip() or ".", self.files.get(sel[0]))

    def _open_table(self):
        path = self._selected_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не прочитать файл:\n{e}")
            return
        if not rows:
            messagebox.showinfo("Пусто", "Файл пустой.")
            return

        win = tk.Toplevel(self)
        win.title(os.path.basename(path))
        win.geometry("1000x560")
        headers, data = rows[0], rows[1:]

        wrap = ttk.Frame(win)
        wrap.pack(fill="both", expand=True)
        tv = ttk.Treeview(wrap, columns=list(range(len(headers))), show="headings")
        for i, h in enumerate(headers):
            tv.heading(i, text=h)
            w = 70 if i == 0 else (260 if h in ("Название", "Сайт") else 130)
            tv.column(i, width=w, anchor="w")
        for row in data:
            tv.insert("", "end", values=row)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        ttk.Label(win, text=f"Строк: {len(data)}").pack(anchor="w", padx=8, pady=4)

    def _open_external(self):
        path = self._selected_path()
        if not path or not os.path.exists(path):
            return
        self._open_file(path)

    def _delete_file(self):
        path = self._selected_path()
        if not path or not os.path.exists(path):
            return
        if not messagebox.askyesno("Удалить файл?",
                                   f"Удалить безвозвратно?\n\n{os.path.basename(path)}"):
            return
        try:
            os.remove(path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалить:\n{e}")
            return
        self._refresh_files()

    # ============================================================ общее
    def _select_all(self):
        for v in self.niche_vars.values():
            v.set(True)

    def _select_none(self):
        for v in self.niche_vars.values():
            v.set(False)

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or ".")
        if d:
            self.dir_var.set(d)
            self._refresh_files()

    def _logmsg(self, msg):
        self.log_q.put(str(msg))

    def _drain_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log["state"] = "normal"
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log["state"] = "disabled"
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _open_file(self, p):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", p])
            elif os.name == "nt":
                os.startfile(p)   # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", p])
        except Exception as e:
            messagebox.showinfo("Файл", f"{p}\n\n(открыть не удалось: {e})")

    # ============================================================ запуск
    def _run(self):
        if self.worker and self.worker.is_alive():
            return
        city = self.city_var.get().strip()
        if not city:
            messagebox.showwarning("Нужен город", "Впиши город, напр. Казань.")
            return
        selected = [n for n, v in self.niche_vars.items() if v.get()]
        niches = selected or None
        limit = max(1, int(self.limit_var.get()))
        out_dir = self.dir_var.get().strip() or "."
        out = os.path.join(out_dir, lf.make_filename(city, niches))

        self.run_btn["state"] = "disabled"
        self.pb.start(12)
        self._logmsg(f"=== Старт. Файл: {os.path.basename(out)} ===")
        self.worker = threading.Thread(
            target=self._work, args=(city, niches, limit, out), daemon=True)
        self.worker.start()

    def _work(self, city, niches, limit, out):
        try:
            rows, out = lf.run_search(city=city, niches=niches, limit=limit,
                                      out=out, progress=self._logmsg)
            self.result_path = out
            hot = sum(1 for r in rows if r["score"] >= 70)
            self._logmsg(f"Горячих лидов (скор ≥ 70): {hot} из {len(rows)}")
            self._logmsg("Открой вкладку «Результаты», чтобы посмотреть таблицу.")
        except Exception as e:
            self._logmsg(f"ОШИБКА: {e}")
        finally:
            self.after(0, self._done)

    def _done(self):
        self.pb.stop()
        self.run_btn["state"] = "normal"
        self._refresh_files()


if __name__ == "__main__":
    App().mainloop()
