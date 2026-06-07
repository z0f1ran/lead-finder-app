#!/usr/bin/env python3
"""
Поиск клиентов — простое окно поверх lead_finder.

Запуск:
    python3 lead_finder_gui.py

Что делает: вводишь город, выбираешь ниши (или все) -> жмёшь «Искать».
Программа берёт организации из OpenStreetMap, проверяет их сайты и сохраняет
CSV. Имя файла = город + ниша (напр. казань__автосервис.csv).
Открыть CSV можно в Excel / Google Таблицах.
"""

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
        self.geometry("760x640")
        self.minsize(640, 540)

        self.log_q = queue.Queue()
        self.worker = None
        self.out_dir = os.path.abspath(".")

        self._build()
        self.after(100, self._drain_log)

    # ---------------------------------------------------------------- UI
    def _build(self):
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Город:").grid(row=0, column=0, sticky="w")
        self.city_var = tk.StringVar(value="Казань")
        ttk.Entry(top, textvariable=self.city_var, width=30).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(top, text="Лимит организаций:").grid(row=0, column=2, sticky="e", padx=(20, 0))
        self.limit_var = tk.IntVar(value=60)
        ttk.Spinbox(top, from_=10, to=500, increment=10, width=6,
                    textvariable=self.limit_var).grid(row=0, column=3, sticky="w", padx=6)

        # --- ниши ---
        nf = ttk.LabelFrame(self, text="Ниши (ничего не отмечено = все ниши)")
        nf.pack(fill="both", expand=True, **pad)

        bar = ttk.Frame(nf)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Выбрать все", command=self._select_all).pack(side="left")
        ttk.Button(bar, text="Снять все", command=self._select_none).pack(side="left", padx=6)

        # прокручиваемый список чекбоксов
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

        # --- папка вывода ---
        of = ttk.Frame(self)
        of.pack(fill="x", **pad)
        ttk.Label(of, text="Папка для CSV:").pack(side="left")
        self.dir_var = tk.StringVar(value=self.out_dir)
        ttk.Entry(of, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(of, text="Выбрать...", command=self._choose_dir).pack(side="left")

        # --- кнопки ---
        af = ttk.Frame(self)
        af.pack(fill="x", **pad)
        self.run_btn = ttk.Button(af, text="🔍  Искать клиентов", command=self._run)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(af, text="Открыть CSV", command=self._open_result, state="disabled")
        self.open_btn.pack(side="left", padx=6)
        self.pb = ttk.Progressbar(af, mode="indeterminate")
        self.pb.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # --- лог ---
        lframe = ttk.LabelFrame(self, text="Ход работы")
        lframe.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(lframe, height=10, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb = ttk.Scrollbar(lframe, command=self.log.yview)
        lsb.pack(side="right", fill="y")
        self.log["yscrollcommand"] = lsb.set

        self.result_path = None

    # ------------------------------------------------------------ helpers
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

    # ------------------------------------------------------------ run
    def _run(self):
        if self.worker and self.worker.is_alive():
            return
        city = self.city_var.get().strip()
        if not city:
            messagebox.showwarning("Нужен город", "Впиши город, напр. Казань.")
            return
        selected = [n for n, v in self.niche_vars.items() if v.get()]
        niches = selected or None   # пусто = все ниши
        limit = max(1, int(self.limit_var.get()))
        out_dir = self.dir_var.get().strip() or "."
        out = os.path.join(out_dir, lf.make_filename(city, niches))

        self.run_btn["state"] = "disabled"
        self.open_btn["state"] = "disabled"
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
        except Exception as e:
            self._logmsg(f"ОШИБКА: {e}")
        finally:
            self.after(0, self._done)

    def _done(self):
        self.pb.stop()
        self.run_btn["state"] = "normal"
        if self.result_path and os.path.exists(self.result_path):
            self.open_btn["state"] = "normal"

    def _open_result(self):
        p = self.result_path
        if not p or not os.path.exists(p):
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", p])
            elif os.name == "nt":
                os.startfile(p)   # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", p])
        except Exception as e:
            messagebox.showinfo("Файл сохранён", f"{p}\n\n(открыть не удалось: {e})")


if __name__ == "__main__":
    App().mainloop()
